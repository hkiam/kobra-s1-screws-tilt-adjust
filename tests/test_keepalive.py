"""Tests fuer den Keepalive.

Hintergrund: Der Drucker faellt nach kurzer Zeit ohne G-Code in den Leerlauf,
schaltet die Heizungen ab und macht die Motoren stromlos - die Referenzfahrt
ist damit weg. Statusabfragen zaehlen nicht als Aktivitaet.
"""

from __future__ import annotations

import time

from bedlevel.keepalive import Keepalive
from bedlevel.moonraker import Moonraker, MoonrakerError


class FakeMoonraker(Moonraker):
    def __init__(self, *, faellt_aus: int = 0) -> None:
        self.kommandos: list[str] = []
        self.faellt_aus = faellt_aus

    def script(self, gcode: str, *, timeout: float | None = None) -> None:
        self.kommandos.append(gcode)
        if len(self.kommandos) <= self.faellt_aus:
            raise MoonrakerError("Verbindung kurz weg")


def test_sendet_regelmaessig():
    mr = FakeMoonraker()
    with Keepalive(mr, interval=0.02):
        time.sleep(0.3)
    assert len(mr.kommandos) >= 3
    assert set(mr.kommandos) == {"M105"}


def test_stoppt_am_ende_des_blocks():
    mr = FakeMoonraker()
    with Keepalive(mr, interval=0.02):
        time.sleep(0.1)
    stand = len(mr.kommandos)
    time.sleep(0.15)
    assert len(mr.kommandos) == stand, "Nach dem Block darf nichts mehr gesendet werden"


def test_einzelner_fehler_beendet_den_keepalive_nicht():
    """Ein verpasster Herzschlag darf die Justage nicht abbrechen."""
    mr = FakeMoonraker(faellt_aus=2)
    gemeldet: list[str] = []
    ka = Keepalive(mr, interval=0.02, on_error=gemeldet.append)
    with ka:
        time.sleep(0.3)
    assert gemeldet, "Der Fehler haette gemeldet werden muessen"
    assert ka.sent >= 1, "Nach dem Fehler muss weitergesendet werden"


def test_doppeltes_starten_erzeugt_nur_einen_thread():
    mr = FakeMoonraker()
    ka = Keepalive(mr, interval=5.0)
    ka.start()
    thread = ka._thread
    ka.start()
    assert ka._thread is thread
    ka.stop()


def test_stop_ohne_start_ist_harmlos():
    Keepalive(FakeMoonraker(), interval=5.0).stop()
