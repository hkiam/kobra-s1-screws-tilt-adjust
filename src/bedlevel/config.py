"""Konfiguration laden und validieren."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG_NAME = "bedlevel.toml"

# Gewindesteigungen gaengiger metrischer Regelgewinde in mm pro Umdrehung.
THREAD_PITCH = {
    "M3": 0.5,
    "M4": 0.7,
    "M5": 0.8,
    "M6": 1.0,
    "M8": 1.25,
}


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Screw:
    name: str
    x: float
    y: float


@dataclass(frozen=True)
class PrinterCfg:
    host: str
    port: int = 7125
    api_key: str | None = None
    # Achsgrenzen aus printer.cfg des Kobra S1; dienen nur als Sicherheitsnetz,
    # die echten Werte werden beim Verbinden vom Drucker gelesen.
    x_min: float = -6.0
    x_max: float = 265.0
    y_min: float = 0.0
    y_max: float = 277.0

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"


@dataclass(frozen=True)
class TempCfg:
    bed: float = 60.0
    nozzle_probe: float = 140.0
    nozzle_wipe: float = 170.0
    cooldown_after: bool = False


@dataclass(frozen=True)
class WipeCfg:
    """Duesenreinigung vor dem Antasten.

    Der Kobra S1 tastet mit der Duese selbst (Kraftsensor, siehe [cs1237] in
    der printer.cfg). Anhaftendes Filament verfaelscht deshalb jede Messung.
    Standardmaessig aus, weil die Wischsequenz maschinenspezifisch ist -
    erst nach Pruefung am Geraet einschalten.
    """

    enabled: bool = False
    gcode: str = ""


@dataclass(frozen=True)
class ParkCfg:
    """Wohin der Druckkopf faehrt, waehrend von Hand geschraubt wird.

    Die Schrauben sitzen oben am Druckbett - nach einer Messung steht die
    Duese genau darueber und ist im Weg. Vor jeder Handarbeit wird deshalb
    das Bett abgesenkt (grosses Z) und der Kopf nach hinten aus dem
    Greifbereich gefahren.
    """

    enabled: bool = True
    x: float = 125.0
    y: float = 277.0
    z: float = 60.0


@dataclass(frozen=True)
class ProbeCfg:
    # Acht Antastungen je Punkt: genug, damit der Median Sensorrauschen
    # zuverlaessig wegmittelt und eine Trendaussage ueber die Reihe moeglich
    # wird (ab fuenf Werten vergleicht die Auswertung Haelften statt nur
    # strenge Monotonie zu pruefen).
    samples_per_point: int = 8
    # Auf mehrere Durchgaenge verteilt statt am Stueck: siehe measure_all.
    passes: int = 2
    discard_first: bool = True
    travel_speed: float = 250.0
    lift_speed: float = 15.0
    safe_z: float = 5.0
    settle_seconds: float = 0.0


@dataclass(frozen=True)
class SpacerCfg:
    """Abstandshalter, die den Werksversatz vorwegnehmen.

    Der hoechste Spacer bekommt max_height, die uebrigen werden um den
    gemessenen Hoehenvorsprung ihrer Ecke gekuerzt.
    """

    outer_diameter: float = 8.74
    inner_diameter: float = 4.3
    max_height: float = 10.5
    #: Anteil, um den TPU unter Vorspannung nachgibt (0.05 = 5 %). Damit
    #: werden die Hoehendifferenzen vorgehalten, siehe spacers.compute.
    compression: float = 0.0
    #: Segmente am Umfang; 128 ergibt bei 8,74 mm rund 0,2 mm Sehnenlaenge.
    segments: int = 128
    material: str = "TPU 95A"
    walls: int = 1
    infill: str = "10 % Gyroid"


@dataclass(frozen=True)
class ScrewCfg:
    thread: str = "M4"
    thread_pitch: float | None = None
    cw_lowers_bed: bool = True
    reference: str = "auto"
    # Toleranz in Minuten der Uhrzeit-Notation, passend zur Ausgabe.
    # Richtwerte: unter 10 gut, unter 5 exzellent, unter 2 im Bereich des
    # Spiels der Verschraubung selbst.
    tolerance_minutes: float = 5.0
    points: list[Screw] = field(default_factory=list)

    @property
    def tolerance_mm(self) -> float:
        """Die Toleranz in Millimetern - Bezugsgroesse fuer alle Warnungen.

        Was als Messproblem gilt, haengt am Ziel: eine Drift von 0,014 mm ist
        bei 00:10 ein Achtel der Toleranz und belanglos, bei 00:02 dagegen
        die halbe Toleranz und ein echtes Hindernis.
        """
        return self.tolerance_minutes / 60 * self.pitch

    @property
    def pitch(self) -> float:
        if self.thread_pitch is not None:
            return self.thread_pitch
        try:
            return THREAD_PITCH[self.thread.upper()]
        except KeyError:
            raise ConfigError(
                f"Unbekanntes Gewinde {self.thread!r}. Bekannt: "
                f"{', '.join(sorted(THREAD_PITCH))}. Alternativ thread_pitch direkt setzen."
            ) from None


@dataclass(frozen=True)
class Config:
    printer: PrinterCfg
    temps: TempCfg
    wipe: WipeCfg
    park: ParkCfg
    spacer: SpacerCfg
    probe: ProbeCfg
    screws: ScrewCfg
    path: Path

    def validate(self) -> None:
        if len(self.screws.points) < 3:
            raise ConfigError("Mindestens drei Schraubenpositionen noetig.")
        names = [s.name for s in self.screws.points]
        if len(set(names)) != len(names):
            raise ConfigError("Schraubennamen muessen eindeutig sein.")
        schluessel = ("auto", "nur-anziehen")
        if self.screws.reference not in schluessel and self.screws.reference not in names:
            raise ConfigError(
                f"reference={self.screws.reference!r} ist weder ein Schluesselwort "
                f"({', '.join(schluessel)}) noch eine Schraube ({', '.join(names)})."
            )
        p = self.printer
        for s in self.screws.points:
            if not (p.x_min <= s.x <= p.x_max and p.y_min <= s.y <= p.y_max):
                raise ConfigError(
                    f"Schraube {s.name!r} liegt mit X{s.x}/Y{s.y} ausserhalb des "
                    f"Fahrbereichs X[{p.x_min},{p.x_max}] Y[{p.y_min},{p.y_max}]."
                )
        sp = self.spacer
        if sp.inner_diameter >= sp.outer_diameter:
            raise ConfigError(
                f"Spacer: Innendurchmesser ({sp.inner_diameter}) muss kleiner sein "
                f"als der Aussendurchmesser ({sp.outer_diameter})."
            )
        if sp.max_height <= 0:
            raise ConfigError("Spacer: max_height muss groesser als 0 sein.")
        if not 0 <= sp.compression < 1:
            raise ConfigError("Spacer: compression muss zwischen 0 und 1 liegen.")
        if sp.segments < 12:
            raise ConfigError("Spacer: segments muss mindestens 12 sein.")
        if self.screws.tolerance_minutes < 0:
            raise ConfigError("tolerance_minutes darf nicht negativ sein.")
        if self.probe.samples_per_point < 1:
            raise ConfigError("samples_per_point muss >= 1 sein.")
        if self.probe.passes < 1:
            raise ConfigError("passes muss >= 1 sein.")
        if self.park.enabled and not (
            p.x_min <= self.park.x <= p.x_max and p.y_min <= self.park.y <= p.y_max
        ):
            raise ConfigError(
                f"Parkposition X{self.park.x}/Y{self.park.y} liegt ausserhalb des Fahrbereichs."
            )
        if self.wipe.enabled and not self.wipe.gcode.strip():
            raise ConfigError("[wipe] enabled=true, aber kein gcode hinterlegt.")
        self.screws.pitch  # loest ConfigError bei unbekanntem Gewinde aus


def find_config(explicit: str | None = None) -> Path:
    if explicit:
        p = Path(explicit).expanduser()
        if not p.is_file():
            raise ConfigError(f"Konfigurationsdatei nicht gefunden: {p}")
        return p
    for candidate in (Path.cwd() / DEFAULT_CONFIG_NAME, Path(__file__).resolve().parents[2] / DEFAULT_CONFIG_NAME):
        if candidate.is_file():
            return candidate
    vorlage = Path.cwd() / "bedlevel.example.toml"
    if vorlage.is_file():
        raise ConfigError(
            f"Keine {DEFAULT_CONFIG_NAME} gefunden. Vorlage kopieren und anpassen:\n"
            f"    cp bedlevel.example.toml {DEFAULT_CONFIG_NAME}"
        )
    raise ConfigError(
        f"Keine {DEFAULT_CONFIG_NAME} gefunden. Anlegen oder mit --config <pfad> angeben."
    )


def load(explicit: str | None = None) -> Config:
    path = find_config(explicit)
    with path.open("rb") as fh:
        raw = tomllib.load(fh)

    try:
        printer = PrinterCfg(**raw["printer"])
    except KeyError:
        raise ConfigError("Abschnitt [printer] fehlt in der Konfiguration.") from None
    except TypeError as exc:
        raise ConfigError(f"[printer]: {exc}") from None

    screws_raw = dict(raw.get("screws", {}))
    points_raw = screws_raw.pop("points", [])
    try:
        temps = TempCfg(**raw.get("temps", {}))
        wipe = WipeCfg(**raw.get("wipe", {}))
        park = ParkCfg(**raw.get("park", {}))
        spacer = SpacerCfg(**raw.get("spacer", {}))
        probe = ProbeCfg(**raw.get("probe", {}))
        screws = ScrewCfg(
            points=[Screw(**p) for p in points_raw],
            **screws_raw,
        )
    except TypeError as exc:
        raise ConfigError(f"Konfigurationsfehler: {exc}") from None

    cfg = Config(
        printer=printer, temps=temps, wipe=wipe, park=park, spacer=spacer,
        probe=probe, screws=screws, path=path
    )
    cfg.validate()
    return cfg
