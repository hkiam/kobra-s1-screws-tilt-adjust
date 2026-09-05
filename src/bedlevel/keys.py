"""Tastenleser fuer den cbreak-Modus.

Bewusst auf Byte-Ebene (os.read auf dem Dateideskriptor) statt ueber
sys.stdin: ein gepufferter TextIOWrapper zieht ganze Escape-Sequenzen in
seinen eigenen Puffer, waehrend select() nur den Dateideskriptor sieht und
dann faelschlich "nichts da" meldet. Die Sequenz zerfaellt dadurch in
einzelne, unbekannte Zeichen - die Bedienung steht.
"""

from __future__ import annotations

import os
import select

ESC = 0x1B
# Abschlusszeichen einer CSI-Sequenz nach ECMA-48.
FINAL_MIN, FINAL_MAX = 0x40, 0x7E
# So lange auf den Rest einer angefangenen Escape-Sequenz warten.
SEQ_TIMEOUT = 0.05

KEY_UP = "\x1b[A"
KEY_DOWN = "\x1b[B"
KEY_RIGHT = "\x1b[C"
KEY_LEFT = "\x1b[D"
KEY_PGUP = "\x1b[5~"
KEY_PGDN = "\x1b[6~"
KEY_CTRL_C = "\x03"


class KeyReader:
    def __init__(self, fd: int) -> None:
        self.fd = fd
        self._buf = bytearray()

    def _pump(self, timeout: float | None) -> bool:
        """Einmal vom Deskriptor nachlesen. True, wenn Bytes dazukamen."""
        try:
            ready, _, _ = select.select([self.fd], [], [], timeout)
        except (OSError, ValueError):
            return False
        if not ready:
            return False
        try:
            data = os.read(self.fd, 64)
        except OSError:
            return False
        if not data:
            return False
        self._buf.extend(data)
        return True

    def pending(self) -> bool:
        """Liegt bereits eine weitere Taste vor?"""
        return bool(self._buf) or self._pump(0)

    def read_key(self, timeout: float | None = None) -> str | None:
        """Eine Taste lesen. None, wenn innerhalb von timeout nichts kam."""
        if not self._buf and not self._pump(timeout):
            return None
        return self._parse()

    def _take(self, count: int) -> str:
        chunk = bytes(self._buf[:count])
        del self._buf[:count]
        return chunk.decode("utf-8", "replace")

    def _parse(self) -> str:
        if self._buf[0] != ESC:
            return self._take(1)

        if len(self._buf) == 1:
            self._pump(SEQ_TIMEOUT)
        if len(self._buf) == 1:
            return self._take(1)  # einzelnes ESC

        if self._buf[1] not in (0x5B, 0x4F):  # '[' oder 'O'
            return self._take(2)

        i = 2
        while True:
            if i >= len(self._buf):
                if not self._pump(SEQ_TIMEOUT):
                    return self._take(len(self._buf))  # unvollstaendig, verwerfen
                continue
            byte = self._buf[i]
            i += 1
            if FINAL_MIN <= byte <= FINAL_MAX:
                return self._take(i)
