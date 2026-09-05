"""Interaktives Einlernen der Schraubenpositionen mit den Pfeiltasten.

Der Kobra S1 tastet mit der Duese an (Probe-Offset 0/0), die eingelernte
Duesenposition ist also unmittelbar die Messkoordinate.
"""

from __future__ import annotations

import re
import shutil
import sys
import termios
import tty
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .config import Config, Screw
from .keys import (
    KEY_CTRL_C,
    KEY_DOWN,
    KEY_LEFT,
    KEY_PGDN,
    KEY_PGUP,
    KEY_RIGHT,
    KEY_UP,
    KeyReader,
)
from .moonraker import Moonraker, MoonrakerError

STEP_SIZES = [0.1, 0.5, 1.0, 5.0, 10.0]
DEFAULT_STEP_INDEX = 2
XY_FEED = 6000
Z_FEED = 600
# Kurzer Timeout fuers Tippen: eine haengende Anfrage darf die Bedienung
# nicht blockieren.
JOG_TIMEOUT = 15.0
# Hoechstens so viele bereits gepufferte Tasten zu einer Fahrt zusammenfassen.
MAX_COALESCE = 32


class Aborted(RuntimeError):
    pass


@dataclass
class Limits:
    x: tuple[float, float]
    y: tuple[float, float]
    z: tuple[float, float]

    @classmethod
    def from_printer(cls, mr: Moonraker) -> "Limits":
        limits = mr.axis_limits()
        return cls(
            x=limits.get("x", (-6.0, 265.0)),
            y=limits.get("y", (0.0, 277.0)),
            # Beim Einlernen nie unter die Bettoberflaeche fahren, auch wenn
            # die Kinematik negatives Z zuliesse.
            z=(0.0, min(limits.get("z", (0.0, 253.0))[1], 50.0)),
        )

    def clamp(self, x: float, y: float, z: float) -> tuple[float, float, float]:
        return (
            min(max(x, self.x[0]), self.x[1]),
            min(max(y, self.y[0]), self.y[1]),
            min(max(z, self.z[0]), self.z[1]),
        )


def _write(text: str) -> None:
    sys.stdout.write(text)
    sys.stdout.flush()


HELP = (
    "  Pfeiltasten: X/Y     Bild-auf/ab oder +/-: Z     1-5: Schrittweite\r\n"
    "  Enter: Position uebernehmen     s: ueberspringen     q: abbrechen\r\n"
)


@dataclass
class Pose:
    x: float
    y: float
    z: float
    step_index: int = DEFAULT_STEP_INDEX

    @property
    def step(self) -> float:
        return STEP_SIZES[self.step_index]

    def xyz(self) -> tuple[float, float, float]:
        return self.x, self.y, self.z


def apply_key(key: str, pose: Pose, limits: Limits) -> str | None:
    """Eine Taste auf die Pose anwenden.

    Rueckgabe ist die ausgeloeste Aktion ("accept", "skip", "abort") oder
    None, wenn die Taste nur bewegt hat oder unbekannt war.
    """
    if key in ("\r", "\n"):
        return "accept"
    if key in ("s", "S"):
        return "skip"
    if key in ("q", "Q", KEY_CTRL_C):
        return "abort"

    step = pose.step
    x, y, z = pose.xyz()
    if key == KEY_LEFT:
        x -= step
    elif key == KEY_RIGHT:
        x += step
    elif key == KEY_UP:
        y += step
    elif key == KEY_DOWN:
        y -= step
    elif key in (KEY_PGUP, "+"):
        z += step
    elif key in (KEY_PGDN, "-"):
        z -= step
    elif key in "12345":
        pose.step_index = int(key) - 1
        return None
    else:
        return None

    pose.x, pose.y, pose.z = limits.clamp(x, y, z)
    return None


def _jog(mr: Moonraker, pose: Pose) -> str | None:
    """Fahrbefehl senden. Rueckgabe ist eine Fehlermeldung oder None."""
    try:
        mr.script(
            f"G1 X{pose.x:.3f} Y{pose.y:.3f} Z{pose.z:.3f} F{XY_FEED}",
            timeout=JOG_TIMEOUT,
        )
    except MoonrakerError as exc:
        return str(exc)
    return None


def teach_points(
    cfg: Config,
    mr: Moonraker,
    *,
    start_z: float = 5.0,
    notify: Callable[[str], None] = lambda _: None,
) -> list[Screw]:
    if not sys.stdin.isatty():
        raise Aborted(
            "teach braucht ein interaktives Terminal. "
            "Bitte direkt in einer Shell starten, nicht ueber eine Pipe."
        )

    limits = Limits.from_printer(mr)
    result: list[Screw] = []
    step_index = DEFAULT_STEP_INDEX

    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    reader = KeyReader(fd)
    try:
        # cbreak statt raw: Strg-C bleibt als KeyboardInterrupt wirksam.
        tty.setcbreak(fd)
        for screw in cfg.screws.points:
            x, y, z = limits.clamp(screw.x, screw.y, start_z)
            pose = Pose(x=x, y=y, z=z, step_index=step_index)

            _write(f"\r\n[{screw.name}]  fahre Startposition an ...\r\n")
            mr.script("G90")
            mr.script(f"G1 Z{max(z, start_z):.2f} F{Z_FEED}")
            mr.script(f"G1 X{x:.3f} Y{y:.3f} F{XY_FEED}")
            mr.script(f"G1 Z{z:.2f} F{Z_FEED}")
            mr.script("M400")
            _write(HELP)

            error: str | None = None
            while True:
                status = (
                    f"\r\x1b[2K  X {pose.x:8.3f}   Y {pose.y:8.3f}   Z {pose.z:7.3f}   "
                    f"Schritt {pose.step:g} mm "
                )
                if error:
                    status += f" [{error}]"
                _write(status)

                key = reader.read_key()
                if key is None:
                    continue

                before = pose.xyz()
                action = apply_key(key, pose, limits)

                # Was waehrend der letzten Fahrt schon getippt wurde, sofort
                # mitnehmen - sonst laeuft die Anzeige der Hand hinterher.
                taken = 1
                while action is None and taken < MAX_COALESCE and reader.pending():
                    extra = reader.read_key(0)
                    if extra is None:
                        break
                    taken += 1
                    action = apply_key(extra, pose, limits)

                error = None
                if pose.xyz() != before:
                    error = _jog(mr, pose)

                if action == "accept":
                    result.append(Screw(name=screw.name, x=round(pose.x, 3), y=round(pose.y, 3)))
                    _write(f"\r\n  uebernommen: X{pose.x:.3f} Y{pose.y:.3f}\r\n")
                    break
                if action == "skip":
                    result.append(screw)
                    _write(f"\r\n  unveraendert: X{screw.x:g} Y{screw.y:g}\r\n")
                    break
                if action == "abort":
                    raise Aborted("Einlernen abgebrochen.")

            step_index = pose.step_index  # Schrittweite ueber Punkte hinweg behalten
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)

    # Duese wieder in sichere Hoehe bringen.
    mr.script("G90")
    mr.script(f"G1 Z{max(start_z, 10.0):.2f} F{Z_FEED}")
    mr.script("M400")
    return result


POINT_BLOCK = re.compile(r"^\[\[screws\.points\]\]\s*$", re.MULTILINE)
ANY_HEADER = re.compile(r"^\[", re.MULTILINE)


def render_points(points: list[Screw]) -> str:
    blocks = []
    for p in points:
        blocks.append(f'[[screws.points]]\nname = "{p.name}"\nx = {p.x:g}\ny = {p.y:g}\n')
    return "\n".join(blocks)


def write_points(path: Path, points: list[Screw]) -> Path:
    """Ersetzt die [[screws.points]]-Bloecke und legt vorher ein Backup an.

    Der Rest der Datei samt Kommentaren bleibt unangetastet - deshalb reine
    Textersetzung statt Serialisieren des geparsten TOML.
    """
    text = path.read_text()
    first = POINT_BLOCK.search(text)
    if first is None:
        raise ValueError(f"In {path} wurde kein [[screws.points]]-Block gefunden.")

    # Ende: naechster Header, der selbst kein Punkt-Block ist, sonst Dateiende.
    end = len(text)
    for m in ANY_HEADER.finditer(text, first.end()):
        line_end = text.find("\n", m.start())
        line = text[m.start() : line_end if line_end != -1 else len(text)].strip()
        if line != "[[screws.points]]":
            end = m.start()
            break

    backup = path.with_suffix(path.suffix + ".bak")
    shutil.copy2(path, backup)
    path.write_text(text[: first.start()] + render_points(points) + text[end:])
    return backup
