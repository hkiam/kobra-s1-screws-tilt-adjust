"""Abstandshalter berechnen und als STL ausgeben.

Der Drucker hat ab Werk keine Spacer, das Bett liegt also direkt auf dem
Traeger. Der Werksversatz der vier Aufnahmepunkte muss dann komplett von den
Schrauben ausgeglichen werden - eine Ecke arbeitet dauerhaft am Anschlag,
waehrend eine andere kaum Vorspannung hat.

Gedruckte Spacer nehmen diesen Versatz vorweg: Die tiefste Ecke bekommt den
hoechsten Spacer, die uebrigen entsprechend flachere. Danach stehen alle vier
Schrauben im gleichen Bereich und die Feinjustage hat nach beiden Seiten Luft.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from pathlib import Path

from .config import SpacerCfg
from .screws import Measurement

Vec = tuple[float, float, float]
Triangle = tuple[Vec, Vec, Vec]


@dataclass(frozen=True)
class Spacer:
    name: str
    height: float
    outer_d: float
    inner_d: float
    #: Wie viel tiefer als die hoechste Ecke dieser Punkt gemessen wurde.
    offset: float

    @property
    def filename(self) -> str:
        sicher = self.name.replace(" ", "_").replace("/", "-")
        return f"spacer_{sicher}_{self.height:.2f}mm.stl"

    @property
    def wall_thickness(self) -> float:
        return (self.outer_d - self.inner_d) / 2


def compute(measurements: list[Measurement], cfg: SpacerCfg) -> list[Spacer]:
    """Spacerhoehen aus der Messung der Ausgangslage.

    Ein tief liegender Aufnahmepunkt braucht mehr Material, damit das Bett
    dort auf dieselbe Hoehe kommt. Die tiefste Ecke bekommt deshalb die
    volle Bauhoehe, jede andere wird um ihren Hoehenvorsprung gekuerzt.
    """
    if not measurements:
        raise ValueError("Keine Messwerte fuer die Spacerberechnung.")

    tiefste = min(m.z for m in measurements)
    # TPU mit wenig Infill federt: unter Vorspannung wird ein hoher Spacer
    # staerker zusammengedrueckt als ein flacher, wodurch die Hoehendifferenz
    # schrumpft. Ueber compression laesst sich das vorhalten.
    faktor = 1.0 / (1.0 - cfg.compression) if cfg.compression else 1.0

    spacers = []
    for m in measurements:
        vorsprung = m.z - tiefste
        hoehe = cfg.max_height - vorsprung * faktor
        if hoehe <= 0:
            raise ValueError(
                f"Fuer {m.screw.name!r} ergibt sich eine Hoehe von {hoehe:.2f} mm. "
                f"max_height ({cfg.max_height} mm) ist kleiner als der Versatz "
                f"von {vorsprung:.3f} mm."
            )
        spacers.append(
            Spacer(
                name=m.screw.name,
                height=round(hoehe, 2),
                outer_d=cfg.outer_diameter,
                inner_d=cfg.inner_diameter,
                offset=vorsprung,
            )
        )
    return spacers


def hollow_cylinder(outer_d: float, inner_d: float, height: float, segments: int) -> list[Triangle]:
    """Dreiecksnetz eines Rohrs, Normalen nach aussen (Rechte-Hand-Regel)."""
    ro, ri = outer_d / 2, inner_d / 2
    # Punkte einmal vorab berechnen und zyklisch indizieren: sonst schliesst
    # die Naht nicht, weil sin(2*pi) nicht exakt 0 ergibt und der letzte
    # Punkt damit knapp neben dem ersten liegt.
    aussen = []
    innen = []
    for i in range(segments):
        a = 2 * math.pi * i / segments
        c, sn = math.cos(a), math.sin(a)
        aussen.append((ro * c, ro * sn))
        innen.append((ri * c, ri * sn))

    tris: list[Triangle] = []
    for i in range(segments):
        j = (i + 1) % segments
        ao0, ao1 = aussen[i], aussen[j]
        ai0, ai1 = innen[i], innen[j]

        # Aussenwand
        tris.append(((*ao0, 0.0), (*ao1, 0.0), (*ao1, height)))
        tris.append(((*ao0, 0.0), (*ao1, height), (*ao0, height)))
        # Innenwand - umgekehrte Umlaufrichtung, damit die Normale ins Loch zeigt
        tris.append(((*ai0, 0.0), (*ai1, height), (*ai1, 0.0)))
        tris.append(((*ai0, 0.0), (*ai0, height), (*ai1, height)))
        # Deckflaeche - Umlauf so, dass die Normale nach +z zeigt
        tris.append(((*ao0, height), (*ai1, height), (*ai0, height)))
        tris.append(((*ao0, height), (*ao1, height), (*ai1, height)))
        # Bodenflaeche - Normale nach -z
        tris.append(((*ao0, 0.0), (*ai0, 0.0), (*ai1, 0.0)))
        tris.append(((*ao0, 0.0), (*ai1, 0.0), (*ao1, 0.0)))
    return tris


def _normal(t: Triangle) -> Vec:
    (ax, ay, az), (bx, by, bz), (cx, cy, cz) = t
    ux, uy, uz = bx - ax, by - ay, bz - az
    vx, vy, vz = cx - ax, cy - ay, cz - az
    nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
    laenge = math.sqrt(nx * nx + ny * ny + nz * nz)
    return (0.0, 0.0, 0.0) if laenge == 0 else (nx / laenge, ny / laenge, nz / laenge)


def mesh_volume(tris: list[Triangle]) -> float:
    """Volumen ueber das Divergenztheorem - negativ bei falscher Orientierung.

    Damit laesst sich das Netz gegen die analytische Formel pruefen, statt
    erst im Slicer zu merken, dass Normalen nach innen zeigen.
    """
    total = 0.0
    for (ax, ay, az), (bx, by, bz), (cx, cy, cz) in tris:
        total += (
            ax * (by * cz - bz * cy)
            - ay * (bx * cz - bz * cx)
            + az * (bx * cy - by * cx)
        )
    return total / 6.0


def write_stl(path: Path, tris: list[Triangle], name: str = "spacer") -> Path:
    """Binaeres STL schreiben - das versteht jeder Slicer."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        fh.write(name.encode("ascii", "replace")[:80].ljust(80, b"\0"))
        fh.write(struct.pack("<I", len(tris)))
        for t in tris:
            fh.write(struct.pack("<3f", *_normal(t)))
            for v in t:
                fh.write(struct.pack("<3f", *v))
            fh.write(struct.pack("<H", 0))
    return path


def write_all(spacers: list[Spacer], out_dir: Path, segments: int) -> list[Path]:
    pfade = []
    for s in spacers:
        tris = hollow_cylinder(s.outer_d, s.inner_d, s.height, segments)
        pfade.append(write_stl(out_dir / s.filename, tris, f"{s.name} {s.height:.2f}mm"))
    return pfade
