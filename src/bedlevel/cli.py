"""Kommandozeile fuer die Bettjustage."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from . import config as config_mod
from . import procedure
from . import spacers as spacers_mod
from .keepalive import Keepalive
from . import teach as teach_mod
from .config import Config
from .moonraker import Moonraker, MoonrakerError
from .screws import Adjustment, Measurement, Report, build_report

console = Console()


class InteractiveNeeded(RuntimeError):
    """Das Kommando braucht ein interaktives Terminal."""


def minuten(wert: float) -> str:
    return f"{wert:.0f} Minute" if round(wert) == 1 else f"{wert:.0f} Minuten"


def notify(msg: str) -> None:
    console.print(msg, highlight=False)


def require_tty(kommando: str) -> None:
    """Ohne Terminal gibt es keine Handarbeit - dann lieber gleich sagen."""
    if not sys.stdin.isatty():
        raise InteractiveNeeded(
            f"'{kommando}' fuehrt dich Schritt fuer Schritt durch die Justage und wartet "
            "dabei auf deine Eingabe. Das braucht ein echtes Terminal - bitte direkt in "
            "einer Shell starten, nicht ueber eine Pipe.\n"
            "Nur messen, ohne Nachstellen: 'bedlevel measure'."
        )


def ask(prompt: str) -> str:
    """Eingabe lesen; ein abgerissenes stdin gilt als Abbruch."""
    try:
        return console.input(prompt)
    except (EOFError, KeyboardInterrupt):
        console.print()
        return "q"


def connect(cfg: Config) -> Moonraker:
    mr = Moonraker(cfg.printer.base_url, cfg.printer.api_key)
    mr.require_ready()
    return mr


def keepalive_for(mr: Moonraker) -> Keepalive:
    return Keepalive(
        mr, on_error=lambda msg: console.print(f"[dim]Keepalive: {msg}[/]")
    )


# -- Ausgabe ---------------------------------------------------------------


def bed_sketch(report: Report) -> str | None:
    """Die vier Ecken als Draufsicht auf das Bett.

    Die Zuordnung kommt aus den Koordinaten, nicht aus den Namen: kleines Y
    ist vorne, grosses X rechts. So stimmt das Bild auch bei abweichender
    Benennung der Schrauben.
    """
    if len(report.adjustments) != 4:
        return None

    xs = [a.screw.x for a in report.adjustments]
    ys = [a.screw.y for a in report.adjustments]
    mx, my = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2

    ecken: dict[tuple[bool, bool], Adjustment] = {}
    for a in report.adjustments:
        ecken[(a.screw.x > mx, a.screw.y > my)] = a
    if len(ecken) != 4:
        return None  # keine rechteckige Anordnung

    def feld(rechts: bool, hinten: bool) -> str:
        a = ecken[(rechts, hinten)]
        if a.unreliable:
            return "   ?.???"
        return f"{a.delta:+8.3f}"

    return (
        "        hinten\n"
        f"  {feld(False, True)}   {feld(True, True)}\n"
        "        ┌───────────┐\n"
        "  links │           │ rechts\n"
        "        └───────────┘\n"
        f"  {feld(False, False)}   {feld(True, False)}\n"
        "        vorne"
    )


def render_report(cfg: Config, report: Report) -> None:
    modus = f", {cfg.screws.reference}" if cfg.screws.reference != report.reference else ""
    table = Table(
        title=f"Messung  (Referenz: {report.reference}{modus})", header_style="bold"
    )
    table.add_column("Schraube", no_wrap=True)
    table.add_column("XY", justify="right", no_wrap=True)
    table.add_column("z", justify="right", no_wrap=True)
    table.add_column("+/-", justify="right", no_wrap=True)
    table.add_column("Abw.", justify="right", no_wrap=True)
    table.add_column("adjust", no_wrap=True)

    for a in report.adjustments:
        if a.unreliable:
            style = "bold red"
        elif a.is_reference:
            style = "cyan"
        elif a.ok:
            style = "green"
        elif a.turns * 60 > 4 * report.tolerance_minutes:
            style = "red"
        else:
            style = "yellow"
        table.add_row(
            a.screw.name,
            f"{a.screw.x:g}/{a.screw.y:g}",
            f"{a.z:+.3f}",
            f"{a.spread:.3f}",
            f"{a.delta:+.3f}",
            f"{a.unreliable}" if a.unreliable else a.action,
            style=style,
        )
    console.print(table)

    lines = [
        f"Groesste Korrektur: [bold]{minuten(report.worst_minutes)}[/] "
        f"- {report.bewertung}  (Ziel: <= 00:{report.tolerance_minutes:02.0f})",
        f"Spannweite hoch/tief: [bold]{report.span:.3f} mm[/] "
        f"= {minuten(report.span_minutes)}",
    ]
    if report.plane is not None:
        tx, ty = report.plane.tilt_mm_per_m()
        lines.append(f"Verkippung: X {tx:+.2f} mm/m, Y {ty:+.2f} mm/m")
        verzug_min = report.plane.peak_to_peak / report.pitch * 60
        lines.append(
            f"Bettverzug (nicht wegdrehbar): [bold]{report.plane.peak_to_peak:.3f} mm[/] "
            f"= {minuten(verzug_min)} - der erreichbare Boden, Rest gehoert ins Bed Mesh"
        )
    console.print(Panel("\n".join(lines), title="Kennzahlen", border_style="dim"))

    skizze = bed_sketch(report)
    if skizze:
        console.print(
            Panel(skizze, title="Abweichung zur Referenz (mm)", border_style="dim", expand=False)
        )

    if not report.trustworthy:
        namen = ", ".join(a.screw.name for a in report.unreliable)
        console.print(
            Panel(
                f"Nicht tragfaehig gemessen: [bold]{namen}[/]\n\n"
                "An diesen Punkten beschreibt der Messwert keine stabile Bettlage. "
                "Eine Drehempfehlung daraus waere auf einen Phantomwert gerechnet, "
                "deshalb steht dort keine.\n"
                "Erst die Lagerung dort in Ordnung bringen, dann mit "
                "[bold]bedlevel stability \"<name>\"[/] nachpruefen.",
                title="Justage nicht moeglich",
                border_style="red",
            )
        )
        return

    if report.done:
        console.print(
            f"[bold green]Fertig - groesste Restabweichung 00:{report.worst_minutes:02.0f} "
            f"({report.bewertung}).[/]"
        )
    else:
        console.print(
            f"[dim]01:20 heisst 1 volle Umdrehung und 20 Minuten (15 Minuten = Viertelumdrehung).\n"
            f"CW = clockwise, im Uhrzeigersinn = anziehen, "
            f"{'senkt' if cfg.screws.cw_lowers_bed else 'hebt'} das Bett.  "
            f"CCW = counter-clockwise = loesen.\n"
            f"Gewinde {cfg.screws.thread}, {cfg.screws.pitch:.2f} mm pro voller Umdrehung. "
            f"z und Abw. in mm.[/]"
        )


# -- Kommandos -------------------------------------------------------------


def cmd_check(cfg: Config, args: argparse.Namespace) -> int:
    with Moonraker(cfg.printer.base_url, cfg.printer.api_key) as mr:
        return _check(cfg, mr)


def _check(cfg: Config, mr: Moonraker) -> int:
    info = mr.printer_info()
    console.print(
        Panel(
            f"Verbindung: {cfg.printer.base_url}\n"
            f"Zustand: [bold]{info.get('state')}[/]\n"
            f"Software: {info.get('software_version', 'unbekannt')}\n"
            f"Hostname: {info.get('hostname', 'unbekannt')}",
            title="Drucker",
        )
    )

    caps = procedure.check_capabilities(mr)
    table = Table(header_style="bold")
    table.add_column("Voraussetzung")
    table.add_column("vorhanden")
    for name, present in caps.items():
        table.add_row(name, "[green]ja[/]" if present else "[red]nein[/]")
    console.print(table)

    mesh = procedure.mesh_status(mr)
    if mesh["active"]:
        console.print(
            f"Bed Mesh {mesh['profile']!r} ist geladen (Korrektur bis "
            f"{float(mesh['span']):.3f} mm) - [green]ohne Einfluss auf die Messwerte[/], "
            "da PROBE die rohe Kinematikposition liefert. Wird bei jeder Messung "
            "am ersten Punkt nachgeprueft."
        )
    else:
        console.print("[dim]Kein Bed Mesh aktiv.[/]")

    limits = mr.axis_limits()
    if limits:
        console.print(
            "Fahrbereich: "
            + "  ".join(f"{ax.upper()} [{lo:g} .. {hi:g}]" for ax, (lo, hi) in limits.items())
        )

    for screw in cfg.screws.points:
        for axis, value in (("x", screw.x), ("y", screw.y)):
            lo, hi = limits.get(axis, (None, None))
            if lo is not None and not (lo <= value <= hi):
                console.print(
                    f"[red]Schraube {screw.name!r}: {axis.upper()}={value:g} liegt "
                    f"ausserhalb von [{lo:g} .. {hi:g}][/]"
                )

    if not caps["PROBE-Kommando"] or not caps["probe.last_z_result"]:
        console.print("[red]Ohne PROBE und probe.last_z_result kann dieses Tool nicht messen.[/]")
        return 1
    if caps["SCREWS_TILT_ADJUST (dann waere dies hier unnoetig)"]:
        console.print(
            "[yellow]Hinweis: Diese Firmware kennt SCREWS_TILT_ADJUST bereits - "
            "das Originalkommando ist dann meist die einfachere Wahl.[/]"
        )
    console.print("[green]Alles Noetige vorhanden.[/]")
    return 0


def _handle_mesh(cfg: Config, mr: Moonraker, args: argparse.Namespace) -> None:
    """Ueber Bed Mesh und Z-Offset informieren.

    Beides bleibt unangetastet: Ein konstanter Z-Offset verschiebt alle Punkte
    gleich und faellt bei der relativen Auswertung heraus. Und PROBE liefert
    auf dieser Firmware die rohe Kinematikposition, nicht die
    mesh-transformierte - ein geladenes Mesh verfaelscht die Messung also
    nicht. Beim Messen wird das einmal nachgeprueft.

    (BED_MESH_CLEAR ist hier wirkungslos: es wird quittiert, das Mesh bleibt
    geladen. Deshalb wird es gar nicht erst gesendet.)
    """
    status = procedure.mesh_status(mr)
    z_offset = float(status["z_offset"])
    if z_offset:
        console.print(f"[dim]Z-Offset {z_offset:+.3f} mm aktiv (fuer die Justage ohne Belang).[/]")

    if not status["active"]:
        console.print("[dim]Kein Bed Mesh geladen.[/]")
        return

    console.print(
        f"[dim]Bed Mesh {status['profile']!r} geladen (Korrektur bis "
        f"{float(status['span']):.3f} mm) - ohne Einfluss auf die Messwerte, "
        f"wird beim ersten Messpunkt geprueft.[/]"
    )


def _prepare(cfg: Config, mr: Moonraker, args: argparse.Namespace) -> None:
    # Reihenfolge wie in der Levelroutine des Druckers: erst Mesh weg, dann G28.
    _handle_mesh(cfg, mr, args)
    if not args.no_heat:
        procedure.heat(cfg, mr, notify=notify)
    procedure.home(mr, force=args.rehome, notify=notify)
    procedure.wipe(cfg, mr, notify=notify)


def _mesh_reminder() -> None:
    console.print(
        Panel(
            "Die Bettlage hat sich geaendert - das vorhandene Bed Mesh passt nicht mehr.\n"
            "Zum Abschluss am Drucker ein neues Mesh erstellen:\n"
            "  [bold]BED_MESH_CALIBRATE[/]  (danach [bold]SAVE_CONFIG[/])",
            title="Noch zu tun",
            border_style="yellow",
        )
    )


def cmd_measure(cfg: Config, args: argparse.Namespace) -> int:
    with connect(cfg) as mr, keepalive_for(mr):
        _prepare(cfg, mr, args)
        measurements = procedure.measure_all(cfg, mr, notify=notify)
        procedure.park(cfg, mr, notify=notify)
        render_report(cfg, build_report(measurements, cfg.screws))
        if cfg.temps.cooldown_after:
            procedure.cooldown(mr, notify=notify)
    _mesh_reminder()
    return 0


def cmd_level(cfg: Config, args: argparse.Namespace) -> int:
    require_tty("level")
    with connect(cfg) as mr, keepalive_for(mr):
        _prepare(cfg, mr, args)
        round_no = 1
        while True:
            console.rule(f"Durchgang {round_no}")
            measurements = procedure.measure_all(cfg, mr, notify=notify)
            report = build_report(measurements, cfg.screws)
            render_report(cfg, report)

            if report.done:
                break
            if args.max_rounds and round_no >= args.max_rounds:
                console.print(f"[yellow]Abbruch nach {round_no} Durchgaengen.[/]")
                break

            procedure.park(cfg, mr, notify=notify)
            console.print()
            answer = ask(
                "Schrauben wie angegeben drehen, dann [bold]Enter[/] fuer die naechste "
                "Messung ([bold]q[/] = beenden): "
            )
            if answer.strip().lower().startswith("q"):
                break
            round_no += 1

        procedure.park(cfg, mr, notify=notify)
        if cfg.temps.cooldown_after:
            procedure.cooldown(mr, notify=notify)
    _mesh_reminder()
    return 0


def cmd_calibrate_direction(cfg: Config, args: argparse.Namespace) -> int:
    """Ermittelt empirisch, ob Rechtsdrehen das Bett senkt oder hebt."""
    require_tty("calibrate-direction")
    screw = next((s for s in cfg.screws.points if s.name == args.screw), None)
    if screw is None:
        names = ", ".join(s.name for s in cfg.screws.points)
        console.print(f"[red]Schraube {args.screw!r} unbekannt. Verfuegbar: {names}[/]")
        return 1

    with connect(cfg) as mr, keepalive_for(mr):
        _prepare(cfg, mr, args)
        console.print(f"Messe {screw.name} vor der Testdrehung ...")
        before = procedure.probe_point(cfg, mr, screw, notify=notify)

        procedure.park(cfg, mr, notify=notify)
        console.print()
        console.print(
            Panel(
                f"Schraube [bold]{screw.name}[/] jetzt genau eine [bold]Viertelumdrehung "
                f"CW[/] (clockwise, im Uhrzeigersinn = anziehen) drehen - also 00:15.\n"
                f"Das entspricht {cfg.screws.pitch / 4:.3f} mm Gewindeweg.",
                title="Bitte von Hand",
                border_style="yellow",
            )
        )
        ask("Erledigt? Enter zum Nachmessen: ")

        after = procedure.probe_point(cfg, mr, screw, notify=notify)

    delta = after.z - before.z
    console.print()
    console.print(f"z vorher: {before.z:+.4f} mm   z nachher: {after.z:+.4f} mm   "
                  f"Aenderung: {delta:+.4f} mm")

    expected = cfg.screws.pitch / 4
    if abs(delta) < expected * 0.3:
        console.print(
            "[red]Die Aenderung ist deutlich kleiner als erwartet "
            f"({expected:.3f} mm). Wurde wirklich gedreht? Sitzt die Feder/Klemmung fest?[/]"
        )
        return 1

    cw_lowers = delta < 0
    console.print(
        f"[green]CW (anziehen) [bold]{'senkt' if cw_lowers else 'hebt'}[/] das Bett "
        f"an dieser Ecke.[/]"
    )
    console.print(
        f"In [bold]{cfg.path.name}[/] eintragen:  "
        f"[bold]cw_lowers_bed = {str(cw_lowers).lower()}[/]"
    )
    if cw_lowers == cfg.screws.cw_lowers_bed:
        console.print("Das entspricht der aktuellen Konfiguration - nichts zu aendern.")
    else:
        console.print("[yellow]Das widerspricht der aktuellen Konfiguration - bitte anpassen.[/]")
    _mesh_reminder()
    return 0


def cmd_teach(cfg: Config, args: argparse.Namespace) -> int:
    with connect(cfg) as mr, keepalive_for(mr):
        procedure.home(mr, force=args.rehome, notify=notify)
        console.print(
            Panel(
                "Die Duese ueber jede Schraube fahren und mit [bold]Enter[/] bestaetigen.\n"
                "Angetastet wird spaeter mit der Duese selbst, die Position ist also\n"
                "direkt die Messkoordinate.",
                title="Schraubenpositionen einlernen",
                border_style="cyan",
            )
        )
        try:
            points = teach_mod.teach_points(cfg, mr, start_z=args.z, notify=notify)
        except teach_mod.Aborted as exc:
            console.print(f"[yellow]{exc}[/]")
            return 1

    table = Table(title="Eingelernte Positionen", header_style="bold")
    table.add_column("Schraube")
    table.add_column("X", justify="right")
    table.add_column("Y", justify="right")
    for point in points:
        table.add_row(point.name, f"{point.x:g}", f"{point.y:g}")
    console.print(table)

    if args.dry_run:
        console.print("[dim]--dry-run: nichts geschrieben. Fuer die Konfiguration:[/]")
        console.print(teach_mod.render_points(points))
        return 0

    backup = teach_mod.write_points(cfg.path, points)
    console.print(f"[green]{cfg.path.name} aktualisiert[/] (Sicherung: {backup.name})")
    return 0


def cmd_spacers(cfg: Config, args: argparse.Namespace) -> int:
    """Werksversatz messen und passende Abstandshalter erzeugen."""
    sp = cfg.spacer
    console.print(
        Panel(
            "Gemessen wird die [bold]Ausgangslage[/] - der Versatz, den die Aufnahme"
            "punkte\nohne Ausgleich haben. Dafuer muss vorher gelten:\n\n"
            "  1. Entweder keine Spacer verbaut, oder an allen vier Punkten\n"
            "     [bold]dieselbe[/] Hoehe - sonst wird ein vorhandener Ausgleich\n"
            "     mitgemessen und doppelt beruecksichtigt.\n"
            "  2. Alle vier Schrauben gleichmaessig angezogen, keine am Anschlag.\n"
            "  3. Druckplatte plan aufgelegt, Auflageflaechen sauber.",
            title="Voraussetzungen",
            border_style="yellow",
        )
    )
    if not args.yes:
        require_tty("spacers")
        if not ask("Trifft das zu? [bold]j[/] zum Messen, alles andere bricht ab: ").strip(
        ).lower().startswith("j"):
            console.print("[yellow]Abgebrochen.[/]")
            return 1

    with connect(cfg) as mr, keepalive_for(mr):
        _prepare(cfg, mr, args)
        measurements = procedure.measure_all(cfg, mr, notify=notify)
        procedure.park(cfg, mr, notify=notify)

    report = build_report(measurements, cfg.screws)
    render_report(cfg, report)
    if not report.trustworthy:
        console.print(
            "[red]Die Messung traegt nicht - daraus jetzt Spacer zu fertigen, wuerde "
            "den Fehler in Hardware giessen. Erst die Lagerung in Ordnung bringen.[/]"
        )
        return 1

    try:
        spacer_liste = spacers_mod.compute(measurements, sp)
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        return 1

    table = Table(title="Abstandshalter", header_style="bold")
    table.add_column("Schraube")
    table.add_column("gemessen", justify="right")
    table.add_column("Vorsprung", justify="right")
    table.add_column("Hoehe", justify="right")
    table.add_column("Datei")
    for s_, m in zip(spacer_liste, measurements):
        hoch = s_.height >= max(x.height for x in spacer_liste) - 1e-9
        table.add_row(
            s_.name,
            f"{m.z:+.3f}",
            f"{s_.offset:+.3f}",
            f"[bold]{s_.height:.2f} mm[/]" + ("  (hoechster)" if hoch else ""),
            s_.filename,
            style="cyan" if hoch else None,
        )
    console.print(table)

    out = Path(args.out)
    if args.dry_run:
        console.print(f"[dim]--dry-run: keine Dateien geschrieben (Ziel waere {out}/).[/]")
    else:
        pfade = spacers_mod.write_all(spacer_liste, out, sp.segments)
        aufmass = out / "aufmass.json"
        aufmass.write_text(
            json.dumps(
                {
                    "gemessen": datetime.now().isoformat(timespec="seconds"),
                    "geometrie": {
                        "aussendurchmesser": sp.outer_diameter,
                        "innendurchmesser": sp.inner_diameter,
                        "max_height": sp.max_height,
                        "compression": sp.compression,
                    },
                    "punkte": [
                        {
                            "name": s_.name,
                            "x": m.screw.x,
                            "y": m.screw.y,
                            "z_gemessen": round(m.z, 4),
                            "einzelwerte": [round(v, 4) for v in m.samples],
                            "vorsprung": round(s_.offset, 4),
                            "hoehe": s_.height,
                        }
                        for s_, m in zip(spacer_liste, measurements)
                    ],
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        console.print(f"[green]{len(pfade)} STL-Dateien in {out}/[/] geschrieben")
        console.print(f"[dim]Aufmass mit allen Einzelwerten: {aufmass}[/]")

    dicke = spacer_liste[0].wall_thickness
    console.print(
        Panel(
            f"Material: [bold]{sp.material}[/]   Wandlinien: [bold]{sp.walls}[/]   "
            f"Infill: [bold]{sp.infill}[/]\n"
            f"Ringwand {dicke:.2f} mm breit - bei einer 0,4-mm-Duese bleiben nach je "
            f"einer Aussen- und Innenlinie rund {max(0.0, dicke - 0.8):.1f} mm fuer das "
            f"Gyroid.\nGenau das macht den Spacer zur Feder: er haelt die Vorspannung, "
            f"statt sie zu blockieren.\n\n"
            "[bold]Alle vier zusammen in einem Auftrag drucken[/] - gleiche Duesen"
            "temperatur,\ngleiche Schichtzeit, gleiches Setzverhalten. Getrennt gedruckt "
            "unterscheiden\nsich die Federraten, und der Ausgleich stimmt nicht mehr.\n\n"
            "Keine Bruecken, kein Support, 100 % Bodenschicht. Bei TPU langsam drucken "
            "(15-25 mm/s)\nund Retraction niedrig halten.",
            title="Druckparameter",
            border_style="dim",
        )
    )
    return 0


def cmd_stability(cfg: Config, args: argparse.Namespace) -> int:
    """Wiederholgenauigkeit eines einzelnen Punktes pruefen.

    Trennt die zwei Fehlerbilder, die eine Justage unmoeglich machen:
    zufaellige Streuung (verschmutzte Duese, Vibration) laesst sich mitteln,
    gerichtete Drift (nachgebende Lagerung) nicht.
    """
    screw = next((s for s in cfg.screws.points if s.name == args.screw), None)
    if screw is None:
        names = ", ".join(s.name for s in cfg.screws.points)
        console.print(f"[red]Schraube {args.screw!r} unbekannt. Verfuegbar: {names}[/]")
        return 1

    from dataclasses import replace as _replace

    probe_cfg = _replace(cfg.probe, samples_per_point=args.samples)
    messung_cfg = _replace(cfg, probe=probe_cfg)

    with connect(cfg) as mr, keepalive_for(mr):
        _prepare(cfg, mr, args)
        console.print(f"Messe {screw.name} {args.samples}x hintereinander ...")
        m = procedure.probe_point(messung_cfg, mr, screw, notify=notify)
        procedure.park(cfg, mr, notify=notify)

    table = Table(title=f"Wiederholgenauigkeit: {screw.name}", header_style="bold")
    table.add_column("#", justify="right")
    table.add_column("z [mm]", justify="right")
    table.add_column("zur vorigen", justify="right")
    vorher = None
    for i, wert in enumerate(m.samples, start=1):
        delta = "" if vorher is None else f"{wert - vorher:+.4f}"
        table.add_row(str(i), f"{wert:+.4f}", delta)
        vorher = wert
    console.print(table)

    def in_minuten(mm: float) -> float:
        return abs(mm) / cfg.screws.pitch * 60

    ziel = cfg.screws.tolerance_minutes
    streu_min, drift_min, gap_min = (in_minuten(m.spread), in_minuten(m.drift), in_minuten(m.gap))
    zeilen = [
        f"Streuung: [bold]{m.spread:.4f} mm[/] = {streu_min:.1f} Minuten",
        f"Ziel der Justage: 00:{ziel:02.0f} ({cfg.screws.tolerance_mm:.4f} mm)",
    ]

    # Bewertet wird im Verhaeltnis zum Ziel: eine Drift, die einen Bruchteil
    # der Toleranz ausmacht, steht der Justage nicht im Weg.
    if m.gap:
        zeilen.append(
            f"[red]Zwei Lagen, {m.gap:.4f} mm ({gap_min:.1f} Minuten) auseinander.[/]\n"
            "Der Median faellt in die Luecke und beschreibt keine reale Lage - "
            "das laesst sich nicht durch mehr Messungen beheben."
        )
    elif m.drift and drift_min > ziel:
        zeilen.append(
            f"[red]Gerichtete Drift: {m.drift:+.4f} mm ({drift_min:.1f} Minuten) - "
            f"mehr als die Toleranz von 00:{ziel:02.0f}.[/] Das mittelt sich nicht weg."
        )
    elif m.drift and drift_min > ziel / 2:
        zeilen.append(
            f"[yellow]Gerichtete Drift: {m.drift:+.4f} mm ({drift_min:.1f} Minuten) - "
            f"rund die Haelfte der Toleranz. Justage moeglich, aber knapp.[/]"
        )
    elif m.drift:
        zeilen.append(
            f"[green]Leichte Drift von {m.drift:+.4f} mm ({drift_min:.1f} Minuten) - "
            f"gegenueber dem Ziel von 00:{ziel:02.0f} unerheblich.[/]"
        )
    elif streu_min > ziel:
        zeilen.append(
            f"[yellow]Die Streuung liegt ueber der Toleranz - eine Justage auf "
            f"00:{ziel:02.0f} waere nicht belastbar.[/]"
        )
    else:
        zeilen.append(f"[green]Stabil genug fuer 00:{ziel:02.0f}.[/]")
    console.print(Panel("\n".join(zeilen), title="Bewertung", border_style="dim"))
    return 0


def cmd_cooldown(cfg: Config, args: argparse.Namespace) -> int:
    with connect(cfg) as mr:
        procedure.cooldown(mr, notify=notify)
    return 0


# -- Einstieg --------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bedlevel",
        description="Druckbett-Schraubenjustage ueber Moonraker (Ersatz fuer SCREWS_TILT_ADJUST).",
    )
    # --config soll vor wie nach dem Unterbefehl funktionieren.
    cfg_opt = argparse.ArgumentParser(add_help=False)
    cfg_opt.add_argument("--config", help=f"Pfad zur {config_mod.DEFAULT_CONFIG_NAME}")
    parser.add_argument("--config", help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--no-heat", action="store_true", help="Aufheizen ueberspringen")
        p.add_argument("--rehome", action="store_true", help="G28 auch bei referenzierten Achsen")

    p_check = sub.add_parser("check", parents=[cfg_opt], help="Verbindung und Firmware-Faehigkeiten pruefen")
    p_check.set_defaults(func=cmd_check)

    p_measure = sub.add_parser("measure", parents=[cfg_opt], help="Einmal alle Punkte messen und auswerten")
    add_common(p_measure)
    p_measure.set_defaults(func=cmd_measure)

    p_level = sub.add_parser("level", parents=[cfg_opt], help="Messen, nachstellen, wiederholen bis im Ziel")
    add_common(p_level)
    p_level.add_argument("--max-rounds", type=int, default=0, help="0 = unbegrenzt")
    p_level.set_defaults(func=cmd_level)

    p_dir = sub.add_parser(
        "calibrate-direction",
        parents=[cfg_opt],
        help="Drehrichtung durch eine Testdrehung bestimmen",
    )
    add_common(p_dir)
    p_dir.add_argument("screw", help="Name der Schraube aus der Konfiguration")
    p_dir.set_defaults(func=cmd_calibrate_direction)

    p_teach = sub.add_parser(
        "teach", parents=[cfg_opt], help="Schraubenpositionen mit den Pfeiltasten einlernen"
    )
    p_teach.add_argument("--rehome", action="store_true", help="G28 auch bei referenzierten Achsen")
    p_teach.add_argument("--z", type=float, default=5.0, help="Starthoehe beim Einlernen (mm)")
    p_teach.add_argument("--dry-run", action="store_true", help="nur anzeigen, nichts schreiben")
    p_teach.set_defaults(func=cmd_teach)

    p_spacer = sub.add_parser(
        "spacers", parents=[cfg_opt],
        help="Werksversatz messen und passende Abstandshalter als STL erzeugen",
    )
    add_common(p_spacer)
    p_spacer.add_argument("--out", default="spacers", help="Zielverzeichnis (Vorgabe: spacers/)")
    p_spacer.add_argument("--dry-run", action="store_true", help="nur rechnen, nichts schreiben")
    p_spacer.add_argument("--yes", action="store_true", help="Rueckfrage ueberspringen")
    p_spacer.set_defaults(func=cmd_spacers)

    p_stab = sub.add_parser(
        "stability", parents=[cfg_opt],
        help="Wiederholgenauigkeit eines Punktes pruefen (Streuung vs. Drift)",
    )
    add_common(p_stab)
    p_stab.add_argument("screw", help="Name der Schraube aus der Konfiguration")
    p_stab.add_argument("--samples", type=int, default=10, help="Anzahl Antastungen (Vorgabe 10)")
    p_stab.set_defaults(func=cmd_stability)

    p_cool = sub.add_parser("cooldown", parents=[cfg_opt], help="Heizungen ausschalten")
    p_cool.set_defaults(func=cmd_cooldown)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cfg = config_mod.load(args.config)
    except config_mod.ConfigError as exc:
        console.print(f"[red]{exc}[/]")
        return 2

    try:
        return int(args.func(cfg, args))
    except InteractiveNeeded as exc:
        console.print(f"[yellow]{exc}[/]")
        return 2
    except MoonrakerError as exc:
        console.print(f"[red]Drucker: {exc}[/]")
        return 1
    except KeyboardInterrupt:
        console.print("\n[yellow]Abgebrochen. Heizungen laufen weiter - "
                      "'bedlevel cooldown' schaltet sie aus.[/]")
        return 130


if __name__ == "__main__":
    sys.exit(main())
