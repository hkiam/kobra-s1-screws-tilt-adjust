"""Der eigentliche Messablauf am Drucker."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from .config import Config, Screw
from .moonraker import Moonraker, MoonrakerError
from .screws import Measurement

Notify = Callable[[str], None]

# Zwischen zwei Antastungen am selben Punkt anheben - sonst loest das naechste
# PROBE sofort aus, weil die Duese noch auf dem Bett steht.
RETRACT_MM = 2.0


def _noop(_: str) -> None:
    pass


def check_capabilities(mr: Moonraker) -> dict[str, bool]:
    """Prueft, ob die eingeschraenkte Firmware alles Noetige mitbringt."""
    try:
        commands = {c.upper() for c in mr.gcode_help()}
    except MoonrakerError:
        commands = set()
    objects = set(mr.objects_list())

    # Rinkhals fuehrt "probe" nicht in objects/list, beantwortet die Abfrage
    # aber trotzdem - deshalb direkt testen statt der Liste zu glauben.
    try:
        probe_status = mr.query("probe").get("probe", {})
        has_probe_status = "last_z_result" in probe_status
    except MoonrakerError:
        has_probe_status = False

    return {
        "PROBE-Kommando": "PROBE" in commands,
        "probe.last_z_result": has_probe_status,
        "toolhead-Objekt": "toolhead" in objects,
        "SCREWS_TILT_ADJUST (dann waere dies hier unnoetig)": "SCREWS_TILT_ADJUST" in commands,
    }


def mesh_status(mr: Moonraker) -> dict[str, object]:
    """Aktives Bed Mesh und Z-Offset auslesen."""
    status = mr.query("bed_mesh", "gcode_move")
    bed_mesh = status.get("bed_mesh", {}) or {}
    gcode_move = status.get("gcode_move", {}) or {}
    matrix = bed_mesh.get("mesh_matrix") or []
    values = [v for row in matrix for v in row]
    homing_origin = gcode_move.get("homing_origin") or [0, 0, 0, 0]
    return {
        "profile": bed_mesh.get("profile_name") or "",
        "matrix": matrix,
        "active": bool(values),
        "span": (max(values) - min(values)) if values else 0.0,
        "z_offset": float(homing_origin[2]) if len(homing_origin) > 2 else 0.0,
    }


def save_mesh(status: dict[str, object], directory: Path) -> Path | None:
    """Das aktive Mesh als JSON sichern, bevor es geloescht wird."""
    if not status.get("active"):
        return None
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = directory / f"mesh-{stamp}.json"
    path.write_text(
        json.dumps(
            {
                "gespeichert": stamp,
                "profil": status.get("profile"),
                "matrix": status.get("matrix"),
            },
            indent=2,
        )
    )
    return path


def probe_ignores_mesh(mr: Moonraker, probe_z: float) -> bool | None:
    """Prueft, ob ein Messwert die rohe Kinematikposition ist.

    Am Geraet verifiziert: PROBE liefert die rohe Kinematik-Z, nicht die
    mesh-transformierte gcode-Position - ein geladenes Bed Mesh verfaelscht
    die Messung also nicht. Weil das eine Eigenschaft der Firmware ist und
    kein Naturgesetz, wird es beim Messen einmal nachgeprueft statt geglaubt.

    Rueckgabe: True (roh), False (mesh-behaftet) oder None (nicht pruefbar).
    """
    raw, gcode = mr.raw_and_gcode_z()
    if raw is None or gcode is None:
        return None
    if abs(raw - gcode) < 0.01:
        return None  # gerade keine Mesh-Korrektur wirksam: nicht unterscheidbar
    return abs(probe_z - raw) < abs(probe_z - gcode)


def heat(cfg: Config, mr: Moonraker, *, nozzle: float | None = None, notify: Notify = _noop) -> None:
    target_nozzle = cfg.temps.nozzle_probe if nozzle is None else nozzle
    notify(f"Heize Bett auf {cfg.temps.bed:.0f} C und Duese auf {target_nozzle:.0f} C ...")
    mr.script(f"M140 S{cfg.temps.bed:.0f}")
    mr.script(f"M104 S{target_nozzle:.0f}")
    last = [0.0]

    def progress(temps: dict[str, dict[str, float]]) -> None:
        now = time.monotonic()
        if now - last[0] < 5.0:
            return
        last[0] = now
        notify(
            f"  Bett {temps['heater_bed']['temperature']:5.1f} C / {cfg.temps.bed:.0f} C   "
            f"Duese {temps['extruder']['temperature']:5.1f} C / {target_nozzle:.0f} C"
        )

    def on_reset(temps: dict[str, dict[str, float]]) -> None:
        notify(
            f"  Sollwert war zurueckgesetzt (Bett {temps['heater_bed']['target']:.0f} C, "
            f"Duese {temps['extruder']['target']:.0f} C) - wird erneut gesetzt."
        )

    mr.wait_for_temperature(
        extruder=target_nozzle,
        bed=cfg.temps.bed,
        on_progress=progress,
        on_reset=on_reset,
    )
    notify("Temperaturen erreicht.")


def home(mr: Moonraker, *, force: bool = False, notify: Notify = _noop) -> None:
    axes = mr.homed_axes()
    if not force and all(a in axes for a in "xyz"):
        return  # still: wird vor jedem Durchgang geprueft, das muss nicht jedes Mal auffallen

    notify("Referenzfahrt (G28) ...")
    mr.script("G28")
    # G28 wird auch dann bestaetigt, wenn hinterher nichts referenziert ist -
    # etwa weil der Leerlauf-Timeout die Motoren gleich wieder abschaltet.
    # Ohne diese Pruefung liefe die ganze Messung ins Leere.
    axes = mr.homed_axes()
    if not all(a in axes for a in "xyz"):
        raise MoonrakerError(
            f"Nach G28 sind die Achsen weiterhin nicht referenziert (homed_axes={axes!r}). "
            "Am Drucker pruefen - haeufig hilft ein Neustart der Firmware."
        )


def wipe(cfg: Config, mr: Moonraker, *, notify: Notify = _noop) -> None:
    if not cfg.wipe.enabled:
        return
    notify(f"Duese reinigen bei {cfg.temps.nozzle_wipe:.0f} C ...")
    mr.script(f"M104 S{cfg.temps.nozzle_wipe:.0f}")
    mr.wait_for_temperature(extruder=cfg.temps.nozzle_wipe)
    for line in cfg.wipe.gcode.strip().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            mr.script(line)
    mr.script("M400")
    notify(f"Zurueck auf Antast-Temperatur {cfg.temps.nozzle_probe:.0f} C ...")
    mr.script(f"M104 S{cfg.temps.nozzle_probe:.0f}")
    mr.wait_for_temperature(extruder=cfg.temps.nozzle_probe, tolerance=3.0)


def goto(cfg: Config, mr: Moonraker, x: float, y: float) -> None:
    mr.script("G90")
    mr.script(f"G1 Z{cfg.probe.safe_z:.2f} F{cfg.probe.lift_speed * 60:.0f}")
    mr.script(f"G1 X{x:.3f} Y{y:.3f} F{cfg.probe.travel_speed * 60:.0f}")
    mr.script("M400")


def probe_at(
    cfg: Config,
    mr: Moonraker,
    screw: Screw,
    count: int,
    *,
    verify: bool = False,
    notify: Notify = _noop,
) -> list[float]:
    """Punkt anfahren und dort count-mal antasten."""
    goto(cfg, mr, screw.x, screw.y)
    if cfg.probe.settle_seconds > 0:
        time.sleep(cfg.probe.settle_seconds)

    total = count + (1 if cfg.probe.discard_first else 0)
    values: list[float] = []
    for i in range(total):
        mr.script("PROBE")
        z = mr.last_probe_z()
        if z is None:
            raise MoonrakerError(
                "PROBE lieferte kein Ergebnis (probe.last_z_result ist leer). "
                "Unterstuetzt diese Firmware das PROBE-Kommando?"
            )
        if verify and i == 0 and probe_ignores_mesh(mr, z) is False:
            notify(
                "  ! Der Messwert folgt der mesh-korrigierten Position. "
                "Ein geladenes Bed Mesh verfaelscht damit die Messung - Ergebnisse "
                "sind nicht belastbar."
            )
        # Anheben, damit die naechste Antastung wieder aus der Luft startet.
        mr.script("G91")
        mr.script(f"G1 Z{RETRACT_MM:.2f} F{cfg.probe.lift_speed * 60:.0f}")
        mr.script("G90")
        mr.script("M400")

        if cfg.probe.discard_first and i == 0:
            notify(f"  {screw.name}: Vormessung z={z:.4f} (verworfen)")
            continue
        values.append(z)
        notify(f"  {screw.name}: z={z:.4f}")
    return values


def bewerten(cfg: Config, m: Measurement, notify: Notify = _noop) -> Measurement:
    """Auffaelligkeiten melden, gemessen an der Toleranz."""
    toleranz = cfg.screws.tolerance_mm

    def in_minuten(mm: float) -> float:
        return abs(mm) / cfg.screws.pitch * 60

    if m.gap > toleranz:
        notify(
            f"  ! {m.screw.name}: Werte zerfallen in zwei Gruppen, {m.gap:.4f} mm "
            f"({in_minuten(m.gap):.0f} Minuten) auseinander - die Lagerung rastet "
            f"zwischen zwei Lagen ein."
        )
    elif abs(m.drift) > toleranz:
        notify(
            f"  ! {m.screw.name}: driftet um {m.drift:+.4f} mm "
            f"({in_minuten(m.drift):.0f} Minuten) - mehr als die Toleranz."
        )
    elif m.spread > toleranz:
        notify(
            f"  ! {m.screw.name}: streut um {m.spread:.4f} mm "
            f"({in_minuten(m.spread):.0f} Minuten) - ueber der Toleranz."
        )
    return m


def probe_point(
    cfg: Config, mr: Moonraker, screw: Screw, *, verify: bool = False, notify: Notify = _noop
) -> Measurement:
    values = probe_at(cfg, mr, screw, cfg.probe.samples_per_point, verify=verify, notify=notify)
    return bewerten(cfg, Measurement(screw=screw, samples=values), notify)


def kreuzweise(points: list[Screw]) -> list[Screw]:
    """Reihenfolge ueber Kreuz statt reihum.

    So werden benachbarte Ecken nie direkt nacheinander belastet; jede Stelle
    bekommt zwischen zwei Antastungen Zeit, sich zu erholen.
    """
    return points[::2] + points[1::2]


def measure_all(cfg: Config, mr: Moonraker, *, notify: Notify = _noop) -> list[Measurement]:
    """Alle Punkte messen - verschraenkt ueber mehrere Durchgaenge.

    Nicht jeden Punkt am Stueck: Senkt sich das Bett waehrend der Messreihe,
    erschiene sonst der zuletzt gemessene Punkt systematisch tiefer, und aus
    einem reinen Zeiteffekt wuerde eine Scheinverkippung.

    Deshalb wird die Reihenfolge in jedem zweiten Durchgang umgekehrt. Damit
    liegt der zeitliche Schwerpunkt jeder Ecke in der Mitte der Gesamtreihe
    und ein gleichmaessiger Zeittrend hebt sich rechnerisch auf, statt nur
    kleiner zu werden.
    """
    # Zwischen zwei Durchgaengen vergeht Zeit am Schraubendreher. Faellt der
    # Drucker dabei in den Leerlauf, sind die Motoren stromlos und die
    # Referenzfahrt ist weg - dann lieber neu referenzieren als blind messen.
    home(mr, notify=notify)

    punkte = kreuzweise(list(cfg.screws.points))
    passes = max(1, cfg.probe.passes)
    gesamt = cfg.probe.samples_per_point
    # Samples moeglichst gleichmaessig auf die Durchgaenge verteilen.
    je_durchgang = [gesamt // passes + (1 if i < gesamt % passes else 0) for i in range(passes)]

    proben: dict[str, list[float]] = {s.name: [] for s in punkte}
    erster = True
    for nr, anzahl in enumerate(je_durchgang):
        if anzahl == 0:
            continue
        reihenfolge = punkte if nr % 2 == 0 else list(reversed(punkte))
        if passes > 1:
            namen = " -> ".join(s.name for s in reihenfolge)
            notify(f"Durchgang {nr + 1}/{passes} ({anzahl}x je Punkt): {namen}")
        for screw in reihenfolge:
            proben[screw.name] += probe_at(
                cfg, mr, screw, anzahl, verify=erster, notify=notify
            )
            erster = False

    mr.script("G90")
    mr.script(f"G1 Z{cfg.probe.safe_z:.2f} F{cfg.probe.lift_speed * 60:.0f}")
    mr.script("M400")

    return [
        bewerten(cfg, Measurement(screw=s, samples=proben[s.name]), notify)
        for s in cfg.screws.points
    ]


def park(cfg: Config, mr: Moonraker, *, notify: Notify = _noop) -> None:
    """Druckkopf aus dem Weg fahren, damit von Hand geschraubt werden kann."""
    if not cfg.park.enabled:
        return
    notify("Fahre den Druckkopf aus dem Weg ...")
    mr.script("G90")
    # Erst das Bett absenken, dann den Kopf zur Seite - nie umgekehrt.
    mr.script(f"G1 Z{cfg.park.z:.2f} F{cfg.probe.lift_speed * 60:.0f}")
    mr.script(f"G1 X{cfg.park.x:.3f} Y{cfg.park.y:.3f} F{cfg.probe.travel_speed * 60:.0f}")
    mr.script("M400")


def cooldown(mr: Moonraker, *, notify: Notify = _noop) -> None:
    notify("Heizungen aus.")
    mr.script("M104 S0")
    mr.script("M140 S0")
