"""Tests fuer das Warten auf Zieltemperatur.

Hintergrund: Reines Statuspollen ist fuer den Drucker keine Aktivitaet.
Beim ersten Lauf am Geraet wurden die Sollwerte mitten im Aufheizen von
aussen auf 0 gesetzt; das Aufheizen brach ab und das Tool wartete bis zum
Zeitlimit weiter.
"""

from __future__ import annotations

import pytest

from bedlevel.moonraker import Moonraker, MoonrakerError


class FakeMoonraker(Moonraker):
    """Moonraker-Ersatz ohne HTTP: simuliert Heizverhalten Schritt fuer Schritt."""

    def __init__(self, *, steigung: float = 5.0, nullt_nach: int | None = None) -> None:
        self.bed = 20.0
        self.nozzle = 20.0
        self.bed_target = 0.0
        self.nozzle_target = 0.0
        self.steigung = steigung
        self.nullt_nach = nullt_nach
        self.polls = 0
        self.skripte: list[str] = []

    def script(self, gcode: str, *, timeout: float | None = None) -> None:
        self.skripte.append(gcode)
        if gcode.startswith("M140 S"):
            self.bed_target = float(gcode[6:])
        elif gcode.startswith("M104 S"):
            self.nozzle_target = float(gcode[6:])

    def temperatures(self) -> dict[str, dict[str, float]]:
        self.polls += 1
        # Der externe Eingriff: Sollwerte werden genullt.
        if self.nullt_nach is not None and self.polls == self.nullt_nach:
            self.bed_target = 0.0
            self.nozzle_target = 0.0
        for name in ("bed", "nozzle"):
            ist = getattr(self, name)
            soll = getattr(self, f"{name}_target")
            setattr(self, name, ist + self.steigung if ist < soll else max(20.0, ist - 1.0))
        return {
            "extruder": {"temperature": self.nozzle, "target": self.nozzle_target},
            "heater_bed": {"temperature": self.bed, "target": self.bed_target},
        }


@pytest.fixture(autouse=True)
def ohne_warten(monkeypatch):
    monkeypatch.setattr("bedlevel.moonraker.time.sleep", lambda _: None)


def test_erreicht_ziel_ohne_stoerung():
    mr = FakeMoonraker()
    mr.script("M140 S60")
    mr.script("M104 S140")
    mr.wait_for_temperature(extruder=140, bed=60, poll=0)
    assert mr.nozzle >= 138.5 and mr.bed >= 58.5


def test_genullter_sollwert_wird_neu_gesetzt():
    """Der eigentliche Regressionsfall."""
    mr = FakeMoonraker(nullt_nach=3)
    mr.script("M140 S60")
    mr.script("M104 S140")
    gemeldet: list[dict] = []
    mr.wait_for_temperature(
        extruder=140, bed=60, poll=0, on_reset=lambda t: gemeldet.append(t)
    )
    assert gemeldet, "Die Nullung haette gemeldet werden muessen"
    assert mr.bed_target == 60 and mr.nozzle_target == 140
    assert mr.nozzle >= 138.5


def test_keepalive_sendet_regelmaessig_nach():
    mr = FakeMoonraker(steigung=0.6)
    mr.script("M140 S60")
    mr.script("M104 S140")
    mr.wait_for_temperature(extruder=140, bed=60, poll=0, keepalive=0)
    # Deutlich mehr als die zwei Kommandos vom Anfang.
    assert mr.skripte.count("M104 S140") > 5


def test_stillstand_bricht_mit_klarer_meldung_ab(monkeypatch):
    """Heizung defekt: Temperatur steigt nicht, trotz Nachsetzen."""
    uhr = {"t": 0.0}
    monkeypatch.setattr("bedlevel.moonraker.time.monotonic", lambda: uhr["t"])

    class Kalt(FakeMoonraker):
        def temperatures(self):
            uhr["t"] += 10.0
            return {
                "extruder": {"temperature": 20.0, "target": self.nozzle_target},
                "heater_bed": {"temperature": 20.0, "target": self.bed_target},
            }

    mr = Kalt()
    with pytest.raises(MoonrakerError, match="steigt seit"):
        mr.wait_for_temperature(extruder=140, bed=60, poll=0, stall_timeout=60)


def test_bereits_warm_kehrt_sofort_zurueck():
    mr = FakeMoonraker()
    mr.bed, mr.nozzle = 61.0, 141.0
    mr.wait_for_temperature(extruder=140, bed=60, poll=0)
    assert mr.polls == 1
