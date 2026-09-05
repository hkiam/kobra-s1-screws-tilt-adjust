"""Smoke-Test der Modulschnittstelle.

Hintergrund: Beim Umbau der Messprozedur ist einmal eine Funktion
verschwunden, die die CLI aufruft - aufgefallen ist das erst am Drucker,
nach einer vollstaendigen Messreihe. Dieser Test faengt so etwas vorher ab.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from bedlevel import cli, procedure

QUELLE = Path(inspect.getfile(cli))


def aufgerufene_namen(modulname: str) -> set[str]:
    baum = ast.parse(QUELLE.read_text())
    treffer = set()
    for knoten in ast.walk(baum):
        if (
            isinstance(knoten, ast.Attribute)
            and isinstance(knoten.value, ast.Name)
            and knoten.value.id == modulname
        ):
            treffer.add(knoten.attr)
    return treffer


@pytest.mark.parametrize("name", sorted(aufgerufene_namen("procedure")))
def test_von_der_cli_genutzte_prozeduren_existieren(name):
    assert hasattr(procedure, name), f"cli.py ruft procedure.{name} auf - fehlt im Modul"


def test_alle_unterbefehle_haben_eine_funktion():
    parser = cli.build_parser()
    unterbefehle = [a for a in parser._actions if hasattr(a, "choices") and a.choices]
    assert unterbefehle, "keine Unterbefehle gefunden"
    for name, unter in unterbefehle[0].choices.items():
        assert unter.get_default("func") is not None, f"'{name}' hat keine Funktion"
