"""Auswertung der Messpunkte: Referenzwahl, Drehempfehlung, Ebenenanalyse."""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from .config import Screw, ScrewCfg

# Rechtsgewinde: im Uhrzeigersinn ist immer "anziehen" - unabhaengig davon,
# von welcher Seite man an die Schraube herankommt. Das ist am Geraet die
# verlaesslichere Ansage als eine Drehrichtung mit Blickrichtung im Kleingedruckten.
AUTO = "auto"
NUR_ANZIEHEN = "nur-anziehen"

# Schreibweise wie SCREWS_TILT_ADJUST: CW = clockwise, CCW = counter-clockwise.
# Bei Rechtsgewinde ist CW immer "anziehen"; die Legende der Ausgabe nennt beides.
CW = "CW"
CCW = "CCW"


@dataclass(frozen=True)
class Measurement:
    screw: Screw
    samples: list[float]

    @property
    def z(self) -> float:
        """Median statt Mittelwert: unempfindlich gegen einzelne Ausreisser."""
        return statistics.median(self.samples)

    @property
    def spread(self) -> float:
        return max(self.samples) - min(self.samples) if len(self.samples) > 1 else 0.0

    @property
    def gap(self) -> float:
        """Abstand zwischen zwei Wertegruppen, sonst 0.

        Rastet die Lagerung zwischen zwei Lagen ein, zerfallen die Messwerte
        in zwei Haufen. Der Median landet dann in der Luecke dazwischen - auf
        einem Wert, den das Bett nie einnimmt. Mehr Messungen helfen hier
        nicht, sie machen den Median nur scheinbar sicherer.
        """
        if len(self.samples) < 4:
            return 0.0
        werte = sorted(self.samples)
        luecken = [b - a for a, b in zip(werte, werte[1:])]
        groesste = max(luecken)
        # Dominiert eine einzelne Luecke die Spannweite, sind es zwei Gruppen
        # und keine kontinuierliche Streuung.
        return groesste if self.spread and groesste > self.spread * 0.5 else 0.0

    @property
    def drift(self) -> float:
        """Gerichtete Aenderung ueber die Messreihe, sonst 0.

        Streuen die Werte zufaellig, mittelt der Median sie weg. Laufen sie
        aber monoton in eine Richtung, ist etwas systematisch falsch - eine
        verschmutzte Duese, die bei jedem Antasten flacher gedrueckt wird,
        oder eine Lagerung, die unter dem Antastdruck nachgibt. Dann hilft
        auch kein weiteres Mitteln.
        """
        if len(self.samples) < 3:
            return 0.0
        if len(self.samples) < 5:
            # Zu wenige Werte fuer eine Aussage ueber verrauschte Trends -
            # deshalb nur der eindeutige Fall: streng monoton.
            steps = [b - a for a, b in zip(self.samples, self.samples[1:])]
            if all(d > 0 for d in steps) or all(d < 0 for d in steps):
                return self.samples[-1] - self.samples[0]
            return 0.0

        # Laengere Reihe: Haelften vergleichen. Erkennt auch einen Trend, der
        # von Rauschen ueberlagert ist - und der Median macht ihn robust
        # gegen einzelne Ausreisser.
        haelfte = len(self.samples) // 2
        trend = statistics.median(self.samples[-haelfte:]) - statistics.median(
            self.samples[:haelfte]
        )
        # Der Trend muss einen spuerbaren Anteil der Streuung ausmachen, sonst
        # ist es Rauschen. Der Medianvergleich daempft echte Trends bereits,
        # deshalb reicht hier ein Drittel als Schwelle.
        return trend if abs(trend) > self.spread * 0.3 else 0.0


def unreliable_reason(m: Measurement, tolerance_mm: float) -> str | None:
    """Warum dieser Messwert keine Justage traegt - oder None."""
    if m.gap > tolerance_mm:
        return f"zwei Lagen, {m.gap:.3f} mm auseinander"
    # Erst wenn die Drift die Toleranz selbst uebersteigt, ist eine Korrektur
    # daraus nicht mehr sinnvoll - darunter faellt sie gegen das Ziel nicht ins
    # Gewicht.
    if abs(m.drift) > tolerance_mm:
        return f"driftet um {m.drift:+.3f} mm"
    if m.spread > tolerance_mm * 2:
        return f"streut um {m.spread:.3f} mm"
    return None


@dataclass(frozen=True)
class Adjustment:
    screw: Screw
    z: float
    spread: float
    delta: float
    turns: float
    degrees: float
    clock_minutes: float
    direction: str | None
    is_reference: bool
    ok: bool
    unreliable: str | None = None

    @property
    def clock(self) -> str:
        """Drehung als Umdrehungen:Minuten, wie bei Klipper.

        60 Minuten sind eine volle Umdrehung, 15 Minuten also eine
        Viertelumdrehung. Gerundet statt abgeschnitten - eine Minute
        entspricht bei M4 immerhin 0,012 mm.
        """
        turns, minutes = divmod(round(self.turns * 60), 60)
        return f"{turns:02d}:{minutes:02d}"

    @property
    def action(self) -> str:
        if self.is_reference:
            return "(base)"
        if self.ok:
            # Auch innerhalb der Toleranz die Zahl zeigen: liegen mehrere
            # Schrauben knapp darunter, bleibt sonst eine systematische
            # Verkippung stehen, ohne dass die Tabelle es verraet. Die
            # Klammern sagen: nicht noetig, aber wirksam.
            return "passt" if self.clock == "00:00" else f"({self.direction} {self.clock})"
        return f"{self.direction} {self.clock}"


@dataclass(frozen=True)
class Plane:
    """Ausgleichsebene durch alle Messpunkte: z = a*x + b*y + c."""

    a: float
    b: float
    c: float
    residuals: dict[str, float]

    @property
    def peak_to_peak(self) -> float:
        """Groesster minus kleinster Restfehler - der reale Restwelligkeitsbereich."""
        if not self.residuals:
            return 0.0
        values = self.residuals.values()
        return max(values) - min(values)

    def tilt_mm_per_m(self) -> tuple[float, float]:
        return self.a * 1000.0, self.b * 1000.0


# Einstufung der groessten Restabweichung, in Minuten der Uhrzeit-Notation.
# Unter 00:02 liegt man im Bereich des Spiels der Verschraubung selbst.
STUFEN = ((2, "an der Grenze des mechanischen Spiels"), (5, "exzellent"), (10, "gut"))


def einstufung(minuten: float) -> str:
    for grenze, text in STUFEN:
        if minuten < grenze:
            return text
    return "noch nachstellen"


@dataclass(frozen=True)
class Report:
    adjustments: list[Adjustment]
    reference: str
    span: float
    plane: Plane | None
    tolerance_minutes: float
    pitch: float

    @property
    def done(self) -> bool:
        return all(a.ok or a.is_reference for a in self.adjustments)

    @property
    def unreliable(self) -> list[Adjustment]:
        return [a for a in self.adjustments if a.unreliable]

    @property
    def trustworthy(self) -> bool:
        return not self.unreliable

    @property
    def worst_minutes(self) -> float:
        """Groesste noetige Korrektur, in Minuten."""
        return max((a.turns * 60 for a in self.adjustments if not a.is_reference), default=0.0)

    @property
    def span_minutes(self) -> float:
        return self.span / self.pitch * 60

    @property
    def bewertung(self) -> str:
        return einstufung(self.worst_minutes)


def pick_reference(
    measurements: list[Measurement], cfg: ScrewCfg, tolerance_mm: float = 0.0
) -> Measurement:
    """Die Schraube bestimmen, an der nicht gedreht wird.

    - "auto": minimiert den Gesamtdrehaufwand (der Median-naechste Punkt).
      Nicht die hoechste oder tiefste Ecke, denn an denen zu referenzieren
      zwingt zu drei grossen Korrekturen statt zwei kleinen.
    - "nur-anziehen": waehlt die Ecke so, dass alle uebrigen Schrauben
      angezogen und keine geloest werden muss. Anziehen haelt die Spannung
      der Lagerung besser als Ausdrehen. Welche Ecke das ist, haengt an der
      Mechanik: senkt Anziehen das Bett, ist es die tiefste, sonst die
      hoechste. Die Wahl wird bei jedem Durchgang neu getroffen, bleibt also
      auch dann gueltig, wenn eine Ecke zwischendurch ueberdreht wurde.
    - ein Schraubenname: genau diese Schraube.
    """
    # Ein Punkt, dessen Messwert nicht tragfaehig ist, taugt erst recht nicht
    # als Bezug fuer alle anderen.
    brauchbar = [m for m in measurements if unreliable_reason(m, tolerance_mm) is None]
    if tolerance_mm and brauchbar and cfg.reference in (AUTO, NUR_ANZIEHEN):
        measurements = brauchbar

    if cfg.reference == NUR_ANZIEHEN:
        # Anziehen senkt -> alle anderen muessen hoeher liegen -> tiefste Ecke.
        return min(measurements, key=lambda m: m.z) if cfg.cw_lowers_bed else max(
            measurements, key=lambda m: m.z
        )
    if cfg.reference != AUTO:
        for m in measurements:
            if m.screw.name == cfg.reference:
                return m
        raise ValueError(f"Referenzschraube {cfg.reference!r} nicht in den Messwerten.")
    return min(
        measurements,
        key=lambda m: sum(abs(other.z - m.z) for other in measurements),
    )


def fit_plane(measurements: list[Measurement]) -> Plane | None:
    """Kleinste-Quadrate-Ebene ueber die Messpunkte.

    Das Residuum zeigt den Anteil der Abweichung, der keine reine Verkippung
    ist - also Verzug/Twist des Betts, den man mit den Schrauben grundsaetzlich
    nicht wegdrehen kann.
    """
    n = len(measurements)
    if n < 4:
        return None  # mit 3 Punkten geht die Ebene exakt durch alle, kein Erkenntnisgewinn

    xs = [m.screw.x for m in measurements]
    ys = [m.screw.y for m in measurements]
    zs = [m.z for m in measurements]

    # Normalgleichungen fuer z = a*x + b*y + c
    sxx = sum(x * x for x in xs)
    sxy = sum(x * y for x, y in zip(xs, ys))
    sx = sum(xs)
    syy = sum(y * y for y in ys)
    sy = sum(ys)
    sxz = sum(x * z for x, z in zip(xs, zs))
    syz = sum(y * z for y, z in zip(ys, zs))
    sz = sum(zs)

    mat = [
        [sxx, sxy, sx, sxz],
        [sxy, syy, sy, syz],
        [sx, sy, float(n), sz],
    ]

    # Gauss-Elimination mit Spaltenpivotisierung
    for col in range(3):
        pivot = max(range(col, 3), key=lambda r: abs(mat[r][col]))
        if abs(mat[pivot][col]) < 1e-12:
            return None
        mat[col], mat[pivot] = mat[pivot], mat[col]
        for row in range(3):
            if row == col:
                continue
            factor = mat[row][col] / mat[col][col]
            for k in range(col, 4):
                mat[row][k] -= factor * mat[col][k]

    a, b, c = (mat[i][3] / mat[i][i] for i in range(3))
    residuals = {m.screw.name: m.z - (a * m.screw.x + b * m.screw.y + c) for m in measurements}
    return Plane(a=a, b=b, c=c, residuals=residuals)


def build_report(measurements: list[Measurement], cfg: ScrewCfg) -> Report:
    pitch = cfg.pitch
    tolerance_mm = cfg.tolerance_minutes / 60 * pitch
    reference = pick_reference(measurements, cfg, tolerance_mm)

    adjustments: list[Adjustment] = []
    for m in measurements:
        delta = m.z - reference.z
        # delta > 0: die Ecke steht hoeher als die Referenz und muss gesenkt werden.
        lower = delta > 0
        if cfg.cw_lowers_bed:
            direction = CW if lower else CCW
        else:
            direction = CCW if lower else CW

        turns = abs(delta) / pitch
        degrees = turns * 360.0
        is_ref = m.screw.name == reference.screw.name
        # In Minuten bewerten, nicht in Millimetern: dann deckt sich die
        # Beurteilung mit der Zahl, die in der Spalte "adjust" steht.
        ok = round(turns * 60) <= cfg.tolerance_minutes

        adjustments.append(
            Adjustment(
                screw=m.screw,
                z=m.z,
                spread=m.spread,
                delta=delta,
                turns=turns,
                degrees=degrees,
                clock_minutes=(turns % 1.0) * 60.0,
                direction=None if is_ref else direction,
                is_reference=is_ref,
                ok=ok,
                unreliable=unreliable_reason(m, tolerance_mm),
            )
        )

    zs = [m.z for m in measurements]
    return Report(
        adjustments=adjustments,
        reference=reference.screw.name,
        span=max(zs) - min(zs),
        plane=fit_plane(measurements),
        tolerance_minutes=cfg.tolerance_minutes,
        pitch=pitch,
    )
