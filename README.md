# Coral Reef Terrain for Stonefish

A ready-made underwater coral reef environment for the [Stonefish](https://github.com/patrykcieslak/stonefish) marine robotics simulator. A 60 × 60 m coral reef seabed with 111 corals and collision meshes, 11.7–16.7 m deep, ready to integrate. This package includes everything needed—no Blender or external tools required.

## Quick Start

Validate the package:
```bash
python3 tools/build_scenario.py check
```

Merge the reef into your existing scenario:
```bash
python3 tools/build_scenario.py merge \
    --into /path/to/my_world.scn \
    -o /path/to/my_world_reef.scn \
    --prefix 'coral_reef/'
```

Preview images are in `docs/`: perspective, close-up, and top-down views.


---

## What You Get

| Aspect | Details |
|--------|---------|
| **Area** | 60 m × 60 m (x, y ∈ [−30, 30] m in NED frame) |
| **Seabed depth** | 11.7 m (reef mound top) to 16.7 m (deepest), reference at 15 m |
| **Corals** | 111 corals built from 33 models: table, staghorn, bush, plate, antler, blue, soft, clathrata, anemone |
| **Zones** | `reef_mound`: 41 dense corals around (2, −3); `patch_or_sand`: 70 scattered on sand |
| **Collision** | Every coral and rock has a collision mesh—vehicles physically collide |
| **Vehicle spawn** | `xyz = −24 24 10` (NED): open sand, no obstacles, seabed at 14.55 m |
| **Performance** | Visual ≈ 4.16 M triangles (0.29 M with `--lowpoly`); physics ≈ 0.18 M triangles |

---

## Package Contents

```
stonefish_coral_reef/
├── README.md                      ← this file
├── scenarios/
│   ├── coral_reef_world.scn         complete scenario, full-detail corals
│   ├── coral_reef_world_lowpoly.scn complete scenario, lightweight (weak GPUs)
│   └── coral_reef_fragment.scn      looks + statics only, for <include>
├── data/coral_reef/               ← copy to Stonefish data directory
│   ├── meshes/terrain/  seabed.obj + seabed_phy.obj
│   ├── meshes/corals/   33 models × 2 (visual + collision)
│   └── textures/sand.png
├── config/reef_layout.json        ← single source of truth (all placements)
├── tools/build_scenario.py        ← build/merge/check scenarios
└── docs/preview_*.png
```

All paths in `.scn` files start with `coral_reef/`. Stonefish resolves them against its data directory, so `data/coral_reef/` must be accessible as `<data_dir>/coral_reef/`.

---

## Integration Guide

### Option A: Run the Reef Standalone (Quickest Test)

1. Copy `data/coral_reef/` into your simulator's data directory:
   ```bash
   cp -r data/coral_reef/ /path/to/simulator/data/
   ```

2. Copy a scenario file:
   ```bash
   cp scenarios/coral_reef_world.scn /path/to/your/scenarios/
   ```

3. Launch with your simulator. Update paths and arguments as needed:

   **stonefish_ros2**:
   ```bash
   ros2 launch stonefish_ros2 stonefish_simulator.launch.py \
     simulation_data:=/abs/path/to/data \
     scenario_desc:=/abs/path/to/coral_reef_world.scn \
     simulation_rate:=100.0 window_res_x:=1280 window_res_y:=800 rendering_quality:=high
   ```

   **stonefish_ros (ROS 1)**:
   ```bash
   roslaunch stonefish_ros simulator.launch \
     simulation_data:=/abs/path/to/data \
     scenario_description:=/abs/path/to/coral_reef_world.scn \
     simulation_rate:=100.0 graphics_resolution:="1280 800" graphics_quality:=high
   ```

   **Plain C++**:
   Pass the data directory containing `coral_reef/` to the app and load `coral_reef_world.scn`.

4. Uncomment the `<include>` at the bottom of the `.scn` file and add your vehicle, spawning at `-24.0 24.0 10.0`.

### Option B: Merge into Your Existing Scenario (Recommended)

This preserves your environment, vehicle, sensors, and materials while adding the reef.

```bash
python3 tools/build_scenario.py merge \
    --into /path/to/my_world.scn \
    -o /path/to/my_world_reef.scn \
    --prefix 'coral_reef/'
```

**Common flags**:

| Flag | Purpose | Example |
|------|---------|---------|
| `--prefix` | Mesh path prefix for your scenario style | `'$(find my_pkg)/data/coral_reef/'` or `'coral_reef/'` |
| `--offset X Y Z` | Move reef (Z is down) | `--offset 0 0 5` sinks it 5 m deeper |
| `--scale K` | Scale reef about seabed reference (0, 0, 15) | `--scale 0.5` gives 30×30 m with half-size corals |
| `--num-corals N` | Keep N largest (below 111) or add extras (above) | `--num-corals 60` or `--num-corals 150` |
| `--lowpoly` | Lightweight visuals (corals use collision mesh) | good for weak GPUs |
| `--zone reef_mound` | Only the dense reef | skip scattered patch corals |
| `--no-corals` | Only terrain | exclude all corals |
| `--seed N` | RNG seed for extra coral placement | `--seed 42` |
| `--name-prefix P` | Namespace all statics/looks/materials | `--name-prefix Reef_` prevents name collisions |

**Important**: Remove or lower any flat seabed plane in your world (e.g., `<static type="plane">` around 15–20 m) so it doesn't cut through the reef.

If you scale the reef (`--scale K`), also scale the vehicle spawn: multiply x and y by K, and compute z as `15 + K·(z − 15)`. The generated file prints the scaled spawn in a header comment.

### Option C: Include the Fragment

Use `scenarios/coral_reef_fragment.scn` if your host scenario supports `<include>`:

1. Add these materials to your scenario's `<materials>` section:
   ```xml
   <material name="ReefRock"  density="3000.0" restitution="0.3"/>
   <material name="ReefCoral" density="1500.0" restitution="0.2"/>
   ```

2. Add the include:
   ```xml
   <include file="path/to/coral_reef_fragment.scn"/>
   ```

   If `<looks>` blocks don't merge properly, use **Option B** instead.

---

## Coordinate Frames

**Stonefish world**: x = north, y = east, z = down (NED), metres and radians.

All OBJ meshes are authored Z-up with the origin at each coral's base. They are flipped into NED with:
- **Terrain**: `rpy = "3.14159 0 0"`, `xyz = "0 0 15"`. Mesh height `h` becomes depth `15 − h`.
- **Corals**: `rpy = "3.14159 0 yaw"`, `xyz = (x, y, z)` from `reef_layout.json`, scaled uniformly.

Mapping: a mesh-authoring point `(x, y, z)` becomes NED `(x, −y, 15 − z)`.

---

## Performance Tuning

### For Weak or Integrated GPUs
Use `--lowpoly` to render corals using their collision meshes:
```bash
python3 tools/build_scenario.py merge --into w.scn -o w_reef.scn --lowpoly
```
Or use the pre-built `coral_reef_world_lowpoly.scn`.

### Reduce Object Count
Keep only the N largest corals:
```bash
python3 tools/build_scenario.py merge --into w.scn -o w_reef.scn --num-corals 40
```

### Add More Corals
Generate extra corals (reusing existing models):
```bash
python3 tools/build_scenario.py merge --into w.scn -o w_reef.scn --num-corals 170
```

### Smaller Reef Relative to Vehicle
Scale everything:
```bash
python3 tools/build_scenario.py merge --into w.scn -o w_reef.scn --scale 0.5
```

### Sparse Reef
Include only the dense mound:
```bash
python3 tools/build_scenario.py merge --into w.scn -o w_reef.scn --zone reef_mound
```

### Terrain Only
Exclude corals:
```bash
python3 tools/build_scenario.py merge --into w.scn -o w_reef.scn --no-corals
```

All options can be combined.

---

## Customisation Without Blender

All coral placements are in `config/reef_layout.json` under `corals[]`. Each entry:

```json
{
  "id": "Coral000",
  "model": "Anemone_A",
  "xyz": [-24.486, -22.1109, 15.0319],
  "yaw": -2.24818,
  "scale": 0.916,
  "footprint_radius_m": 0.481,
  "height_m": 0.422,
  "zone": "patch_or_sand"
}
```

### Edit and Regenerate

- **Move a coral**: update `xyz` (set z to nearby seabed depth, typically 14–16 m).
- **Rotate a coral**: change `yaw`.
- **Delete a coral**: remove the entry.
- **Add a coral**: append an entry with any `model` from `models{}` and a unique `id`.
- **Change colours**: edit `models.<Model>.rgb` or `looks`, then regenerate.

Regenerate with:
```bash
python3 tools/build_scenario.py standalone -o scenarios/coral_reef_world.scn
```

Or use `merge` to apply changes to an existing scenario.

---

## Coral Models

33 models available, sizes at scale 1 (x × y × height):

| Model | Size (m) | Visual tris | Collision tris | Instances |
|-------|----------|-------------|----------------|-----------|
| Anemone_A | 0.90 × 1.05 × 0.46 | 30,000 | 1,502 | 3 |
| Coral_Antler_A–E | 0.49–0.59 × 0.35–0.55 × 0.31–0.39 | ~40k | ~1.5k | 21 total |
| Coral_Blue_A–B | 0.42–0.90 × 0.48–0.83 × 0.38–0.62 | 40,000 | ~1.5k | 8 |
| Coral_Bush_A–E | 0.48–3.08 × 0.55–2.62 × 0.31–1.41 | 13.8k–40k | ~1.5k | 14 |
| Coral_Clathrata_A–C | 0.17–0.47 × 0.21–0.56 × 0.10–0.12 | ~40k | ~1.5k | 23 |
| Coral_Plate_A–H | 0.74–4.33 × 0.60–1.69 × 0.14–0.47 | 37k–40k | ~1.5k | 16 |
| Coral_Soft_A–B | 0.88–0.90 × 0.76–0.80 × 0.66–1.24 | 40,000 | 1,504 | 6 |
| Coral_Staghorn_A–D | 0.91–1.93 × 0.90–2.14 × 0.38–1.17 | 21k–40k | 1,504 | 16 |
| Coral_Table_A–C | 3.38–5.14 × 3.46–4.75 × 1.35–2.10 | 40,000 | 1,500 | 4 |

Corals render as solid colours (averaged from original textures, no UVs applied).

---

## Troubleshooting

| Problem | Cause / Solution |
|---------|-----------------|
| "Could not load mesh" or file not found | Data path must contain `coral_reef/`. Check `ls <data_dir>/coral_reef/meshes/corals/`. Or regenerate with the `--prefix` style your world uses. |
| Reef invisible but vehicle collides | A flat `<static type="plane">` in your world sits above the reef. Remove it or move it below 17 m. |
| Everything upside-down or above water | The roll = π flip is missing. Check `rpy="3.14159 0 …"` on terrain and corals. |
| Low FPS | Use `--lowpoly`, `--num-corals`, or `--zone` flags. |
| Sand texture stretched | Replace `textures/sand.png` with any tileable image of the same size. |
| Vehicle spawns inside terrain | Use a shallower depth (11.8 m on mound, 14.55 m at recommended spawn). |

---

## Verification & Limitations

✓ **Verified**: all 70 mesh files exist; scenarios parse as valid XML; merge preserves comments and structure; coral placements verified numerically (max 0.08 m error from seabed).

✗ **Not verified**: scenarios have not been loaded in a running Stonefish instance. Version-specific details (launch argument names, path resolution) may need tuning (see Integration Guide).

**Limitations**: corals are static (no swaying); solid colours only; no fauna; collision meshes are voxel hulls (gaps < 1/40 of coral size treated as solid).

---

## Model sources and licenses

### Generation process

All 33 coral models were **procedurally generated** from reference images of real coral species. The generation pipeline:

1. **Image acquisition**: reference photographs and photogrammetry scans of actual coral specimens
2. **Procedural generation**: 3D mesh synthesis using parametric coral growth algorithms to recreate morphology (branching patterns, polyp distribution, surface textures)
3. **Optimization**: visual meshes simplifed for rendering; collision meshes voxelized for physics simulation
4. **Validation**: coral sizes, heights, and proportions verified against biological data

This approach ensures models are **structurally and visually representative** of real coral species while remaining lightweight for simulation.

---

## License

[![License: CC BY 4.0](https://img.shields.io/badge/License-CC%20BY%204.0-lightgrey.svg)](https://creativecommons.org/licenses/by/4.0/)

© 2026 Robotics and Machine Intelligence, NIT Tiruchirappalli (RMI NITT).

This package (meshes, textures, scenarios, layout data, tools and documentation) is licensed under the
[Creative Commons Attribution 4.0 International License (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/).

You are free to:

- **Share**: copy and redistribute the material in any medium or format.
- **Adapt**: remix, transform and build upon the material for any purpose, including commercial use.

Under the following terms:

- **Attribution**: you must give appropriate credit, link to the license, and indicate if changes were made. You may do so in any reasonable manner, but not in any way that suggests the licensor endorses you or your use.
- **No additional restrictions**: you may not apply legal terms or technological measures that legally restrict others from doing anything the license permits.

The material is provided "as is", without warranties of any kind. See the [full legal code](https://creativecommons.org/licenses/by/4.0/legalcode) for details.

Stonefish itself is a separate project with its own license; see the [Stonefish repository](https://github.com/patrykcieslak/stonefish).

---

## Attribution

When you use or redistribute this package, or any mesh, texture or scenario derived from it, include a notice such as:

```
Coral Reef Terrain for Stonefish
© 2026 Robotics and Machine Intelligence, NIT Tiruchirappalli (RMI NITT)
Licensed under CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/)
Source: https://github.com/podalanga/stonefish_coral_reef
Changes: <describe your modifications, or "none">
```

For videos, screenshots and demos, a short credit line is enough:

> Coral reef environment: *stonefish_coral_reef* by RMI NITT, [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

---

## Citation

If you use this environment in academic work, please cite it:

```bibtex
@misc{rmi_nitt_stonefish_coral_reef_2026,
  author       = {{Robotics and Machine Intelligence, NIT Tiruchirappalli}},
  title        = {Coral Reef Terrain for Stonefish},
  year         = {2026},
  howpublished = {\url{https://github.com/podalanga/stonefish_coral_reef}},
  note         = {Procedurally generated coral reef environment for the Stonefish simulator. Licensed under CC BY 4.0}
}
```

Please also cite the Stonefish simulator:

```bibtex
@inproceedings{cieslak2019stonefish,
  author    = {Cie{\'s}lak, Patryk},
  title     = {Stonefish: An Advanced Open-Source Simulation Tool Designed for Marine Robotics, With a {ROS} Interface},
  booktitle = {OCEANS 2019 - Marseille},
  year      = {2019},
  pages     = {1--6},
  doi       = {10.1109/OCEANSE.2019.8867434}
}
```
