# Measurement quality, notation and tolerance

*[Deutsche Fassung: MEASUREMENT.de.md](MEASUREMENT.de.md)*

## Reading the turn instruction

The notation follows Klipper's `SCREWS_TILT_ADJUST`:

```
adjust  CW 01:20     one full turn plus 20 minutes, clockwise
```

The clock face as a measure of rotation:

| Display | Rotation | with M4 (0.7 mm pitch) |
|---|---|---:|
| `01:00` | full turn, 360° | 0.700 mm |
| `00:30` | half turn, 180° | 0.350 mm |
| `00:15` | quarter turn, 90° | 0.175 mm |
| `00:05` | small nudge, 30° | 0.058 mm |

`CW` = clockwise, `CCW` = counter-clockwise. With a right-hand thread `CW` is
always tightening — the legend below the table also states which way the bed
moves. The reference screw shows as `(base)`.

**Parentheses mean: not required, but effective.** A correction in parentheses
is within tolerance. This matters when several screws sit just below the limit:
if you only turn the one that exceeds it, another becomes the new highest
corner and the range stays where it was.

## Tolerance

It is given in the same unit as the instruction (`tolerance_minutes`), so that
the stopping criterion matches the number in the `adjust` column.

| Target | Meaning |
|---|---|
| below `00:10` | **good** — fine for everyday printing, the mesh handles the rest |
| below `00:05` | **excellent** — when the bed should sit as stress-free as possible |
| below `00:02` | **limit of mechanical play** in screws and mounts |

**All measurement-quality warnings are relative to this value.** What counts as
a problem depends on the target: a drift of one minute is an eighth of the
tolerance at `00:10` and irrelevant, but half the tolerance at `00:02`.

## Reference screw

One screw stays put and the others are aligned to it. `reference` controls
which:

| Value | Meaning |
|---|---|
| `nur-anziehen` | picks the corner such that **no** screw needs loosening |
| `auto` | least total turning — may require loosening |
| `<name>` | exactly this screw |

`nur-anziehen` ("tighten only") is the default: tightening holds the preload of
the mounts better than backing out. Which corner that is, the tool derives from
`cw_lowers_bed` — if tightening lowers the bed it is the lowest corner,
otherwise the highest.

The choice is made **fresh on every round**. That is the difference from a fixed
screw: if you overshoot while tightening and that corner ends up below the
reference, the reference moves with it — and you keep tightening instead of
having to loosen.

## Measuring order

Points are not measured one at a time but interleaved across two passes —
crosswise, with the second pass reversed:

```
Pass 1:  front left → rear right → front right → rear left
Pass 2:  rear left → front right → rear right → front left
```

The reason: the bed sinks by a measurable 0.01–0.02 mm during a measuring run.
Measured sequentially, the point probed last would appear systematically lower —
a pure *time* effect would turn into *phantom tilt*. With the reversed pass the
temporal centre of gravity of every corner lies in the middle of the whole run,
so a uniform time trend cancels out mathematically.

Simulated on a perfectly flat bed that gives way by 0.002 mm per probe:

| Passes | Phantom tilt |
|---|---:|
| 1 (sequential) | 0.054 mm = `00:05` |
| 2 (interleaved) | 0.000 mm |

The crosswise pattern within a pass serves its own purpose: adjacent corners
are never loaded back to back, so each spot gets time to recover.

## When the measurement does not hold

Eight readings are taken per point and the median is used. The tool
distinguishes three failure modes, because they have different consequences:

| Pattern | Example | Meaning |
|---|---|---|
| **Scatter** | `-0.425 -0.432 -0.421` | noise — the median averages it out |
| **Drift** | `-0.437 → -0.462 → -0.480` | directional, does **not** average out |
| **Two levels** | `-0.520 -0.696 -0.518 -0.698` | the mount latches between two positions |

### Drift

Readings run monotonically in one direction. The mount gives way under probing
pressure, or the bed settles. More readings do not help — they only push the
corner down further.

### Two levels

The most dangerous case, because it looks like ordinary scatter. Readings jump
between two groups, and **the median lands in the gap between them**, describing
a position the bed never occupies. A real case:

```
-0.5358  -0.6667  -0.5200  -0.6958  -0.5175  -0.6983  -0.5258  -0.7075
    A        B        A        B        A        B        A        B
```

Median: −0.601 — a value that appears in neither level. Most common cause: the
build plate is not seated flat.

### What the tool does about it

For drift or two levels it gives **no** turn instruction for the affected point
and does not select it as reference — a correction based on it would be computed
against a phantom value. Instead the reason appears in the table, along with a
note that tramming is not possible this way.

### Checking a single point

```bash
uv run bedlevel stability "vorne links"
```

Probes the point ten times and reports scatter and drift separately, each
relative to the configured tolerance.

**The sensor is rarely the problem.** On sound corners it delivers 6–17 µm
repeatability. If a single point scatters far more than the others in the same
run, the cause there is mechanical — same nozzle, same sensor, same run.

## Output metrics

- **Größte Korrektur** (largest correction) — the biggest turn needed, with a
  rating.
- **Spannweite** (range) — difference between highest and lowest corner.
- **Verkippung** (tilt) — slope of the fitted plane in mm/m, split by X and Y.
- **Bettverzug** (bed warp) — what remains after fitting a plane. The
  achievable floor; if it approaches your tolerance, further turning is not
  worth it.
