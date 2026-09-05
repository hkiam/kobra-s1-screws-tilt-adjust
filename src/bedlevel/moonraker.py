"""Duenner, synchroner Moonraker-HTTP-Client.

Bewusst nur die Endpunkte, die fuer die Bettjustage gebraucht werden.
Alle Methoden werfen bei Fehlern MoonrakerError mit der Klartextmeldung
des Druckers, damit die CLI sie direkt anzeigen kann.
"""

from __future__ import annotations

import time
from typing import Any

import httpx


class MoonrakerError(RuntimeError):
    pass


class PrinterNotReady(MoonrakerError):
    pass


class Moonraker:
    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        *,
        timeout: float = 15.0,
        script_timeout: float = 600.0,
    ) -> None:
        headers = {"X-Api-Key": api_key} if api_key else {}
        self._client = httpx.Client(base_url=base_url, headers=headers, timeout=timeout)
        self._script_timeout = script_timeout

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "Moonraker":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- Transport ---------------------------------------------------------

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            resp = self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise MoonrakerError(f"Verbindung zu {self._client.base_url}{path} fehlgeschlagen: {exc}") from exc

        try:
            payload = resp.json()
        except ValueError:
            raise MoonrakerError(
                f"Unerwartete Antwort ({resp.status_code}) von {path}: {resp.text[:200]!r}"
            ) from None

        if isinstance(payload, dict) and "error" in payload:
            err = payload["error"]
            message = err.get("message") if isinstance(err, dict) else str(err)
            raise MoonrakerError(str(message))
        if resp.status_code >= 400:
            raise MoonrakerError(f"HTTP {resp.status_code} von {path}: {resp.text[:200]}")
        if not isinstance(payload, dict) or "result" not in payload:
            raise MoonrakerError(f"Antwort ohne 'result' von {path}: {payload!r}")
        return payload["result"]

    # -- Info / Discovery --------------------------------------------------

    def server_info(self) -> dict[str, Any]:
        return self._request("GET", "/server/info")

    def printer_info(self) -> dict[str, Any]:
        return self._request("GET", "/printer/info")

    def objects_list(self) -> list[str]:
        return list(self._request("GET", "/printer/objects/list").get("objects", []))

    def gcode_help(self) -> dict[str, str]:
        """Alle vom Drucker registrierten erweiterten G-Code-Kommandos."""
        return dict(self._request("GET", "/printer/gcode/help"))

    # -- Status ------------------------------------------------------------

    def query(self, *objects: str) -> dict[str, Any]:
        params = "&".join(objects)
        result = self._request("GET", f"/printer/objects/query?{params}")
        return result.get("status", {})

    def state(self) -> str:
        return str(self.printer_info().get("state", "unknown"))

    def require_ready(self) -> None:
        info = self.printer_info()
        state = info.get("state")
        if state != "ready":
            raise PrinterNotReady(
                f"Drucker ist nicht bereit (state={state}): {info.get('state_message', '').strip()}"
            )

    # -- Steuerung ---------------------------------------------------------

    def script(self, gcode: str, *, timeout: float | None = None) -> None:
        """G-Code ausfuehren und auf Abschluss warten.

        Moonraker antwortet erst, wenn der Befehl abgearbeitet ist. Fuer
        kurze Tippbewegungen daher einen eigenen, knappen Timeout setzen,
        damit eine haengende Anfrage nicht die Bedienung blockiert.
        """
        self._request(
            "POST",
            "/printer/gcode/script",
            params={"script": gcode},
            timeout=self._script_timeout if timeout is None else timeout,
        )

    def emergency_stop(self) -> None:
        self._request("POST", "/printer/emergency_stop")

    def wait_for_moves(self) -> None:
        self.script("M400")

    # -- Hilfsabfragen -----------------------------------------------------

    def homed_axes(self) -> str:
        return str(self.query("toolhead").get("toolhead", {}).get("homed_axes", ""))

    def position(self) -> list[float]:
        return list(self.query("toolhead").get("toolhead", {}).get("position", []))

    def axis_limits(self) -> dict[str, tuple[float, float]]:
        th = self.query("toolhead").get("toolhead", {})
        lo = th.get("axis_minimum") or []
        hi = th.get("axis_maximum") or []
        out: dict[str, tuple[float, float]] = {}
        for idx, axis in enumerate("xyz"):
            if idx < len(lo) and idx < len(hi):
                out[axis] = (float(lo[idx]), float(hi[idx]))
        return out

    def raw_and_gcode_z(self) -> tuple[float | None, float | None]:
        """Rohe Kinematik-Z und mesh-transformierte gcode-Z."""
        status = self.query("toolhead", "gcode_move")
        pos = status.get("toolhead", {}).get("position") or []
        gpos = status.get("gcode_move", {}).get("gcode_position") or []
        return (
            float(pos[2]) if len(pos) > 2 else None,
            float(gpos[2]) if len(gpos) > 2 else None,
        )

    def last_probe_z(self) -> float | None:
        probe = self.query("probe").get("probe", {})
        value = probe.get("last_z_result")
        return None if value is None else float(value)

    def temperatures(self) -> dict[str, dict[str, float]]:
        status = self.query("extruder", "heater_bed")
        out: dict[str, dict[str, float]] = {}
        for key in ("extruder", "heater_bed"):
            section = status.get(key, {})
            out[key] = {
                "temperature": float(section.get("temperature", 0.0)),
                "target": float(section.get("target", 0.0)),
            }
        return out

    def _resend_targets(self, extruder: float | None, bed: float | None) -> None:
        if bed is not None:
            self.script(f"M140 S{bed:.0f}", timeout=20.0)
        if extruder is not None:
            self.script(f"M104 S{extruder:.0f}", timeout=20.0)

    def wait_for_temperature(
        self,
        *,
        extruder: float | None = None,
        bed: float | None = None,
        tolerance: float = 1.5,
        poll: float = 2.0,
        timeout: float = 900.0,
        keepalive: float = 15.0,
        stall_timeout: float = 120.0,
        on_progress: Any = None,
        on_reset: Any = None,
    ) -> None:
        """Auf Zieltemperatur warten - mit Nachsetzen der Sollwerte.

        Reines Statuspollen ist fuer den Drucker keine Aktivitaet: die
        Sollwerte werden dabei von aussen wieder auf 0 gesetzt und das
        Aufheizen bricht mittendrin ab. Deshalb werden die Targets
        regelmaessig erneut gesendet - das haelt den Drucker beschaeftigt
        und stellt genullte Sollwerte wieder her.

        Anders als M109/M190 laeuft das Warten auf der PC-Seite; der Drucker
        bleibt ansprechbar und Strg-C haengt nicht in einem offenen Request.
        """
        deadline = time.monotonic() + timeout
        next_keepalive = time.monotonic() + keepalive
        best = float("-inf")
        best_at = time.monotonic()

        while True:
            temps = self.temperatures()
            hot = extruder is None or temps["extruder"]["temperature"] >= extruder - tolerance
            warm = bed is None or temps["heater_bed"]["temperature"] >= bed - tolerance
            if on_progress is not None:
                on_progress(temps)
            if hot and warm:
                return

            # Hat jemand die Sollwerte zurueckgesetzt?
            reset = (
                (bed is not None and temps["heater_bed"]["target"] < bed - 0.5)
                or (extruder is not None and temps["extruder"]["target"] < extruder - 0.5)
            )
            now = time.monotonic()
            if reset or now >= next_keepalive:
                if reset and on_reset is not None:
                    on_reset(temps)
                self._resend_targets(extruder, bed)
                next_keepalive = now + keepalive

            # Fortschritt ueberwachen: bleibt die Temperatur trotz Nachsetzen
            # stehen, ist etwas grundsaetzlich falsch.
            current = min(
                temps["extruder"]["temperature"] if extruder is not None else float("inf"),
                temps["heater_bed"]["temperature"] if bed is not None else float("inf"),
            )
            if current > best + 0.5:
                best, best_at = current, now
            elif now - best_at > stall_timeout:
                raise MoonrakerError(
                    f"Temperatur steigt seit {stall_timeout:.0f} s nicht mehr "
                    f"(Duese {temps['extruder']['temperature']:.1f}/{extruder}, "
                    f"Bett {temps['heater_bed']['temperature']:.1f}/{bed}). "
                    "Heizung blockiert oder Sollwert wird extern zurueckgesetzt."
                )

            if now > deadline:
                raise MoonrakerError(
                    "Zieltemperatur nicht innerhalb des Zeitlimits erreicht "
                    f"(Duese {temps['extruder']['temperature']:.1f}/{extruder}, "
                    f"Bett {temps['heater_bed']['temperature']:.1f}/{bed})."
                )
            time.sleep(poll)
