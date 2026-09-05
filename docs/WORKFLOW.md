# Workflow

*[Deutsche Fassung: WORKFLOW.de.md](WORKFLOW.de.md)*

From the first measurement to a trammed bed. If you already have spacers
fitted, skip step 1.

## Step 0 — Preparation

**Clean nozzle.** Probing is done with the nozzle itself. A stuck-on piece of
filament gets squashed flatter with every probe and makes the readings drift —
the most common cause of unusable measurements. The tool can wipe the nozzle
before every run, see `[wipe]` in the configuration.

**Flat build plate.** A crumb between the spring steel sheet and the magnetic
base makes the plate rock, and it settles differently on every probe. That
produces readings which jump between two levels — useless for tramming. Wipe
both surfaces.

**Measure warm, not cold.** The geometry changes with temperature; trammed cold
means skewed when hot. The defaults are 60 °C bed and 140 °C nozzle. Use the bed
temperature you actually print at.

## Step 1 — Spacers (one-off)

The Kobra S1 ships without spacers. The factory offset of the four mounting
points therefore has to be taken up entirely by the screws — one corner works
permanently near its limit while another has almost no preload. Printed spacers
take that offset out beforehand.

```bash
uv run bedlevel spacers
```

Details, geometry and print parameters: [SPACERS.md](SPACERS.md).

## Step 2 — Teach the positions

The tool needs to know where your screws are. Because probing happens with the
nozzle (probe offset 0/0), the taught nozzle position *is* the measuring
coordinate.

```bash
uv run bedlevel teach
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
`bedlevel.toml.bak`. Use `--dry-run` to only display them.

`teach` starts with `G28` and moves to Z 5 mm. With step size `5` and page-down
you reach bed contact — stay at `1` or below for fine positioning, or start
higher with `--z 10`.

## Step 3 — Determine the turning direction

Whether tightening raises or lowers your bed depends on your mechanics. This is
not something to guess: with the wrong assumption every correction makes it
twice as bad.

```bash
uv run bedlevel calibrate-direction "vorne links"
```

The command measures, asks you to tighten by a quarter turn, measures again and
reports the value for `cw_lowers_bed`. If you know the direction for certain,
set it directly:

```toml
cw_lowers_bed = true    # tightening lowers the bed (gap to the nozzle grows)
```

## Step 4 — Tram

```bash
uv run bedlevel level
```

Each round:

1. Heat up (first time only), wipe the nozzle, home
2. Measure — 8 probes per point, interleaved across two passes
3. The head moves to the rear and the bed lowers
4. Table with the turn instruction per screw
5. You turn the screws, Enter starts the next round

Done means no correction exceeds the tolerance any more. `q` ends it early.

**What to expect:** the first round brings the biggest jump. From the third
round onwards little tends to move — at that point you have either reached your
target or hit the limit set by bed warp.

## Step 5 — Recreate the bed mesh

After tramming the old mesh is invalid, the bed geometry has changed. On the
printer:

```
BED_MESH_CALIBRATE
SAVE_CONFIG
```

If you consistently only tightened, you lowered the bed overall — set the
**Z offset** again first.

Out of the box the S1 probes 5 × 5 points for this. A finer grid is what makes
residual waviness visible in the first place — see *Optional: a finer bed mesh*
in the README for how to switch to 7 × 7.

## When it is good enough

The output reports **bed warp**: what remains after fitting a plane. That is the
part which is not tilt — waves and warp in the plate itself. Four screws
fundamentally cannot remove it.

If bed warp approaches your configured tolerance, tramming is exhausted.
Turning further only shifts which corner is off. The rest belongs in the bed
mesh — that is exactly what it is for.

A real progression for reference:

| | Range | Bed warp |
|---|---:|---:|
| first warm measurement | `00:23` | — |
| after round 1 | `00:14` | `00:09` |
| after round 2 | `00:11` | `00:01` |
| after round 3 | `00:07` | `00:04` |

The warp figure dropped along with it — the high initial value was not the
plate, but a corner giving way under probing pressure.
