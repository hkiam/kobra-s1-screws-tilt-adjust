"""Regressionstests fuer den Tastenleser.

Hintergrund: Eine erste Fassung las ueber sys.stdin (gepufferter
TextIOWrapper) und fragte select() auf dem Dateideskriptor. Kamen mehrere
Escape-Sequenzen in einem Rutsch an, lagen sie in Pythons Puffer, select
meldete "nichts da", und die Sequenzen zerfielen in unbekannte Einzelzeichen -
die Bedienung stand nach dem ersten Tastendruck.
"""

from __future__ import annotations

import os

import pytest

from bedlevel.keys import (
    KEY_DOWN,
    KEY_LEFT,
    KEY_PGDN,
    KEY_PGUP,
    KEY_RIGHT,
    KEY_UP,
    KeyReader,
)
from bedlevel.teach import Limits, Pose, apply_key


@pytest.fixture
def limits() -> Limits:
    return Limits(x=(-6.0, 265.0), y=(0.0, 277.0), z=(0.0, 50.0))


def reader_with(*chunks: bytes) -> KeyReader:
    read_fd, write_fd = os.pipe()
    for chunk in chunks:
        os.write(write_fd, chunk)
    os.close(write_fd)
    return KeyReader(read_fd)


def drain(reader: KeyReader, count: int) -> list[str]:
    keys = []
    for _ in range(count):
        key = reader.read_key(0.3)
        if key is None:
            break
        keys.append(key)
    return keys


def test_mehrere_sequenzen_in_einem_schreibvorgang():
    """Der eigentliche Regressionsfall."""
    reader = reader_with(b"\x1b[C\x1b[C\x1b[A")
    assert drain(reader, 3) == [KEY_RIGHT, KEY_RIGHT, KEY_UP]


def test_sequenz_byteweise_zerstueckelt():
    reader = reader_with(b"\x1b", b"[", b"D")
    assert reader.read_key(0.3) == KEY_LEFT


def test_sequenzen_mit_parameterbytes():
    reader = reader_with(b"\x1b[5~\x1b[6~")
    assert drain(reader, 2) == [KEY_PGUP, KEY_PGDN]


def test_normale_zeichen_und_sequenzen_gemischt():
    reader = reader_with(b"3\x1b[B\rs")
    assert drain(reader, 4) == ["3", KEY_DOWN, "\r", "s"]


def test_einzelnes_escape_blockiert_nicht():
    reader = reader_with(b"\x1b")
    assert reader.read_key(0.3) == "\x1b"


def test_pending_erkennt_gepufferte_taste():
    reader = reader_with(b"\x1b[C\x1b[C")
    reader.read_key(0.3)
    assert reader.pending() is True


def test_read_key_ohne_eingabe_gibt_none(limits):
    read_fd, _write_fd = os.pipe()
    assert KeyReader(read_fd).read_key(0.01) is None


def test_bewegung_summiert_sich(limits):
    pose = Pose(x=100.0, y=100.0, z=5.0, step_index=2)  # 1 mm
    for key in [KEY_RIGHT] * 5 + [KEY_UP] * 3:
        assert apply_key(key, pose, limits) is None
    assert pose.xyz() == (105.0, 103.0, 5.0)


def test_schrittweite_umschalten(limits):
    pose = Pose(x=100.0, y=100.0, z=5.0, step_index=2)
    apply_key("5", pose, limits)  # 10 mm
    apply_key(KEY_RIGHT, pose, limits)
    assert pose.x == 110.0


def test_clamping_an_den_achsgrenzen(limits):
    pose = Pose(x=264.0, y=0.5, z=0.2, step_index=4)  # 10 mm
    for key in (KEY_RIGHT, KEY_DOWN, KEY_PGDN):
        apply_key(key, pose, limits)
    assert pose.xyz() == (265.0, 0.0, 0.0)


@pytest.mark.parametrize(
    "key,erwartet",
    [("\r", "accept"), ("\n", "accept"), ("s", "skip"), ("q", "abort"), ("\x03", "abort"), ("x", None)],
)
def test_aktionstasten(key, erwartet, limits):
    assert apply_key(key, Pose(0.0, 0.0, 0.0), limits) == erwartet


# --- Referenzwahl -----------------------------------------------------------

from dataclasses import replace  # noqa: E402

from bedlevel.config import Screw, ScrewCfg  # noqa: E402
from bedlevel.screws import Measurement, build_report  # noqa: E402

# Reale Messwerte vom Geraet.
MESSUNG = {"vorne links": -0.4370, "vorne rechts": -0.5842,
           "hinten rechts": -0.3483, "hinten links": -0.2900}


def _messungen():
    punkte = [Screw("vorne links", 41, 43), Screw("vorne rechts", 211, 43),
              Screw("hinten rechts", 211, 213), Screw("hinten links", 41, 213)]
    return [Measurement(screw=s, samples=[MESSUNG[s.name]]) for s in punkte]


def _cfg(reference, cw_lowers_bed=True, tolerance_minutes=5.0):
    return ScrewCfg(reference=reference, cw_lowers_bed=cw_lowers_bed,
                    tolerance_minutes=tolerance_minutes,
                    points=[m.screw for m in _messungen()])


def test_nur_anziehen_verlangt_kein_loesen():
    bericht = build_report(_messungen(), _cfg("nur-anziehen"))
    assert bericht.reference == "vorne rechts"  # die tiefste Ecke
    assert not [a for a in bericht.adjustments if a.direction == "loesen" and not a.ok]


def test_nur_anziehen_kehrt_sich_bei_umgekehrter_mechanik_um():
    """Loest Anziehen das Bett nach oben, ist die hoechste Ecke die Referenz."""
    bericht = build_report(_messungen(), _cfg("nur-anziehen", cw_lowers_bed=False))
    assert bericht.reference == "hinten links"
    assert not [a for a in bericht.adjustments if a.direction == "loesen" and not a.ok]


def test_feste_referenz_wird_genommen():
    bericht = build_report(_messungen(), _cfg("hinten links"))
    assert bericht.reference == "hinten links"


def test_auto_minimiert_den_gesamtaufwand():
    auto = build_report(_messungen(), _cfg("auto"))
    summe = lambda b: sum(a.turns for a in b.adjustments)
    for name in MESSUNG:
        assert summe(auto) <= summe(build_report(_messungen(), _cfg(name))) + 1e-9


def test_unbekannte_referenz_meldet_fehler():
    import pytest
    with pytest.raises(ValueError, match="nicht in den Messwerten"):
        build_report(_messungen(), _cfg("gibt es nicht"))


# --- Klipper-Notation -------------------------------------------------------

@pytest.mark.parametrize(
    "turns,erwartet",
    [(0.0, "00:00"), (0.25, "00:15"), (0.5, "00:30"), (1.0, "01:00"),
     (1.25, "01:15"), (1.0 + 20/60, "01:20"), (2.5, "02:30"),
     (0.99999, "01:00"), (0.21, "00:13")],
)
def test_uhrzeit_notation(turns, erwartet):
    """01:20 heisst 1 volle Umdrehung und 20 Minuten (Klipper-Schreibweise)."""
    from bedlevel.screws import Adjustment
    a = Adjustment(screw=Screw("x", 0, 0), z=0, spread=0, delta=0, turns=turns,
                   degrees=turns * 360, clock_minutes=(turns % 1) * 60,
                   direction="CW", is_reference=False, ok=False)
    assert a.clock == erwartet


def test_basisschraube_wird_als_base_ausgewiesen():
    bericht = build_report(_messungen(), _cfg("nur-anziehen"))
    basis = [a for a in bericht.adjustments if a.is_reference]
    assert len(basis) == 1
    assert basis[0].action == "(base)"


def test_richtungen_heissen_cw_und_ccw():
    bericht = build_report(_messungen(), _cfg("auto"))
    richtungen = {a.direction for a in bericht.adjustments if a.direction}
    assert richtungen <= {"CW", "CCW"}


# --- Toleranz in Minuten ----------------------------------------------------

@pytest.mark.parametrize(
    "minuten,erwartet",
    [(0, "an der Grenze des mechanischen Spiels"), (1.9, "an der Grenze des mechanischen Spiels"),
     (2, "exzellent"), (4.9, "exzellent"), (5, "gut"), (9.9, "gut"), (10, "noch nachstellen")],
)
def test_einstufung_nach_praxiswerten(minuten, erwartet):
    from bedlevel.screws import einstufung
    assert einstufung(minuten) == erwartet


def test_toleranz_wird_in_minuten_beurteilt():
    """Die Beurteilung muss sich mit der angezeigten adjust-Zahl decken."""
    bericht = build_report(_messungen(), _cfg("nur-anziehen", tolerance_minutes=5))
    for a in bericht.adjustments:
        if a.is_reference:
            continue
        angezeigte_minuten = int(a.clock.split(":")[0]) * 60 + int(a.clock.split(":")[1])
        assert a.ok == (angezeigte_minuten <= 5)


def test_grosszuegige_toleranz_beendet_die_schleife():
    assert build_report(_messungen(), _cfg("nur-anziehen", tolerance_minutes=30)).done


def test_strenge_toleranz_verlangt_nachstellen():
    assert not build_report(_messungen(), _cfg("nur-anziehen", tolerance_minutes=2)).done


def test_spannweite_in_minuten_passt_zur_steigung():
    bericht = build_report(_messungen(), _cfg("auto"))
    # 0.294 mm bei 0.7 mm Steigung -> 0.42 Umdrehungen -> rund 25 Minuten
    assert 24 <= bericht.span_minutes <= 26


# --- Drifterkennung ---------------------------------------------------------

@pytest.mark.parametrize(
    "samples,erwartet_drift",
    [([-0.4375, -0.4625, -0.4800], True),   # der reale Fall vom Geraet
     ([-0.5258, -0.5208, -0.4825], True),
     ([-0.4683, -0.4650, -0.4658], False),  # zufaellige Streuung
     ([-0.30, -0.31, -0.30], False),
     ([-0.30, -0.30], False)],              # zu wenige Werte fuer eine Aussage
)
def test_monotone_drift_wird_erkannt(samples, erwartet_drift):
    m = Measurement(screw=Screw("x", 0, 0), samples=samples)
    assert bool(m.drift) is erwartet_drift


def test_drift_gibt_die_gesamtaenderung_zurueck():
    m = Measurement(screw=Screw("x", 0, 0), samples=[-0.4375, -0.4625, -0.4800])
    assert m.drift == pytest.approx(-0.0425)


def test_median_bleibt_gegen_einzelne_ausreisser_robust():
    m = Measurement(screw=Screw("x", 0, 0), samples=[-0.30, -0.31, -0.90])
    assert m.z == pytest.approx(-0.31)


def test_verrauschter_trend_in_langer_reihe():
    """Der reale 10er-Verlauf vom Geraet: sinkt, aber nicht streng monoton."""
    m = Measurement(screw=Screw("x", 0, 0), samples=[
        -0.2775, -0.2775, -0.2825, -0.2900, -0.2850,
        -0.2875, -0.2875, -0.2867, -0.2925, -0.2925])
    assert m.drift < 0


def test_reines_rauschen_in_langer_reihe_ist_kein_trend():
    m = Measurement(screw=Screw("x", 0, 0), samples=[
        -0.300, -0.305, -0.298, -0.303, -0.299,
        -0.302, -0.300, -0.304, -0.298, -0.301])
    assert m.drift == 0.0


# --- Zwei-Lagen-Erkennung ---------------------------------------------------

def test_zwei_lagen_werden_erkannt():
    """Realer Verlauf vom Geraet: die Werte springen zwischen zwei Lagen."""
    m = Measurement(screw=Screw("x", 0, 0), samples=[
        -0.5358, -0.6667, -0.5200, -0.6958, -0.5175, -0.6983, -0.5258, -0.7075])
    assert m.gap == pytest.approx(0.1309, abs=1e-4)


def test_stabiler_punkt_hat_keine_luecke():
    """Aus derselben Reihe, aber eine gesunde Ecke."""
    m = Measurement(screw=Screw("x", 0, 0), samples=[
        -0.4258, -0.4258, -0.4267, -0.4317, -0.4258, -0.4250, -0.4375, -0.4208])
    assert m.gap == 0.0


def test_gleichmaessige_streuung_ist_keine_luecke():
    m = Measurement(screw=Screw("x", 0, 0), samples=[-0.30, -0.31, -0.32, -0.33, -0.34, -0.35])
    assert m.gap == 0.0


def test_median_zwischen_zwei_lagen_ist_physikalisch_leer():
    """Dokumentiert, warum die Luecke gemeldet werden muss."""
    m = Measurement(screw=Screw("x", 0, 0), samples=[
        -0.5358, -0.6667, -0.5200, -0.6958, -0.5175, -0.6983, -0.5258, -0.7075])
    # Der Median liegt in der Luecke - weit weg von jedem gemessenen Wert.
    assert min(abs(m.z - w) for w in m.samples) > 0.05


# --- Schutz vor Justage auf unbrauchbare Messwerte --------------------------

ZWEI_LAGEN = [-0.5358, -0.6667, -0.5200, -0.6958, -0.5175, -0.6983, -0.5258, -0.7075]
STABIL = [-0.4258, -0.4258, -0.4267, -0.4317, -0.4258, -0.4250, -0.4375, -0.4208]


def _gemischte_messung():
    """Die reale Reihe vom Geraet: vorne links rastet zwischen zwei Lagen."""
    punkte = [Screw("vorne links", 41, 43), Screw("vorne rechts", 211, 43),
              Screw("hinten rechts", 211, 213), Screw("hinten links", 41, 213)]
    proben = [ZWEI_LAGEN, [-0.45] * 8, STABIL, [-0.54] * 8]
    return [Measurement(screw=s, samples=p) for s, p in zip(punkte, proben)]


def test_zwei_lagen_punkt_wird_als_untragfaehig_markiert():
    bericht = build_report(_gemischte_messung(), _cfg("nur-anziehen"))
    assert not bericht.trustworthy
    schlecht = [a.screw.name for a in bericht.unreliable]
    assert schlecht == ["vorne links"]


def test_untragfaehiger_punkt_wird_nicht_referenz():
    """Sonst richtet sich das ganze Bett nach einem Phantomwert."""
    bericht = build_report(_gemischte_messung(), _cfg("nur-anziehen"))
    assert bericht.reference != "vorne links"


def test_gesunde_messung_bleibt_tragfaehig():
    assert build_report(_messungen(), _cfg("nur-anziehen")).trustworthy


def test_ausdrueckliche_referenz_wird_respektiert():
    """Wer eine Schraube ausdruecklich nennt, bekommt sie auch."""
    bericht = build_report(_gemischte_messung(), _cfg("vorne links"))
    assert bericht.reference == "vorne links"


# --- Bewertung relativ zum Ziel ---------------------------------------------

def test_kleine_drift_blockiert_bei_grosszuegigem_ziel_nicht():
    """Reale Drift vom Geraet: 0.0142 mm sind bei 00:10 rund ein Achtel der Toleranz."""
    from bedlevel.screws import unreliable_reason
    m = Measurement(screw=Screw("x", 0, 0), samples=[
        -0.4000, -0.4020, -0.4040, -0.4060, -0.4080, -0.4100, -0.4120, -0.4142])
    assert abs(m.drift) > 0                      # die Drift wird erkannt
    toleranz_10min = 10 / 60 * 0.7               # 0.1167 mm
    assert unreliable_reason(m, toleranz_10min) is None


def test_dieselbe_drift_blockiert_bei_strengem_ziel():
    from bedlevel.screws import unreliable_reason
    m = Measurement(screw=Screw("x", 0, 0), samples=[
        -0.4000, -0.4020, -0.4040, -0.4060, -0.4080, -0.4100, -0.4120, -0.4142])
    # Die erkannte Drift betraegt rund 0.008 mm; erst unterhalb davon blockiert sie.
    toleranz_halbe_minute = 0.5 / 60 * 0.7       # 0.0058 mm
    assert unreliable_reason(m, toleranz_halbe_minute) is not None


def test_zwei_lagen_blockieren_unabhaengig_vom_ziel():
    """Eine Luecke im Median ist kein Genauigkeitsproblem, sondern ein Phantomwert."""
    from bedlevel.screws import unreliable_reason
    m = Measurement(screw=Screw("x", 0, 0), samples=ZWEI_LAGEN)
    assert unreliable_reason(m, 10 / 60 * 0.7) is not None


def test_knappe_korrektur_bleibt_sichtbar():
    """Sonst bleibt eine systematische Kippung unbemerkt stehen."""
    from bedlevel.screws import Adjustment
    a = Adjustment(screw=Screw("x", 0, 0), z=0, spread=0, delta=0.116, turns=0.1657,
                   degrees=59.7, clock_minutes=9.9, direction="CW",
                   is_reference=False, ok=True)
    assert a.action == "(CW 00:10)"


def test_wirklich_passende_schraube_zeigt_keine_zahl():
    from bedlevel.screws import Adjustment
    a = Adjustment(screw=Screw("x", 0, 0), z=0, spread=0, delta=0.001, turns=0.001,
                   degrees=0.5, clock_minutes=0.1, direction="CW",
                   is_reference=False, ok=True)
    assert a.action == "passt"


# --- Bettskizze -------------------------------------------------------------

def test_skizze_ordnet_ecken_nach_koordinaten_zu():
    """Die Zuordnung kommt aus X/Y, nicht aus den Namen."""
    from bedlevel.cli import bed_sketch
    # Namen absichtlich unpassend vergeben
    punkte = [Screw("A", 41, 43), Screw("B", 211, 43),
              Screw("C", 211, 213), Screw("D", 41, 213)]
    z = {"A": -0.60, "B": -0.50, "C": -0.40, "D": -0.30}
    ms = [Measurement(screw=s, samples=[z[s.name]]) for s in punkte]
    zeilen = bed_sketch(build_report(ms, ScrewCfg(reference="A", points=punkte))).splitlines()
    # A liegt vorne links (kleines X, kleines Y) -> untere Zeile, links
    assert "+0.000" in zeilen[5]
    # C liegt hinten rechts -> obere Zeile, rechts
    assert "+0.200" in zeilen[1]


def test_skizze_nur_bei_vier_punkten():
    from bedlevel.cli import bed_sketch
    punkte = [Screw("a", 0, 0), Screw("b", 100, 0), Screw("c", 50, 100)]
    ms = [Measurement(screw=s, samples=[0.0]) for s in punkte]
    assert bed_sketch(build_report(ms, ScrewCfg(reference="a", points=punkte))) is None
