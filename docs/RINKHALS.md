# Firmware quirks (Rinkhals / gklib)

*[Deutsche Fassung: RINKHALS.de.md](RINKHALS.de.md)*

The Kobra S1 does not run real Klipper but **gklib** — a Go port by Anycubic.
Rinkhals puts a real Moonraker in front of it. Much behaves as expected, some
things do not. The points below were verified on the machine, not taken from
documentation — they otherwise cost hours.

Tested with Rinkhals `20260901_01`, gklib on `rinkhals_gklib.cfg`.

## `probe` is missing from `objects/list` but can be queried

`/printer/objects/list` does **not** list a `probe` object. Trusting that list
leads to rebuilding the read path for nothing. The query works regardless:

```bash
curl "http://<ip>:7125/printer/objects/query?probe"
# {"probe": {"last_query": false, "last_z_result": 0}}
```

Consequence for the tool: `check` tests the query directly instead of trusting
the list.

## `PROBE` returns the raw kinematic position

A loaded bed mesh transforms the Z axis — by up to 1.8 mm on the test machine,
depending on position. That would be exactly the kind of error that ruins a
corner measurement.

But `probe.last_z_result` follows the **raw** kinematic position, not the
mesh-transformed gcode position. Measured at three points with very different
mesh corrections:

| Point | `last_z_result` | kinematic (raw) | gcode (mesh) | mesh share |
|---|---:|---:|---:|---:|
| centre | −0.1658 | −0.1708 | −0.1158 | −0.055 |
| front left | −0.4308 | −0.4350 | −0.0906 | −0.344 |
| rear right | −0.2783 | −0.2825 | −0.1153 | −0.167 |

The reading follows the raw position throughout. A constant offset of about
0.004 mm remains whose cause is unresolved — it is the same at every point and
cancels out in the relative evaluation. What matters is that the reading follows
the **raw** position and not the gcode position, which is shifted by up to
0.34 mm.

**An active bed mesh therefore does not disturb the measurement.** The tool
leaves it alone but re-checks the assumption at the first measuring point of
every run, in case a firmware update ever reverses it.

## `BED_MESH_CLEAR` has no effect

The command is acknowledged, the mesh stays loaded:

```
before               active=True  profile='default'  range=1.829
after BED_MESH_CLEAR active=True  profile='default'  range=1.829
```

Sending it would only feign safety. The tool therefore does not send it — which,
thanks to the previous point, is not necessary either.

## Idle shuts down heaters and motors

**Status queries over HTTP do not count as activity.** Without G-code the
printer goes idle, switches off the heaters and de-energises the motors — which
loses the homing reference.

This affects any automation that waits for something. Observed: the nozzle fell
back from 105 °C in the middle of heating up while the tool dutifully polled the
status.

Countermeasures in the tool:

- a **keepalive** sending `M105` every 15 s throughout the run — especially
  important while screws are being turned by hand
- **re-sending setpoints** while waiting for temperature
- **verifying homing** instead of assuming it: `G28` is acknowledged even when
  `homed_axes` is empty afterwards

The exact timeout could not be determined — `idle_timeout` is not configured,
and the value `idle_timeout: 30` in the configuration belongs to
`[controller_fan]`, i.e. it is the fan run-on time. The keepalive interval is
therefore chosen conservatively.

## The G-code store holds no responses

`/server/gcode_store` records only the **commands**, not the printer's output.
Commands such as `GET_POSITION` or `BED_MESH_OUTPUT` are therefore not
evaluable over HTTP.

Responses are only available over the WebSocket:

```python
import asyncio, json, websockets

async def main():
    async with websockets.connect("ws://<ip>:7125/websocket") as ws:
        await ws.send(json.dumps({"jsonrpc": "2.0", "method": "printer.gcode.script",
                                  "params": {"script": "BED_MESH_OUTPUT"}, "id": 1}))
        while True:
            msg = json.loads(await ws.recv())
            if msg.get("method") == "notify_gcode_response":
                print(msg["params"])
            elif msg.get("id") == 1:
                break

asyncio.run(main())
```

## The printer's own leveling routine

Found in the buffer of a previous calibration — useful as a template for
temperatures and the wipe sequence:

```
BED_MESH_CLEAR
G28
MOVE_HEAT_POS
M140 S80
M109 S170
M190 S80
WIPE_ENTER
WIPE_NOZZLE
WIPE_EXIT
M109 S140
BED_MESH_CALIBRATE
```

So: wipe at 170 °C, probe at 140 °C. The wipe macros expect a suitable Z height
— on the test machine the nozzle grazes the wiper at **Z 15**; the macros
themselves set no Z.

## Relevant values from `rinkhals_gklib.cfg`

| | |
|---|---|
| Kinematics | corexy, 250 × 250 × 250 mm |
| Axis limits | X −6…265, Y 0…277, Z −4…253 |
| Probe | `[cs1237]` load cell, x/y offset 0 |
| Bed mesh | 5…245, fade 1…10 |
| Z homing | `probe:z_virtual_endstop`, `safe_z_home` at 125,125 |

On the test machine `probe_count` and `algorithm` come from a custom
`printer.custom.cfg` (7 × 7 instead of 5 × 5, `bicubic` instead of `lagrange`) —
see *Optional: a finer bed mesh* in the README. Rinkhals merges the contents of
that file with the stock configuration at startup; `gklib` reads the merged
version, which is why a change requires a reboot and `FIRMWARE_RESTART` is not
enough.
