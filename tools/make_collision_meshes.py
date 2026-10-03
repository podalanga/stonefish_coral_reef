"""Regenerate coral collision meshes (<Model>_phy.obj) from their visual meshes.

Runs inside Blender (tested with 5.2):
  blender -b --python tools/make_collision_meshes.py -- [options]
  flatpak run --filesystem=$PWD org.blender.Blender -b --python $PWD/tools/make_collision_meshes.py -- [options]

Two methods, chosen per model (see VOXEL below):
  decimate  edge-collapse the visual mesh directly to the triangle budget. Keeps thin branches
            connected. Default for clean meshes (antler, bush, staghorn, most plates).
  voxel     voxel-remesh the visual mesh at max_dim / VOXEL[model], then decimate. Used where the
            visual mesh is non-manifold (decimation leaves shards) or is thousands of loose chips
            (decimation cannot reach the budget). Thin plates (SHEETS) are thickened first.
The mesh frame and scale are unchanged, so scenarios need no edits.

Options
  --src DIR        visual meshes (default data/coral_reef/meshes/corals)
  --out DIR        where to write <Model>_phy.obj (default: same as --src)
  --tris N         triangle budget per model (default 3000)
  --only A,B       comma-separated model names to process (default: all)
"""
import argparse, glob, os, sys
import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# model -> voxel divisions along its largest dimension; models not listed use plain decimation
VOXEL = {
    # dense fields of loose blades: a coarse voxel gives a solid envelope (blade gaps are far
    # too small for a vehicle to enter) instead of a shredded carpet
    "Coral_Clathrata_A": 60, "Coral_Clathrata_B": 60, "Coral_Clathrata_C": 60,
    "Coral_Table_A": 60, "Coral_Table_B": 60, "Coral_Table_C": 60,
    # non-manifold visuals where plain decimation leaves shards: fine voxel keeps the plates/branches
    "Coral_Plate_E": 200, "Coral_Plate_F": 200, "Coral_Plate_G": 200,
    "Coral_Soft_A": 200,
}
# thin layered plates: thickened before voxelising, else sheets thinner than a voxel are dropped
SHEETS = {"Coral_Plate_E", "Coral_Plate_F", "Coral_Plate_G"}
# model -> triangle budget overriding --tris (these shard or lose branches at 3000)
TRIS = {"Coral_Plate_E": 6000, "Coral_Soft_A": 6000}


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=os.path.join(ROOT, "data", "coral_reef", "meshes", "corals"))
    ap.add_argument("--out", default=None)
    ap.add_argument("--tris", type=int, default=3000)
    ap.add_argument("--only", default="")
    a = ap.parse_args(argv)
    a.out = a.out or a.src
    return a


def apply(ob, kind, **props):
    m = ob.modifiers.new(kind, kind)
    for k, v in props.items():
        setattr(m, k, v)
    bpy.ops.object.modifier_apply(modifier=m.name)


def make_phy(src, dst, target, voxel_div, thicken):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.wm.obj_import(filepath=src, forward_axis='Y', up_axis='Z')
    ob = bpy.context.selected_objects[0]
    bpy.context.view_layer.objects.active = ob
    if thicken:
        apply(ob, 'SOLIDIFY', thickness=max(ob.dimensions) / 200, offset=0.0)
    if voxel_div:
        apply(ob, 'REMESH', mode='VOXEL', voxel_size=max(ob.dimensions) / voxel_div, adaptivity=0.0)
    else:
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.remove_doubles(threshold=1e-5)
        bpy.ops.object.mode_set(mode='OBJECT')
    apply(ob, 'TRIANGULATE')
    n = len(ob.data.polygons)
    apply(ob, 'DECIMATE', decimate_type='COLLAPSE', ratio=min(1.0, target / n), use_collapse_triangulate=True)
    # decimation can leave wire edges/points; drop them so the OBJ holds only faces
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.delete_loose(use_verts=True, use_edges=True, use_faces=False)
    bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.wm.obj_export(filepath=dst, export_selected_objects=True, forward_axis='Y', up_axis='Z',
                          export_materials=False, export_uv=False, export_normals=True,
                          export_triangulated_mesh=True)
    return n, len(ob.data.polygons)


def main():
    a = parse_args()
    os.makedirs(a.out, exist_ok=True)
    only = set(filter(None, a.only.split(",")))
    for src in sorted(glob.glob(os.path.join(a.src, "*.obj"))):
        name = os.path.basename(src)[:-4]
        if name.endswith("_phy") or (only and name not in only):
            continue
        div = VOXEL.get(name)
        n, k = make_phy(src, os.path.join(a.out, name + "_phy.obj"), TRIS.get(name, a.tris), div, name in SHEETS)
        print(f"PHY {name}: {'voxel 1/%d' % div if div else 'decimate'} {n} -> {k} tris")


main()
