#!/usr/bin/env python3
"""Generate / merge the coral reef terrain into Stonefish scenario (.scn) files.

Python 3.8+ standard library only. No Blender needed.
Source of truth: config/reef_layout.json (NED frame, metres, radians).

Sub-commands
  check       validate the package (files exist, OBJ counts, triangle budget, ASCII map)
  standalone  write a complete scenario (environment + materials + looks + reef)
  fragment    write a <scenario> containing only looks + reef statics, for <include>
  merge       insert materials/looks/statics into an EXISTING scenario file

Common options (standalone/fragment/merge)
  --prefix STR       prepended to every mesh/texture path in the XML (default "coral_reef/")
                     e.g. "coral_reef/" when Stonefish's data dir is <pkg>/data,
                     or "$(find my_pkg)/data/coral_reef/" for stonefish_ros.
  --offset X Y Z     shift the whole reef in the world (NED, metres)
  --max-corals N     keep only the N largest corals (performance)
  --num-corals N     total coral count: fewer than the layout keeps the N largest, more ADDS extra
                     corals (seeded, on the seabed, clear of rocks/spawn/each other); see --seed
  --seed N           RNG seed for the extra corals (default 1; same seed = same reef)
  --scale K          uniformly scale the whole reef by K (terrain, corals, positions) about the
                     seabed reference point (0, 0, 15); K=0.5 halves it, so the ROV looks 2x bigger
  --zone Z           keep only corals in zone Z (reef_mound | patch_or_sand); repeatable
  --lowpoly          use the ~3k-tri collision mesh as the coral VISUAL too (big GPU saving)
  --vivid            saturate the coral colours and pre-compensate them for the red the water absorbs,
                     so corals keep their hue at depth instead of rendering grey-green
                     (same as --saturation 1.8 --min-value 0.65 --colour-gain 5 1.5 1)
  --saturation K     multiply the HSV saturation of every coral colour by K (capped at 0.9)
  --min-value V      raise the HSV value (brightness) of every coral colour to at least V
  --colour-gain R G B  multiply the coral rgb by these factors; values above 1 are allowed and
                     make up for absorption over the light path (red is absorbed first)
  --no-corals        terrain (seabed + rocks) only
  --name-prefix STR  prefix for every static/look/material name (default "")

Examples
  python3 tools/build_scenario.py check
  python3 tools/build_scenario.py standalone -o scenarios/coral_reef_world.scn
  python3 tools/build_scenario.py merge --into my_world.scn -o my_world_reef.scn \
          --prefix '$(find my_pkg)/data/coral_reef/'
"""
import argparse, colorsys, json, math, os, random, sys
import xml.etree.ElementTree as ET
from xml.dom import minidom

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAYOUT = os.path.join(ROOT, "config", "reef_layout.json")
DATA = os.path.join(ROOT, "data", "coral_reef")


def fmt(v):
    s = f"{v:.5f}".rstrip("0").rstrip(".")
    return "0.0" if s in ("-0", "0", "") else (s if "." in s else s + ".0")


def vec(v):
    return " ".join(fmt(x) for x in v)


def load_layout():
    with open(LAYOUT) as f:
        return json.load(f)


def _obj_verts(path):
    with open(path) as f:
        return [tuple(float(t) for t in l.split()[1:4]) for l in f if l.startswith("v ")]


class Seabed:
    """Bilinear height lookup on the regular grid of seabed_phy.obj (mesh frame: Z-up, y = -NED y)."""

    def __init__(self, L):
        v = _obj_verts(os.path.join(DATA, next(t["physical"] for t in L["terrain"] if t["id"] == "Seabed")))
        self.xs = sorted({round(p[0], 4) for p in v})
        self.ys = sorted({round(p[1], 4) for p in v})
        self.h = {(round(p[0], 4), round(p[1], 4)): p[2] for p in v}
        self.ref = L["depth"]["seabed_reference_plane_z"]

    def z_ned(self, x, y_ned):
        y = -y_ned
        def cell(ax, c):
            i = min(max(sum(1 for a in ax if a <= c) - 1, 0), len(ax) - 2)
            return ax[i], ax[i + 1], (c - ax[i]) / (ax[i + 1] - ax[i])
        x0, x1, tx = cell(self.xs, x)
        y0, y1, ty = cell(self.ys, y)
        h = (self.h[x0, y0] * (1 - tx) * (1 - ty) + self.h[x1, y0] * tx * (1 - ty)
             + self.h[x0, y1] * (1 - tx) * ty + self.h[x1, y1] * tx * ty)
        return self.ref - h


def extra_corals(L, base, n, seed, zones):
    """Return n new corals appended to the layout distribution (models, scales, zone mix)."""
    rng = random.Random(seed)
    sb = Seabed(L)
    rocks = [(p[0], -p[1]) for t in L["terrain"] if t["id"] == "Rocks"
             for p in _obj_verts(os.path.join(DATA, t["physical"]))]
    mc = L["reef_mound_centre"]
    mx, my, mr = mc["xyz"][0], mc["xyz"][1], mc["radius_m"]
    spx, spy = L["suggested_vehicle_spawn"]["xyz"][:2]
    lo, hi = L["extent"]["x"][0], L["extent"]["x"][1]
    pool = {}
    for c in L["corals"]:
        pool.setdefault(c["model"], []).append(c["scale"])
    names = sorted(pool)
    weights = [len(pool[m]) for m in names]
    zone_w = {z: sum(1 for c in L["corals"] if c["zone"] == z) for z in ("reef_mound", "patch_or_sand")}
    zl = [z for z in zone_w if not zones or z in zones]
    placed = [(c["xyz"][0], c["xyz"][1], c["footprint_radius_m"]) for c in base]
    out, idx, tries = [], len(L["corals"]), 0
    while len(out) < n and tries < 20000 * max(n, 1):
        tries += 1
        zone = rng.choices(zl, [zone_w[z] for z in zl])[0]
        m = rng.choices(names, weights)[0]
        md = L["models"][m]
        sc = rng.uniform(min(pool[m]), max(pool[m])) if len(pool[m]) > 1 else pool[m][0] * rng.uniform(0.9, 1.1)
        r = max(md["dims_m_at_scale1"][0], md["dims_m_at_scale1"][1]) / 2 * sc
        if zone == "reef_mound":
            d, th = mr * math.sqrt(rng.random()), rng.uniform(0, 2 * math.pi)
            x, y = mx + d * math.cos(th), my + d * math.sin(th)
        else:
            x, y = rng.uniform(lo, hi), rng.uniform(lo, hi)
            if math.hypot(x - mx, y - my) <= mr:
                continue
        if not (lo + 1 + r < x < hi - 1 - r and lo + 1 + r < y < hi - 1 - r):
            continue
        if math.hypot(x - spx, y - spy) < 6 + r:
            continue
        if any(math.hypot(x - px, y - py) < 0.9 * (r + pr) for px, py, pr in placed):
            continue
        if any(math.hypot(x - rx, y - ry) < r + 0.6 for rx, ry in rocks):
            continue
        placed.append((x, y, r))
        out.append({"id": f"Coral{idx:03d}", "model": m, "xyz": [round(x, 4), round(y, 4), round(sb.z_ned(x, y), 4)],
                    "yaw": round(rng.uniform(-math.pi, math.pi), 5), "scale": round(sc, 4),
                    "footprint_radius_m": round(r, 3), "height_m": round(md["dims_m_at_scale1"][2] * sc, 3),
                    "zone": zone})
        idx += 1
    if len(out) < n:
        print(f"warning: only found room for {len(out)} of {n} extra corals", file=sys.stderr)
    return out


def select_corals(L, a):
    if a.no_corals:
        return []
    cs = L["corals"]
    if a.zone:
        cs = [c for c in cs if c["zone"] in a.zone]
    if a.max_corals is not None:
        cs = sorted(cs, key=lambda c: -c["footprint_radius_m"])[: a.max_corals]
    if a.num_corals is not None:
        if a.num_corals < len(cs):
            cs = sorted(cs, key=lambda c: -c["footprint_radius_m"])[: a.num_corals]
        else:
            cs = cs + extra_corals(L, cs, a.num_corals - len(cs), a.seed, a.zone)
    return sorted(cs, key=lambda c: c["id"])


def place(L, a, xyz):
    """Layout-space NED point -> world point: scale about the seabed reference point, then offset."""
    piv = L["depth"]["seabed_reference_plane_z"]
    q = [a.scale * xyz[0], a.scale * xyz[1], piv + a.scale * (xyz[2] - piv)]
    return [q[i] + a.offset[i] for i in range(3)]


# ---------------------------------------------------------------- XML builders
def el(parent, tag, **attrs):
    return ET.SubElement(parent, tag, {k: str(v) for k, v in attrs.items()})


def material_defs(L, np):
    return [(np + n, m) for n, m in L["materials"].items()]


def coral_rgb(rgb, a):
    """Coral colour as written to the scene: saturated, brightened and gained as asked."""
    saturation, min_value, gain = a.saturation, a.min_value, a.colour_gain
    if a.vivid:
        saturation, min_value, gain = saturation or 1.8, min_value or 0.65, gain or [5.0, 1.5, 1.0]
    h, s, v = colorsys.rgb_to_hsv(*rgb)
    rgb = colorsys.hsv_to_rgb(h, min(max(s, 0.9), s * (saturation or 1.0)), max(v, min_value or 0.0))
    return [c * g for c, g in zip(rgb, gain or [1.0, 1.0, 1.0])]


def look_defs(L, corals, a):
    np, pre = a.name_prefix, a.prefix
    out = []
    for n, lk in L["looks"].items():
        attrs = {"name": np + n, "rgb": vec(lk["rgb"]), "roughness": fmt(lk["roughness"])}
        if lk.get("texture"):
            attrs["texture"] = pre + lk["texture"]
        out.append(attrs)
    for m in sorted({c["model"] for c in corals}):
        md = L["models"][m]
        out.append({"name": np + m, "rgb": vec(coral_rgb(md["rgb"], a)), "roughness": "0.85"})
    return out


def add_static(parent, name, visual, physical, material, look, xyz, rpy, scale):
    s = el(parent, "static", name=name, type="model")
    ph = el(s, "physical")
    el(ph, "mesh", filename=physical, scale=fmt(scale))
    el(ph, "origin", rpy="0.0 0.0 0.0", xyz="0.0 0.0 0.0")
    vi = el(s, "visual")
    el(vi, "mesh", filename=visual, scale=fmt(scale))
    el(vi, "origin", rpy="0.0 0.0 0.0", xyz="0.0 0.0 0.0")
    el(s, "material", name=material)
    el(s, "look", name=look)
    el(s, "world_transform", rpy=vec(rpy), xyz=vec(xyz))
    return s


def add_reef_statics(parent, L, corals, a):
    np, pre = a.name_prefix, a.prefix
    parent.append(ET.Comment(" ===== Coral reef terrain (generated by tools/build_scenario.py) ===== "))
    for t in L["terrain"]:
        add_static(parent, np + "Reef" + t["id"], pre + t["visual"], pre + t["physical"],
                   np + t["material"], np + t["look"],
                   place(L, a, t["xyz"]), t["rpy"], t["scale"] * a.scale)
    for c in corals:
        md = L["models"][c["model"]]
        vis = md["physical"] if a.lowpoly else md["visual"]
        add_static(parent, np + c["id"] + "_" + c["model"].replace("Coral_", ""),
                   pre + vis, pre + md["physical"], np + "ReefCoral", np + c["model"],
                   place(L, a, c["xyz"]), [math.pi, 0.0, c["yaw"]], c["scale"] * a.scale)


def pretty(root):
    raw = ET.tostring(root, encoding="unicode")
    txt = minidom.parseString(raw).toprettyxml(indent="\t")
    return "\n".join(l for l in txt.splitlines() if l.strip()) + "\n"


def header(L, a, corals):
    sp = place(L, a, L["suggested_vehicle_spawn"]["xyz"])
    d = L["depth"]
    zs = [place(L, a, [0, 0, d[k]])[2] for k in ("shallowest_seabed_z", "deepest_seabed_z")]
    rc = place(L, a, L["reef_mound_centre"]["xyz"])
    return (f"<!-- Coral reef terrain for Stonefish ({len(corals)} corals{'' if a.scale == 1 else ', scale ' + fmt(a.scale)}). Generated by tools/build_scenario.py.\n"
            f"     Frame NED (z down). Seabed depth {zs[0]:.1f}-{zs[1]:.1f} m. Reef centre ~({rc[0]:.0f}, {rc[1]:.0f}).\n"
            f"     Mesh/texture paths are prefixed with '{a.prefix}' (resolved against the Stonefish data directory\n"
            f"     unless absolute / $(find ...)). Suggested vehicle spawn xyz = {vec(sp)} -->\n")


# ---------------------------------------------------------------- commands
def cmd_standalone(L, a):
    corals = select_corals(L, a)
    np = a.name_prefix
    root = ET.Element("scenario")
    env = el(root, "environment")
    el(env, "ned", latitude="10.5", longitude="72.6")
    oc = el(env, "ocean")
    el(oc, "water", density="1025.0", jerlov="0.2")
    el(oc, "waves", height="0.0")
    el(oc, "particles", enabled="true")
    cur = el(oc, "current", type="uniform")
    el(cur, "velocity", xyz="0.0 0.0 0.0")
    at = el(env, "atmosphere")
    el(at, "sun", azimuth="20.0", elevation="60.0")
    mats = el(root, "materials")
    el(mats, "material", name="Neutral", density="1000.0", restitution="0.5")
    for n, m in material_defs(L, np):
        el(mats, "material", name=n, density=fmt(m["density"]), restitution=fmt(m["restitution"]))
    looks = el(root, "looks")
    for attrs in look_defs(L, corals, a):
        el(looks, "look", **attrs)
    add_reef_statics(root, L, corals, a)
    sp = place(L, a, L["suggested_vehicle_spawn"]["xyz"])
    root.append(ET.Comment(
        " ===== Add your vehicle here, e.g.\n\t<include file=\"path/to/my_rov.scn\">\n"
        f"\t\t<arg name=\"position\" value=\"{vec(sp)}\"/>\n\t</include>\n\t(argument names depend on your vehicle file) "))
    write(a.output, '<?xml version="1.0"?>\n' + header(L, a, corals) + pretty(root).split("\n", 1)[1])
    print(f"wrote {a.output}: {len(corals)} corals")


def cmd_fragment(L, a):
    corals = select_corals(L, a)
    root = ET.Element("scenario")
    root.append(ET.Comment(" Requires materials " + a.name_prefix + "ReefRock and " + a.name_prefix +
                           "ReefCoral in the including scenario. See CLAUDE.md. "))
    looks = el(root, "looks")
    for attrs in look_defs(L, corals, a):
        el(looks, "look", **attrs)
    add_reef_statics(root, L, corals, a)
    write(a.output, '<?xml version="1.0"?>\n' + header(L, a, corals) + pretty(root).split("\n", 1)[1])
    print(f"wrote {a.output}: {len(corals)} corals (fragment)")


def cmd_merge(L, a):
    corals = select_corals(L, a)
    np = a.name_prefix
    tree = ET.parse(a.into, parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True)))
    root = tree.getroot()
    if root.tag != "scenario":
        sys.exit(f"{a.into}: root element is <{root.tag}>, expected <scenario>")
    # static-name collisions
    existing = {s.get("name") for s in root.iter("static")}
    wanted = {np + "Reef" + t["id"] for t in L["terrain"]} | {np + c["id"] + "_" + c["model"].replace("Coral_", "") for c in corals}
    clash = existing & wanted
    if clash:
        sys.exit(f"name collision with existing statics: {sorted(clash)[:5]}... use --name-prefix")
    # materials
    mats = root.find("materials")
    if mats is None:
        mats = el(root, "materials")
    have = [m.get("name") for m in mats.findall("material")]
    added = []
    for n, m in material_defs(L, np):
        if n not in have:
            mat = ET.Element("material", {"name": n, "density": fmt(m["density"]), "restitution": fmt(m["restitution"])})
            mats.append(mat)
            added.append(n)
    # looks
    looks = root.find("looks")
    if looks is None:
        looks = ET.Element("looks")
        root.insert(list(root).index(mats) + 1, looks)
    lh = {l.get("name") for l in looks.findall("look")}
    nl = 0
    for attrs in look_defs(L, corals, a):
        if attrs["name"] not in lh:
            el(looks, "look", **attrs)
            nl += 1
    add_reef_statics(root, L, corals, a)
    ET.indent(tree, space="\t") if hasattr(ET, "indent") else None
    out = ET.tostring(root, encoding="unicode")
    write(a.output, '<?xml version="1.0"?>\n' + out + "\n")
    print(f"wrote {a.output}: +{len(added)} materials {added}, +{nl} looks, "
          f"+{len(L['terrain'])} terrain statics, +{len(corals)} corals")


def cmd_check(L, a):
    ok = True
    files = {t["visual"] for t in L["terrain"]} | {t["physical"] for t in L["terrain"]}
    files |= {m["visual"] for m in L["models"].values()} | {m["physical"] for m in L["models"].values()}
    files |= {lk["texture"] for lk in L["looks"].values() if lk.get("texture")}
    for f in sorted(files):
        p = os.path.join(DATA, f)
        if not os.path.isfile(p):
            print("MISSING", p)
            ok = False
    unknown = {c["model"] for c in L["corals"]} - set(L["models"])
    if unknown:
        print("corals reference unknown models:", unknown)
        ok = False
    for f in sorted(x for x in files if x.endswith(".obj")):
        nf = 0
        with open(os.path.join(DATA, f)) as fh:
            for line in fh:
                if line.startswith("f "):
                    nf += 1
                    if len(line.split()) != 4:
                        print("non-triangle face in", f)
                        ok = False
                        break
        if nf == 0:
            print("no faces in", f)
            ok = False
    vis = sum(t["visual_tris"] for t in L["terrain"]) + sum(L["models"][c["model"]]["visual_tris"] for c in L["corals"])
    phy = sum(t["physical_tris"] for t in L["terrain"]) + sum(L["models"][c["model"]]["physical_tris"] for c in L["corals"])
    low = sum(t["visual_tris"] for t in L["terrain"]) + sum(L["models"][c["model"]]["physical_tris"] for c in L["corals"])
    print(f"{len(files)} files OK" if ok else "PROBLEMS FOUND")
    print(f"{len(L['corals'])} corals / {len(L['models'])} models | visual tris {vis:,} (with --lowpoly {low:,}) | physics tris {phy:,}")
    # ASCII map, north (+x) up, east (+y) right
    W, H = 60, 30
    g = [["." for _ in range(W)] for _ in range(H)]
    for c in L["corals"]:
        x, y = c["xyz"][0], c["xyz"][1]
        r, col = int((30 - x) / 60 * (H - 1) + 0.5), int((y + 30) / 60 * (W - 1) + 0.5)
        if 0 <= r < H and 0 <= col < W:
            g[r][col] = "#" if c["footprint_radius_m"] > 1.2 else ("o" if c["footprint_radius_m"] > 0.5 else "*")
    sx, sy = L["suggested_vehicle_spawn"]["xyz"][:2]
    g[int((30 - sx) / 60 * (H - 1) + 0.5)][int((sy + 30) / 60 * (W - 1) + 0.5)] = "S"
    print("map (N up, E right, 60x60 m): # large  o medium  * small  S spawn")
    print("\n".join("".join(row) for row in g))
    sys.exit(0 if ok else 1)


def write(path, txt):
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(txt)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    for name in ("standalone", "fragment", "merge"):
        p = sub.add_parser(name)
        p.add_argument("-o", "--output", required=True)
        if name == "merge":
            p.add_argument("--into", required=True, help="existing scenario to merge into (not modified)")
        p.add_argument("--prefix", default="coral_reef/")
        p.add_argument("--offset", nargs=3, type=float, default=[0.0, 0.0, 0.0], metavar=("X", "Y", "Z"))
        p.add_argument("--max-corals", type=int)
        p.add_argument("--num-corals", type=int, help="total corals; more than the layout adds extras")
        p.add_argument("--seed", type=int, default=1, help="RNG seed for extra corals")
        p.add_argument("--scale", type=float, default=1.0, help="uniform reef scale factor (default 1.0)")
        p.add_argument("--zone", action="append", choices=["reef_mound", "patch_or_sand"])
        p.add_argument("--lowpoly", action="store_true")
        p.add_argument("--vivid", action="store_true",
                       help="saturated, absorption-compensated coral colours (keeps hue at depth)")
        p.add_argument("--saturation", type=float)
        p.add_argument("--min-value", type=float)
        p.add_argument("--colour-gain", nargs=3, type=float, metavar=("R", "G", "B"))
        p.add_argument("--no-corals", action="store_true")
        p.add_argument("--name-prefix", default="")
    a = ap.parse_args()
    L = load_layout()
    {"check": cmd_check, "standalone": cmd_standalone, "fragment": cmd_fragment, "merge": cmd_merge}[a.cmd](L, a)


if __name__ == "__main__":
    main()
