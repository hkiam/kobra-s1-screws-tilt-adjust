"""Tests fuer die verschraenkte Messreihenfolge.

Hintergrund: Wird jeder Punkt am Stueck gemessen, schlaegt ein Absinken des
Betts waehrend der Reihe voll auf den zuletzt gemessenen Punkt durch - aus
einem reinen Zeiteffekt wird eine Scheinverkippung. Verschraenkte Durchgaenge
mit umgekehrter Reihenfolge heben einen gleichmaessigen Zeittrend auf.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from bedlevel import config as C
from bedlevel import procedure
from bedlevel.moonraker import Moonraker
from bedlevel.screws import build_report


class SinkendesbettMoonraker(Moonraker):
    """Perfekt ebenes Bett, das mit jeder Antastung ein Stueck absinkt."""

    def __init__(self, senkung_je_antastung: float = 0.002) -> None:
        self.antastungen = 0
        self.senkung = senkung_je_antastung

    def script(self, gcode: str, *, timeout: float | None = None) -> None:
        if gcode.startswith("PROBE"):
            self.antastungen += 1

    def last_probe_z(self) -> float:
        return -self.antastungen * self.senkung

    def homed_axes(self) -> str:
        return "xyz"

    def query(self, *objects):
        return {"toolhead": {"position": [0, 0, 0, 0]},
                "gcode_move": {"gcode_position": [0, 0, 0, 0]}}


@pytest.fixture
def cfg():
    basis = C.load("bedlevel.toml")
    return replace(basis, probe=replace(basis.probe, samples_per_point=8, settle_seconds=0))


def scheinkippung(cfg) -> float:
    """Spannweite, die allein durch das Absinken entsteht."""
    mr = SinkendesbettMoonraker()
    messungen = procedure.measure_all(cfg, mr)
    return build_report(messungen, cfg.screws).span


def test_kreuzweise_reihenfolge_meidet_nachbarn():
    punkte = C.load("bedlevel.toml").screws.points
    reihe = [s.name for s in procedure.kreuzweise(list(punkte))]
    assert reihe == ["vorne links", "hinten rechts", "vorne rechts", "hinten links"]


def test_zweiter_durchgang_laeuft_rueckwaerts(cfg):
    """Nur so liegt der zeitliche Schwerpunkt jeder Ecke in der Mitte."""
    protokoll: list[str] = []
    mr = SinkendesbettMoonraker()
    procedure.measure_all(replace(cfg, probe=replace(cfg.probe, passes=2)), mr,
                          notify=lambda m: protokoll.append(m))
    durchgaenge = [z for z in protokoll if z.startswith("Durchgang")]
    assert len(durchgaenge) == 2
    erster = durchgaenge[0].split(": ")[1].split(" -> ")
    zweiter = durchgaenge[1].split(": ")[1].split(" -> ")
    assert zweiter == list(reversed(erster))


def test_verschraenkte_messung_unterdrueckt_die_scheinkippung(cfg):
    """Der eigentliche Gewinn: ein ebenes Bett wird auch als eben gemessen."""
    sequenziell = scheinkippung(replace(cfg, probe=replace(cfg.probe, passes=1)))
    verschraenkt = scheinkippung(replace(cfg, probe=replace(cfg.probe, passes=2)))
    assert verschraenkt < sequenziell / 4, (
        f"sequenziell {sequenziell:.4f} mm, verschraenkt {verschraenkt:.4f} mm"
    )


def test_samples_werden_gleichmaessig_verteilt(cfg):
    mr = SinkendesbettMoonraker()
    messungen = procedure.measure_all(replace(cfg, probe=replace(cfg.probe, passes=2)), mr)
    for m in messungen:
        assert len(m.samples) == cfg.probe.samples_per_point


def test_ungerade_verteilung_verliert_keine_messung(cfg):
    """7 Messungen auf 2 Durchgaenge: 4 + 3, keine faellt unter den Tisch."""
    angepasst = replace(cfg, probe=replace(cfg.probe, samples_per_point=7, passes=2))
    messungen = procedure.measure_all(angepasst, SinkendesbettMoonraker())
    for m in messungen:
        assert len(m.samples) == 7
