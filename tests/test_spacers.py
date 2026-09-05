"""Tests fuer Spacerberechnung und STL-Geometrie."""

from __future__ import annotations

import math
import struct
from dataclasses import replace

import pytest

from bedlevel.config import Screw, SpacerCfg
from bedlevel.screws import Measurement
from bedlevel.spacers import compute, hollow_cylinder, mesh_volume, write_stl


@pytest.fixture
def cfg():
    return SpacerCfg()


def messung(werte: dict[str, float]) -> list[Measurement]:
    lage = {"vorne links": (41, 43), "vorne rechts": (211, 43),
            "hinten rechts": (211, 213), "hinten links": (41, 213)}
    return [
        Measurement(screw=Screw(n, *lage.get(n, (0.0, 0.0))), samples=[z])
        for n, z in werte.items()
    ]


# --- Hoehenberechnung -------------------------------------------------------

def test_tiefste_ecke_bekommt_die_volle_bauhoehe(cfg):
    """Wer am tiefsten liegt, braucht am meisten Material."""
    s = compute(messung({"vorne links": -0.60, "vorne rechts": -0.40,
                         "hinten rechts": -0.50, "hinten links": -0.45}), cfg)
    nach_name = {x.name: x for x in s}
    assert nach_name["vorne links"].height == cfg.max_height
    assert max(x.height for x in s) == cfg.max_height


def test_hoehendifferenz_entspricht_dem_versatz(cfg):
    s = compute(messung({"a": -0.60, "b": -0.40}), cfg)
    nach_name = {x.name: x for x in s}
    # b liegt 0.20 mm hoeher -> Spacer 0.20 mm flacher
    assert nach_name["b"].height == pytest.approx(cfg.max_height - 0.20, abs=0.005)


def test_ebenes_bett_ergibt_gleiche_spacer(cfg):
    s = compute(messung({"a": -0.5, "b": -0.5, "c": -0.5, "d": -0.5}), cfg)
    assert {x.height for x in s} == {cfg.max_height}


def test_kompression_ueberhoeht_die_differenz(cfg):
    """TPU gibt nach: hohe Spacer werden staerker gestaucht als flache."""
    ohne = compute(messung({"a": -0.60, "b": -0.40}), cfg)
    mit = compute(messung({"a": -0.60, "b": -0.40}), replace(cfg, compression=0.2))
    diff_ohne = max(x.height for x in ohne) - min(x.height for x in ohne)
    diff_mit = max(x.height for x in mit) - min(x.height for x in mit)
    assert diff_mit > diff_ohne
    assert diff_mit == pytest.approx(0.20 / 0.8, abs=0.005)


def test_zu_grosser_versatz_wird_abgelehnt(cfg):
    """Lieber ein klarer Fehler als ein Spacer mit negativer Hoehe."""
    with pytest.raises(ValueError, match="max_height"):
        compute(messung({"a": -12.0, "b": 0.0}), cfg)


def test_ohne_messwerte_fehler(cfg):
    with pytest.raises(ValueError, match="Keine Messwerte"):
        compute([], cfg)


def test_dateiname_enthaelt_hoehe_und_punkt(cfg):
    s = compute(messung({"hinten rechts": -0.5}), cfg)[0]
    assert s.filename == "spacer_hinten_rechts_10.50mm.stl"


# --- Geometrie --------------------------------------------------------------

@pytest.mark.parametrize("segments", [32, 64, 128, 256])
def test_netz_ist_geschlossen(segments):
    """Jede Kante genau zweimal - sonst ist das Netz nicht wasserdicht."""
    tris = hollow_cylinder(8.74, 4.3, 10.5, segments)
    kanten: dict[frozenset, int] = {}
    for t in tris:
        for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
            kanten[frozenset((a, b))] = kanten.get(frozenset((a, b)), 0) + 1
    assert [v for v in kanten.values() if v != 2] == []


def test_volumen_trifft_die_analytische_formel():
    """Faengt falsch orientierte Flaechen ab - der Fehler war real."""
    od, id_, h = 8.74, 4.3, 10.5
    v = mesh_volume(hollow_cylinder(od, id_, h, 256))
    exakt = math.pi * ((od / 2) ** 2 - (id_ / 2) ** 2) * h
    assert v > 0, "negatives Volumen = Normalen zeigen nach innen"
    assert v == pytest.approx(exakt, rel=0.001)


def test_masse_werden_eingehalten():
    tris = hollow_cylinder(8.74, 4.3, 10.5, 128)
    ecken = [v for t in tris for v in t]
    radien = [math.hypot(x, y) for x, y, _ in ecken]
    assert max(radien) == pytest.approx(4.37, abs=0.005)
    assert min(radien) == pytest.approx(2.15, abs=0.005)
    assert max(z for _, _, z in ecken) == pytest.approx(10.5)
    assert min(z for _, _, z in ecken) == 0.0


def test_stl_ist_lesbares_binaerformat(tmp_path):
    tris = hollow_cylinder(8.74, 4.3, 10.5, 64)
    pfad = write_stl(tmp_path / "t.stl", tris, "test")
    rohdaten = pfad.read_bytes()
    (anzahl,) = struct.unpack("<I", rohdaten[80:84])
    assert anzahl == len(tris)
    assert len(rohdaten) == 84 + anzahl * 50
