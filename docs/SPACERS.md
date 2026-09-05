# Spacers

*[Deutsche Fassung: SPACERS.de.md](SPACERS.de.md)*

> **Least tested part of this project.** The generator was written *after*
> spacers were already fitted to the test machine, so the full sequence
> — measure the baseline, print, install — has never been run end to end.
> The maths and the STL geometry are covered by tests; the practical workflow
> is not. Treat it as a well-founded proposal, not a proven recipe.

The Kobra S1 ships **without** spacers — the bed rests directly on its carrier.
The factory offset of the four mounting points therefore has to be taken up
entirely by the screws: one corner works permanently near its limit while
another has almost no preload.

That is exactly where the measurement problems from
[MEASUREMENT.md](MEASUREMENT.md) come from — a corner giving way under probing
pressure, or latching between two levels.

Printed spacers take the offset out beforehand. The lowest corner gets the
tallest spacer, the others correspondingly shorter ones. Afterwards all four
screws operate in the same range and fine adjustment has room in both
directions.

## Prerequisites

What gets measured is the **baseline**, not an already compensated state.
Otherwise an existing compensation is measured along and then applied twice.

1. **Either no spacers fitted, or the same height at all four points.** A set of
   equally tall reference spacers is ideal — it holds the bed at working height
   without distorting the offset.
2. **All four screws tightened evenly**, none at its limit. The same number of
   turns from first contact is a usable measure.
3. **Build plate seated flat**, contact surfaces and magnetic base clean.

The command asks about these before measuring.

## Sequence

```bash
uv run bedlevel spacers
```

1. Prompt about the prerequisites (skip with `--yes`)
2. Heat up, wipe the nozzle, home
3. Measure with interleaved passes, 8 readings per point
4. Check that the measurement holds — with two levels or drift it **aborts**
   rather than casting the error into hardware
5. Compute heights, write STL files to `spacers/`
6. `spacers/aufmass.json` with all individual readings for traceability

`--dry-run` only computes and writes nothing.

## Calculation

A low mounting point needs more material. The lowest corner gets the full build
height, every other one is shortened by how far it sits above it:

```
height_i = max_height − (z_i − z_min) / (1 − compression)
```

Example with `max_height = 10.5`:

| Point | measured | above lowest | spacer height |
|---|---:|---:|---:|
| front left | −0.780 | +0.000 | **10.50 mm** (tallest) |
| front right | −0.520 | +0.260 | 10.24 mm |
| rear right | −0.610 | +0.170 | 10.33 mm |
| rear left | −0.655 | +0.125 | 10.38 mm |

If a point works out to a height ≤ 0 the command aborts: `max_height` is then
smaller than the offset and needs raising.

## Geometry

| | |
|---|---|
| Outer diameter | 8.74 mm |
| Inner diameter | 4.30 mm (M4 with clearance) |
| Ring wall | 2.22 mm |
| Tallest spacer | 10.50 mm |
| Volume (10.5 mm) | 477 mm³ |

All values live under `[spacer]` in `bedlevel.toml` and can be adapted to other
mounts. `segments` controls the circumferential resolution; 128 gives about
0.2 mm chord length at 8.74 mm.

The generated mesh is watertight and verified against the analytical volume
formula (0.04 % deviation at 128 segments — pure polygon approximation of the
circle).

## Print parameters

| | |
|---|---|
| Material | TPU 95A |
| Wall lines | 1 |
| Infill | 10 % gyroid |
| Speed | 15–25 mm/s |
| Support | none needed |

**Why so little material:** the ring wall is 2.22 mm wide. With a 0.4 mm nozzle,
one outer and one inner line leave roughly 1.4 mm for the gyroid. That turns the
spacer into a **spring** which holds the preload instead of blocking it. A
solidly printed spacer would be a rigid block and would defeat the screw
adjustment.

**Print all four in a single job.** Same nozzle temperature, same layer time,
same cooling — printed separately their spring rates differ and the
compensation no longer holds.

100 % bottom layer, no bridges needed (plain tube geometry). Keep retraction low
for TPU, direct drive preferred.

Files are named by point and height, e.g.
`spacer_hinten_links_10.50mm.stl` — do not mix them up on installation.

## Installation

1. Match spacers to points (by file name), remove the bed, place the spacers.
2. Tighten the screws evenly, all in the same range.
3. Only then fine-adjust: `uv run bedlevel level`.

The spacers provide the coarse correction, the screws the rest. Some residual
deviation after installation is normal — but it should be much smaller than
before, and above all all four screws should be driven in comparably far.

## Settling and follow-up correction

TPU at 10 % infill gives way under preload, and not evenly: a tall spacer is
compressed more than a short one, so the installed height difference comes out
smaller than the printed one.

Procedure: after installation let it go through a few heat cycles, then run
`uv run bedlevel measure`. If a systematic residual deviation remains in the
same direction as the original offset, compression was the cause. Then estimate
`compression` (residual deviation divided by original offset) and print a second
set.

For the first set leave `compression = 0` — before that the value cannot be
estimated seriously.
