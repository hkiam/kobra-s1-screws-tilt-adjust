# kobra-s1-screws-tilt-adjust

**Mechanical bed tramming for the Anycubic Kobra S1 running
[Rinkhals](https://github.com/rinkhals-community/Rinkhals/).**

A replacement for Klipper's `SCREWS_TILT_ADJUST`, which does not exist on this
platform. The tool runs on your PC, talks to the printer over Moonraker, probes
the points above the four bed screws and tells you how far to turn each one —
in Klipper notation.

*[Deutsche Fassung: README.de.md](README.de.md) — the detailed documentation in
`docs/` is in German.*

---

## Contents

- [The result](#the-result)
- [Why this exists](#why-this-exists)
- [What it is not](#what-it-is-not)
- [Requirements](#requirements)
- [Installation](#installation)
- [Step by step](#step-by-step)
- [Reading the output](#reading-the-output)
- [Limits: four points define a plane](#limits-four-points-define-a-plane)
- [Optional: a finer bed mesh](#optional-a-finer-bed-mesh)
- [Safety](#safety)
- [Development](#development)
- [Credits](#credits)
- [License](#license)

---

## The result

The test machine had these deviations at its four mounting points out of the
box:

```
                    BEFORE                                     AFTER

                    rear                                       rear
        1.10 mm             0.40 mm               0.08 mm             0.00 mm
             ┌───────────────────┐                     ┌───────────────────┐
       left  │                   │  right        left  │                   │  right
             └───────────────────┘                     └───────────────────┘
        0.10 mm             0.00 mm               0.02 mm             0.04 mm
                    front                                      front

        Range:  1.10 mm                           Range:  0.08 mm
        equals: 01:34                             equals: 00:07
```

**From 1.10 mm down to 0.08 mm** — a factor of 13. The rear left corner was off
by more than a full turn of its screw.

This was achieved in two stages:

1. **Printed spacers** that take out the factory offset — the Kobra S1 ships
   without any (see [docs/SPACER.md](docs/SPACER.md), in German).
2. **Fine adjustment via the screws** using this tool.

What the bed mesh has to compensate afterwards is an entirely different
magnitude. Instead of 1.1 mm of tilt it only handles the residual waviness of
the plate.

---

## Why this exists

Klipper ships an excellent tool for mechanical bed tramming:
[`SCREWS_TILT_ADJUST`](https://www.klipper3d.org/Manual_Level.html). It moves to
the points above the leveling screws, probes them, and tells you which screw to
turn and by how much.

**On the Kobra S1 that command does not exist.** The printer does not run real
Klipper but `gklib` — a Go port by Anycubic with a reduced feature set. `PROBE`,
`BED_MESH_CALIBRATE` and much else are there; `SCREWS_TILT_ADJUST` is not.
Extending the firmware is not an option: it is proprietary and closed.

**The solution is to move the logic off the printer.** Everything
`SCREWS_TILT_ADJUST` needs is available:

- a command to probe (`PROBE`)
- a way to read the result (`probe.last_z_result`)
- motion control (`G0`/`G1`, `G28`)

Rinkhals exposes an HTTP and WebSocket interface through Moonraker. That is
enough to drive the whole measuring loop from a PC — the printer only executes
individual commands, the evaluation happens outside. This even has advantages:
the evaluation is written in Python, it is testable, and it can be extended
without touching the firmware.

One detail helps a lot: **the Kobra S1 probes with the nozzle itself** (load
cell, `[cs1237]` in its config), with a probe offset of 0/0. The measuring
points are therefore exactly the screw coordinates, with no offset arithmetic.

---

## What it is not

> **This tool does not replace bed leveling.** It establishes the mechanical
> baseline so that the bed mesh has an easy job afterwards.

The division of labour:

| | Task | Using |
|---|---|---|
| **1. Mechanics** | make the bed physically flat | this tool + the screws |
| **2. Software** | compensate residual waviness | `BED_MESH_CALIBRATE` |

A bed mesh can compensate more than a millimetre of tilt mathematically — but
it forces the Z axis to track constantly during every move across the bed. That
costs accuracy, wears the mechanics and hides real problems. The flatter the bed
is mechanically, the less the mesh has to do.

**After tramming, the bed mesh must be recreated** — the bed geometry has
changed.

---

## Requirements

### Printer

| | |
|---|---|
| Model | Anycubic Kobra S1 |
| Firmware | [Rinkhals](https://github.com/rinkhals-community/Rinkhals/), tested with `20260901_01` |
| Klipper core | `gklib` on `rinkhals_gklib.cfg` |
| Network | Moonraker reachable, default port 7125 |

**Rinkhals is required.** The Anycubic stock firmware offers no open access — it
only exposes a proprietary API on port 18086. Rinkhals puts a real Moonraker in
front of it, and only through that is the printer controllable.

### What the tool accesses

Read-only and through Moonraker exclusively. Nothing in the firmware is
modified, no file on the printer is touched, no configuration overwritten.

| Endpoint / object | Purpose |
|---|---|
| `GET /printer/info` | check state |
| `GET /printer/objects/query?toolhead` | position, axis limits, homing status |
| `GET /printer/objects/query?probe` | probe result (`last_z_result`) |
| `GET /printer/objects/query?extruder&heater_bed` | temperatures |
| `GET /printer/objects/query?bed_mesh&gcode_move` | mesh state, Z offset |
| `GET /printer/gcode/help` | discover available commands |
| `POST /printer/gcode/script` | `G28`, `G0`/`G1`, `PROBE`, `M104`/`M140`, `M105` |

**SSH is not required.** It was only useful during development, to work out
firmware quirks — documented in [docs/RINKHALS.md](docs/RINKHALS.md).

### PC

| | |
|---|---|
| Python | ≥ 3.11 |
| Package manager | [uv](https://docs.astral.sh/uv/) |
| OS | Linux, macOS (tested), Windows untested¹ |

¹ `bedlevel teach` uses `termios` for arrow keys and will not run on Windows.
All other commands should work.

### Mechanics

The bed screws must be **mounted with some play** so that preload can be set
through the screw. The Kobra S1 does not provide this out of the box — a
modification is needed, and printed spacers are recommended anyway.

---

## Installation

```bash
git clone https://github.com/hkiam/kobra-s1-screws-tilt-adjust.git
cd kobra-s1-screws-tilt-adjust
uv sync
cp bedlevel.example.toml bedlevel.toml
```

Then edit `bedlevel.toml` — at minimum these values:

| Value | Meaning | Helper |
|---|---|---|
| `printer.host` | your printer's IP | — |
| `screws.points` | coordinates above the screws | `bedlevel teach` |
| `screws.cw_lowers_bed` | whether tightening lowers the bed | `bedlevel calibrate-direction` |
| `screws.tolerance_minutes` | how accurate you want it | see below |

Check that everything is in place:

```bash
uv run bedlevel check
```

```
╭────────────────────────────────── Drucker ───────────────────────────────────╮
│ Verbindung: http://192.168.1.50:7125                                         │
│ Zustand: ready                                                               │
╰──────────────────────────────────────────────────────────────────────────────╯
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━┓
┃ Voraussetzung                                      ┃ vorhanden ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━┩
│ PROBE-Kommando                                     │ ja        │
│ probe.last_z_result                                │ ja        │
│ toolhead-Objekt                                    │ ja        │
│ SCREWS_TILT_ADJUST (dann waere dies hier unnoetig) │ nein      │
└────────────────────────────────────────────────────┴───────────┘
Fahrbereich: X [-6 .. 265]  Y [0 .. 277]  Z [-4 .. 253]
Alles Noetige vorhanden.
```

> **Note:** the program output is in German. The tables are largely
> self-explanatory; `adjust` follows Klipper's `CW 01:20` notation, `Abweichung`
> means deviation, `Spannweite` means range.

---

## Step by step

### 1. Prepare nozzle and plate

Probing is done with the nozzle. A stuck-on piece of filament gets squashed
flatter with every probe and makes the readings drift — the most common cause
of unusable measurements. The tool can wipe the nozzle before each run
(`[wipe]`); otherwise clean it by hand.

Equally important: **seat the build plate flat.** A crumb between the spring
steel sheet and the magnetic base makes the plate rock, and it settles in a
different position on every probe. The readings then jump between two levels
and the median lands in the gap between them.

### 2. Teach the screw positions

```bash
uv run bedlevel teach
```

The nozzle moves to the first screw and you position it with the arrow keys:

```
[vorne links]  fahre Startposition an ...
  Pfeiltasten: X/Y     Bild-auf/ab oder +/-: Z     1-5: Schrittweite
  Enter: Position uebernehmen     s: ueberspringen     q: abbrechen
  X   41.000   Y   43.000   Z   5.000   Schritt 1 mm
```

| Key | Effect |
|---|---|
| Arrows | X / Y |
| Page up/down, `+` / `-` | Z |
| `1`–`5` | step size 0.1 / 0.5 / 1 / 5 / 10 mm |
| Enter | accept, move to next |
| `s` | leave this point unchanged |
| `q` | abort |

Positions are written to `bedlevel.toml`, the previous version to
`bedlevel.toml.bak`.

### 3. Determine the turning direction

Whether tightening raises or lowers your bed depends on your mechanics. Do not
guess: with the wrong assumption every correction makes it twice as bad.

```bash
uv run bedlevel calibrate-direction "vorne links"
```

The command measures, asks you to tighten by a quarter turn, measures again and
reports the value for `cw_lowers_bed`.

### 4. Trammel the bed

```bash
uv run bedlevel level
```

```
Heize Bett auf 60 C und Duese auf 140 C ...
Temperaturen erreicht.
Duese reinigen bei 170 C ...
Durchgang 1/2 (4x je Punkt): vorne links -> hinten rechts -> vorne rechts -> hinten links
  vorne links: z=-0.4633
  ...
Durchgang 2/2 (4x je Punkt): hinten links -> vorne rechts -> hinten rechts -> vorne links
  ...
Fahre den Druckkopf aus dem Weg ...
```

Then the evaluation:

```
        Messung  (Referenz: hinten links, nur-anziehen)
┏━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━┳━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━┓
┃ Schraube      ┃      XY ┃      z ┃   +/- ┃   Abw. ┃ adjust     ┃
┡━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━╇━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━┩
│ vorne links   │   41/43 │ -0.627 │ 0.012 │ +0.011 │ (CW 00:01) │
│ vorne rechts  │  211/43 │ -0.522 │ 0.014 │ +0.116 │ (CW 00:10) │
│ hinten rechts │ 211/213 │ -0.515 │ 0.018 │ +0.123 │ CW 00:11   │
│ hinten links  │  41/213 │ -0.638 │ 0.024 │ +0.000 │ (base)     │
└───────────────┴─────────┴────────┴───────┴────────┴────────────┘
╭─ Abweichung zur Referenz (mm) ─╮
│         hinten                 │
│     +0.000     +0.123          │
│         ┌───────────┐          │
│   links │           │ rechts   │
│         └───────────┘          │
│     +0.011     +0.116          │
│         vorne                  │
╰────────────────────────────────╯
```

*(`vorne` = front, `hinten` = rear, `links` = left, `rechts` = right,
`Schraube` = screw, `Abw.` = deviation.)*

By this point the head has already moved out of the way and the bed has been
lowered — you can reach all screws. Turn, press Enter, next round.

### 5. Recreate the bed mesh

The old mesh is invalid after tramming. On the printer:

```
BED_MESH_CALIBRATE
SAVE_CONFIG
```

If you consistently only tightened, you lowered the bed overall — set the
**Z offset** again first.

---

## Reading the output

### The turn instruction

The notation follows Klipper: `CW 01:20` means **one full turn plus
20 minutes** clockwise.

| Display | Rotation | with M4 (0.7 mm pitch) |
|---|---|---:|
| `01:00` | full turn, 360° | 0.700 mm |
| `00:30` | half turn, 180° | 0.350 mm |
| `00:15` | quarter turn, 90° | 0.175 mm |
| `00:05` | small nudge, 30° | 0.058 mm |

`CW` = clockwise = tighten (with a right-hand thread), `CCW` =
counter-clockwise = loosen. The legend below the table also states which way the
bed moves — at the machine that is less ambiguous than a rotation direction with
a viewing direction in the fine print.

**Parentheses mean: not required, but effective.** `(CW 00:10)` is within
tolerance. This matters when several screws sit just below the limit — turning
only the one that exceeds it makes another the new highest corner, and the range
stays where it was.

`(base)` is the reference screw: leave that one alone.

### Tolerance

| Target | Meaning |
|---|---|
| below `00:10` | **good** — fine for everyday printing, the mesh handles the rest |
| below `00:05` | **excellent** — when the bed should sit as stress-free as possible |
| below `00:02` | **limit of mechanical play** in screws and mounts |

### The metrics

- **Größte Korrektur** (largest correction) — the biggest turn needed, with a
  rating.
- **Spannweite** (range) — difference between highest and lowest corner.
- **Verkippung** (tilt) — slope of the fitted plane in mm/m, split by X and Y.
- **Bettverzug** (bed warp) — what remains after fitting a plane. **The key
  number for knowing when to stop** (see next section).

---

## Limits: four points define a plane

The tool trams **four points**. Four points span a plane — there is no more
information in the measurement. What it can correct:

✅ **Tilt** — the bed sits at an angle, one corner higher than another.
✅ **Offset of individual mounting points** — one corner sagging.

What it **cannot** correct:

❌ **Waviness of the plate** — hills or valleys between the screws.
❌ **Warp** — a plate that bows or ripples.

### Bed warp as the stopping criterion

That is exactly what the **Bettverzug** figure is for: the residual waviness
after fitting a plane through the four measuring points.

```
Bettverzug (nicht wegdrehbar): 0.009 mm = 1 Minute
```

**If this value approaches your tolerance, tramming is exhausted.** Turning
further only shifts which corner is off. The rest belongs in the bed mesh —
that is what it is for.

### If the mesh shows hills in the middle

Run `BED_MESH_CALIBRATE` after tramming and look at the map. A typical picture
for a warped plate:

```
     -0.02  -0.01   0.00  -0.01  -0.02
     -0.01   0.12   0.18   0.11  -0.01
      0.00   0.18   0.24   0.17   0.00      ← hill in the middle
     -0.01   0.11   0.17   0.10  -0.01
     -0.02  -0.01   0.00  -0.01  -0.02
```

The corners sit flat (tramming did that), but the centre is high. **No screw
will fix this** — the plate itself is warped.

With noticeable waviness (roughly from 0.15–0.2 mm) a **thicker or stiffer bed**
is the actual solution:

| Option | Note |
|---|---|
| **Funssor 8 mm aluminium** | obvious swap, considerably stiffer than stock |
| **Precision-milled aluminium bed** | flatter than rolled stock, priced accordingly |
| **Sandwich: 5 mm stock + milled plate** | untested — more mass means longer heat-up and altered heat distribution |

The stock Kobra S1 bed is 5 mm. More thickness means more bending stiffness: the
plate follows the tension from the screws less and stays flatter. The price is
inertia — thicker beds take longer to heat and respond more slowly to
temperature changes.

> **Tram first, then decide.** Without a sound mechanical baseline you cannot
> tell whether waviness comes from the plate or from tension. The reported bed
> warp is the number to judge it by.

---

## Optional: a finer bed mesh

*Not part of this tool, but the obvious companion to it.*

The Kobra S1 probes **5 × 5 points** for its bed mesh out of the box and
interpolates with `lagrange`. For a mechanically well-trammed plate that is
often enough — with noticeable waviness a finer grid is much better: a hill
between two probe points is simply missed at 5 × 5.

Rinkhals provides `printer.custom.cfg` for this. Its contents are **merged**
with the main configuration: new sections are added, existing values overridden.
The stock firmware stays untouched.

The test machine runs these adjustments:

```ini
[probe]
speed: 10.0
final_speed: 10.0
lift_speed: 20.0
samples: 1

[bed_mesh]
speed: 500
horizontal_move_z:2
probe_count:7,7  # original 5,5
algorithm:bicubic

[leviQ3]
bed_temp: 80
```

| Value | Stock | Changed | Effect |
|---|---|---|---|
| `probe_count` | `5,5` | `7,7` | 49 instead of 25 points — finer grid, catches waviness between corners |
| `algorithm` | `lagrange` | `bicubic` | smoother interpolation, less overshoot between nodes |
| `probe.speed` | `4.0` | `10.0` | faster probing — needed, or 7 × 7 takes noticeably longer |
| `probe.samples` | `2` | `1` | one probe per point instead of two |
| `horizontal_move_z` | `3` | `2` | lower travel height between points |
| `leviQ3.bed_temp` | `55` | `80` | calibration temperature of the stock routine |

### How to change it

1. Open `printer.custom.cfg` in **Mainsail** under *Machine*
2. Insert the sections, save
3. **Reboot the printer** — a `FIRMWARE_RESTART` is not enough here, because
   `gklib` reads the merged configuration at startup
4. Then run `BED_MESH_CALIBRATE` and `SAVE_CONFIG`

> **No warranty.** These values come from a single machine. `probe.speed` and
> `samples` affect how hard the nozzle lands — probing too fast can hurt
> repeatability. Verify with `bedlevel stability "<name>"` after changing them.

---

## Commands

| Command | Purpose |
|---|---|
| `check` | verify connection and firmware capabilities |
| `teach` | teach screw positions with the arrow keys |
| `calibrate-direction <name>` | determine turning direction by a test turn |
| `measure` | measure once and evaluate |
| `level` | measure, adjust, repeat until in tolerance |
| `stability <name>` | check repeatability of a single point |
| `spacers` | measure factory offset and generate spacers as STL |
| `cooldown` | switch off the heaters |

---

## Safety

The tool moves a hot print head across a heated bed.

- It only travels within the axis limits **read from the printer**.
- It lifts before every move; before parking it lowers the bed first, then moves
  the head aside.
- On `Ctrl-C` the heaters stay on — `uv run bedlevel cooldown` switches them
  off.

**Watch the first run.** `teach` in particular lets you drive the nozzle all the
way down to bed contact.

---

## Development

```bash
uv run pytest tests -q
```

The tests run **without a printer**. They cover the evaluation, keyboard input,
measuring order and STL geometry — and pin down several bugs that showed up on
the machine:

- escape sequences vanishing into Python's buffer while `select` polls the file
  descriptor
- setpoints being zeroed from outside while the printer sits idle
- readings alternating between two levels, making their median meaningless
- an STL mesh with top and bottom faces wound the wrong way

| Module | Responsibility |
|---|---|
| `moonraker.py` | HTTP client, temperature wait with setpoint refresh |
| `keepalive.py` | keeps the printer awake so idle timeout does not interfere |
| `procedure.py` | measuring sequence: heat, wipe, home, probe, park |
| `screws.py` | evaluation: reference choice, turn advice, plane fit |
| `spacers.py` | spacer calculation and STL generation |
| `keys.py` | key reader for interactive positioning |
| `cli.py` | command line and output |

---

## Credits

This project stands on other people's work. It would not exist without:

### [Rinkhals](https://github.com/rinkhals-community/Rinkhals/)

The alternative firmware that makes the Kobra S1 accessible in the first place.
It puts a real Moonraker in front of the closed `gklib` core — without that
access there would be no way to measure and control the printer from outside.
The entire approach of this tool rests on it. **Many thanks to the Rinkhals
project and everyone contributing to it.**

### [Kobra S1 bed tramming spacers](https://www.makeronline.com/en/model/Kobra%20S1%20bed%20tramming%20spacers/166490.html)

The idea of compensating the factory offset with printed spacers, rather than
loading it all onto the screws, comes from there. This project picks the idea up
and derives the spacers from an actual measurement instead of estimating them.
**Thank you for the blueprint.**

### [Anycubic Kobra S1 – checking and adjusting the flatness of the hot bed](https://forum.makeronline.com/en/forum/topic/anycubic%20kobra%20s1%20-%20checking%20and%20adjusting%20the%20flatness%20of%20the%20hot%20bed-3704.html)

The forum thread with the groundwork: how to assess the flatness of the Kobra S1
heated bed at all, what to watch out for and which magnitudes are realistic.
**Thanks to everyone involved.**

### Klipper

The core idea comes from Klipper's
[`SCREWS_TILT_ADJUST`](https://www.klipper3d.org/Manual_Level.html). This project
reproduces its behaviour for a platform where the command is unavailable —
including the well-established `CW 01:20` notation. **Thanks to the Klipper
project.**

---

## License

[MIT](LICENSE) — © 2026 Maik Hofmann
