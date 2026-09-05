"""Haelt den Drucker waehrend der Justage wach.

Der Drucker faellt nach kurzer Zeit ohne G-Code in den Leerlauf und schaltet
dabei Heizungen ab und die Motoren stromlos - womit auch die Referenzfahrt
verloren geht. Reine Statusabfragen ueber HTTP zaehlen dabei nicht als
Aktivitaet.

Das trifft die Justage an zwei Stellen: beim Warten auf Zieltemperatur und -
deutlich laenger - zwischen zwei Messdurchgaengen, waehrend von Hand an den
Schrauben gedreht wird.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from .moonraker import Moonraker, MoonrakerError

# Deutlich unter dem beobachteten Leerlauf-Zeitfenster.
DEFAULT_INTERVAL = 15.0
# M105 fragt nur Temperaturen ab: keine Bewegung, keine Nebenwirkung, zaehlt
# aber als G-Code-Aktivitaet.
DEFAULT_COMMAND = "M105"


class Keepalive:
    """Sendet regelmaessig ein harmloses Kommando, solange der Block laeuft."""

    def __init__(
        self,
        mr: Moonraker,
        *,
        interval: float = DEFAULT_INTERVAL,
        command: str = DEFAULT_COMMAND,
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        self._mr = mr
        self._interval = interval
        self._command = command
        self._on_error = on_error
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.sent = 0

    def _loop(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self._mr.script(self._command, timeout=20.0)
                self.sent += 1
            except MoonrakerError as exc:
                # Ein verpasster Herzschlag ist kein Grund, die Justage
                # abzubrechen - der naechste Versuch kommt gleich.
                if self._on_error is not None:
                    self._on_error(str(exc))

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="keepalive")
        self._thread.start()

    def stop(self) -> None:
        if self._thread is None:
            return
        self._stop.set()
        self._thread.join(timeout=5.0)
        self._thread = None

    def __enter__(self) -> "Keepalive":
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()
