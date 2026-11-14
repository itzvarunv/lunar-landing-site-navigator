# -*- coding: utf-8 -*-
"""
4:1 BLOCK-AND-TACKLE SIMULATOR  (Blender 4.x, pure bpy, 100% procedural)
=======================================================================
Engineering-physics teaching scene: two fixed + two movable steel pulleys,
continuous tan rope, live N-panel with telemetry, presets, CSV export and an
auto-running presentation mode.

IMPORTANT (honest note on the physics):
  Motion is KINEMATIC RIGGING, not a soft-body / cloth / rigid-body simulation.
  The rope is a poly curve whose control points are recomputed analytically
  (straight strands + circular arcs on the pulley grooves) every time the rope
  displacement d changes.  Lift h = d / IMA and the pulley angles follow from
  rope-length conservation (derivation is in the comments of apply_rig()).

Run:  Scripting workspace -> Text Editor -> Open/paste -> Run Script (Alt+P).
Then in the 3D viewport press N and open the "Block & Tackle" tab.
"""

bl_info = {
    "name": "Block & Tackle Simulator (4:1)",
    "author": "Generated for BTech Engineering Physics",
    "version": (1, 0, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar (N) > Block & Tackle",
    "description": "Procedural 4:1 pulley system with live physics telemetry",
    "category": "Education",
}

import bpy
import bmesh
import csv
import os
import textwrap
from math import pi, sin, cos, radians
from bpy.app.handlers import persistent
from bpy.props import (BoolProperty, EnumProperty, FloatProperty, IntProperty,
                       PointerProperty, StringProperty)
from mathutils import Matrix, Vector

# ----------------------------------------------------------------------------
# 0. CONSTANTS  (metres, Blender Z is up, rope plane is XZ at y = 0)
# ----------------------------------------------------------------------------
COLL_NAME = "BT_Block_Tackle"
_NS_KEY = "BT_BLOCK_TACKLE_UNREGISTER"

IMA = 4                      # number of rope strands supporting the movable block
R_ROPE = 0.30                # rope centre-line radius on every pulley
ROPE_R = 0.022               # rope radius
# Five vertical rope strands (anchor side -> free end).  Spacing = 2*R_ROPE so
# every strand is exactly tangent to its pulleys and no strand touches another.
XS = (1.2, 0.6, 0.0, -0.6, -1.2)

# key: (centre x, movable?, k = angular-rate multiple of h/R, sign: +1 clockwise
# in the front view (x right, z up) = +rotation about Y, -1 counter-clockwise)
PULLEYS = {
    "MR": dict(x=0.9,  movable=True,  k=1, sign=+1, name="Right movable"),
    "FR": dict(x=0.3,  movable=False, k=2, sign=-1, name="Right fixed"),
    "ML": dict(x=-0.3, movable=True,  k=3, sign=+1, name="Left movable"),
    "FL": dict(x=-0.9, movable=False, k=4, sign=-1, name="Left fixed"),
}
ZF = 5.2                     # fixed pulley centre height
ZM0 = 1.55                   # movable pulley centre height at h = 0
Z_ANCHOR = 5.95              # rope anchor (inside the clamp under the beam)
Z_END0 = 3.2                 # free rope end height at d = 0
H_MAX = 0.75                 # maximum lift (m)  -> keeps rope end above the floor
D_MAX = IMA * H_MAX          # maximum rope displacement (m)
ARC_N = 28                   # samples per 180-degree rope arc
BLOCK_CX = 0.3               # x of lower block centre (centroid of 4 strands)
HOOK_DX = 0.1                # hook bowl offset -> load is centred at BLOCK_CX+HOOK_DX
ARROW_K = 0.0011             # arrow length per newton (m/N), clamped below
ARROW_MIN, ARROW_MAX = 0.25, 2.2
TICK = 1.0 / 30.0

COLL = None  # set in build_scene()


# ----------------------------------------------------------------------------
# 1. PHYSICS ENGINE  (exact formulas required by the brief)
# ----------------------------------------------------------------------------
def calc_state(W, eff_pct, d):
    """All theoretical quantities for load W [N], efficiency [%], rope pull d [m]."""
    eta = max(eff_pct, 1e-6) / 100.0
    h = d / IMA                      # d = IMA x h  ->  h = d / IMA
    f_ideal = W / IMA                # F_ideal = W / IMA
    ama = IMA * eta                  # AMA = IMA x efficiency
    f_actual = W / ama               # F_actual = W / AMA
    w_out = W * h                    # W_out = W x h
    w_in = f_actual * d              # W_in  = F x d
    eff_meas = (w_out / w_in * 100.0) if w_in > 1e-12 else eff_pct
    return dict(W=W, d=d, h=h, IMA=IMA, AMA=ama, F_ideal=f_ideal,
                F_actual=f_actual, W_out=w_out, W_in=w_in,
                eff=eff_meas, loss=w_in - w_out)


# ----------------------------------------------------------------------------
# 2. ROPE KINEMATICS
# ----------------------------------------------------------------------------
def _arc(cx, cz, phi0, phi1, n=ARC_N):
    return [(cx + R_ROPE * cos(phi0 + (phi1 - phi0) * i / n), 0.0,
             cz + R_ROPE * sin(phi0 + (phi1 - phi0) * i / n)) for i in range(n + 1)]


def rope_points(h, d):
    """Polyline of the rope centre-line for lift h and pull d.
    Anchor -> down & under MR (CW) -> up & over FR (CCW) -> down & under ML (CW)
    -> up & over FL (CCW) -> free end hanging on the left."""
    zm = ZM0 + h
    pts = [(XS[0], 0.0, Z_ANCHOR)]
    pts += _arc(PULLEYS["MR"]["x"], zm, 0.0, -pi)
    pts += _arc(PULLEYS["FR"]["x"], ZF, 0.0, pi)
    pts += _arc(PULLEYS["ML"]["x"], zm, 0.0, -pi)
    pts += _arc(PULLEYS["FL"]["x"], ZF, 0.0, pi)
    pts.append((XS[4], 0.0, Z_END0 - d))
    return pts


def _poly_length(pts):
    return sum((Vector(pts[i + 1]) - Vector(pts[i])).length for i in range(len(pts) - 1))


def _selftest():
    """Rope length must be constant when d = IMA*h (inextensible rope)."""
    base = _poly_length(rope_points(0.0, 0.0))
    for h in (0.1, 0.25, 0.5, 0.75):
        # polyline length of arcs is constant; strands change by -4h + d
        diff = abs(_poly_length(rope_points(h, IMA * h)) - base)
        # mathutils.Vector stores coordinates at single precision in Blender, so
        # summing many sampled rope segments can accumulate ~1e-7 m of rounding.
        # This tolerance is small compared with the model dimensions but robust.
        assert diff < 1e-5, "Rope length not conserved (%g)" % diff
    s = calc_state(500.0, 80.0, 2.0)
    assert abs(s["F_ideal"] - 125.0) < 1e-9 and abs(s["F_actual"] - 156.25) < 1e-9
    assert abs(s["W_out"] - 250.0) < 1e-9 and abs(s["W_in"] - 312.5) < 1e-9
    assert abs(s["eff"] - 80.0) < 1e-9
    print("[BlockTackle] self-test passed: rope length conserved, Case 1 numbers verified.")


# ----------------------------------------------------------------------------
# 3. PROCEDURAL MESH HELPERS (bmesh only - no bpy.ops, no external files)
# ----------------------------------------------------------------------------
def finish_bm(bm, deg=35.0):
    """Smooth-shade everything but keep hard edges where faces meet > deg."""
    thr = radians(deg)
    for f in bm.faces:
        f.smooth = True
    for e in bm.edges:
        if len(e.link_faces) == 2 and e.calc_face_angle(0.0) > thr:
            e.smooth = False


def bm_box(bm, center, size):
    m = Matrix.Translation(center) @ Matrix.Diagonal(Vector((size[0], size[1], size[2], 1.0)))
    bmesh.ops.create_cube(bm, size=1.0, matrix=m)


def bm_cyl(bm, center, radius, length, axis="Z", segments=32):
    rot = {"X": Matrix.Rotation(pi / 2, 4, "Y"),
           "Y": Matrix.Rotation(pi / 2, 4, "X"),
           "Z": Matrix.Identity(4)}[axis]
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=segments,
                          radius1=radius, radius2=radius, depth=length,
                          matrix=Matrix.Translation(center) @ rot)


def bm_sphere(bm, center, radius):
    bmesh.ops.create_uvsphere(bm, u_segments=24, v_segments=12, radius=radius,
                              matrix=Matrix.Translation(center))


def bm_lathe(bm, profile, segs=96):
    """Revolve a CLOSED (r, y) profile around the local Y axis."""
    rings = []
    for (r, y) in profile:
        rings.append([bm.verts.new((r * cos(2 * pi * j / segs), y, r * sin(2 * pi * j / segs)))
                      for j in range(segs)])
    faces = []
    n = len(profile)
    for i in range(n):
        a, b = rings[i], rings[(i + 1) % n]
        for j in range(segs):
            j2 = (j + 1) % segs
            faces.append(bm.faces.new((a[j], a[j2], b[j2], b[j])))
    bmesh.ops.recalc_face_normals(bm, faces=faces)
    return faces


def torus_profile(major, minor, n=16):
    return [(major + minor * cos(2 * pi * i / n), minor * sin(2 * pi * i / n)) for i in range(n)]


def mesh_from_bm(name, bm, mats=()):
    finish_bm(bm)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    for m in mats:
        me.materials.append(m)
    if hasattr(me, "use_auto_smooth"):           # Blender 4.0 only (removed in 4.1)
        try:
            me.use_auto_smooth = True
            me.auto_smooth_angle = radians(35)
        except Exception:
            pass
    return me


def add_obj(name, data, loc=(0, 0, 0), rot=(0, 0, 0), parent=None):
    ob = bpy.data.objects.new(name, data)
    COLL.objects.link(ob)
    ob.location = loc
    ob.rotation_euler = rot
    if parent is not None:
        ob.parent = parent
    return ob


def add_bevel(ob, width, seg=3):
    m = ob.modifiers.new("Bevel", "BEVEL")
    m.width = width
    m.segments = seg
    m.limit_method = "ANGLE"
    m.angle_limit = radians(30)
    try:
        m.harden_normals = True
    except Exception:
        pass


def add_text(name, body, size, loc, mat, parent=None, align="CENTER", extrude=0.012):
    """Text uses Blender's built-in font (no external font file)."""
    cu = bpy.data.curves.new(name, "FONT")
    cu.body = body
    cu.size = size
    cu.align_x = align
    cu.align_y = "CENTER"
    cu.extrude = extrude
    cu.materials.append(mat)
    ob = bpy.data.objects.new(name, cu)
    COLL.objects.link(ob)
    ob.location = loc
    ob.rotation_euler = (pi / 2, 0.0, 0.0)       # stand upright, readable from -Y camera
    if parent is not None:
        ob.parent = parent
    return ob


# ----------------------------------------------------------------------------
# 4. MATERIALS (Principled BSDF)
# ----------------------------------------------------------------------------
def _sock(bsdf, names, value):
    for n in names:
        if n in bsdf.inputs:
            bsdf.inputs[n].default_value = value
            return True
    return False


def make_mat(name, color, metallic=0.0, rough=0.5, coat=0.0, emit=None, bump=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    _sock(bsdf, ("Base Color",), (color[0], color[1], color[2], 1.0))
    _sock(bsdf, ("Metallic",), metallic)
    _sock(bsdf, ("Roughness",), rough)
    if coat > 0:
        _sock(bsdf, ("Coat Weight", "Clearcoat"), coat)      # 4.x / 3.x names
    if emit is not None:
        _sock(bsdf, ("Emission Color", "Emission"), (emit[0], emit[1], emit[2], 1.0))
        _sock(bsdf, ("Emission Strength",), emit[3])
    if bump > 0:                                               # subtle rope fibres
        try:
            tex = nt.nodes.new("ShaderNodeTexNoise")
            tex.inputs["Scale"].default_value = 140.0
            tex.inputs["Detail"].default_value = 6.0
            bp = nt.nodes.new("ShaderNodeBump")
            bp.inputs["Strength"].default_value = bump
            nt.links.new(tex.outputs["Fac"], bp.inputs["Height"])
            nt.links.new(bp.outputs["Normal"], bsdf.inputs["Normal"])
        except Exception:
            pass
    return m


# ----------------------------------------------------------------------------
# 5. SCENE CONSTRUCTION
# ----------------------------------------------------------------------------
def _purge_previous():
    old = bpy.data.collections.get(COLL_NAME)
    if old is not None:
        for ob in list(old.objects):
            bpy.data.objects.remove(ob, do_unlink=True)
        bpy.data.collections.remove(old)
    for pool in (bpy.data.meshes, bpy.data.curves, bpy.data.materials,
                 bpy.data.lights, bpy.data.cameras, bpy.data.worlds):
        for dat in list(pool):
            if dat.name.startswith("BT_"):
                pool.remove(dat)


def _pulley_mesh(mats):
    t, rf, rg = 0.075, 0.36, 0.275
    prof = [(0.045, -t), (0.34, -t), (rf, -0.055), (rf, -0.05), (rg, -0.028), (rg, 0.028),
            (rf, 0.05), (rf, 0.055), (0.34, t), (0.045, t)]
    bm = bmesh.new()
    bm_lathe(bm, prof, 96)
    # Dark radial ribs on both faces so the rotation is clearly visible.
    for k in range(6):
        ang = k * pi / 3
        for side in (-1, 1):
            m = (Matrix.Rotation(ang, 4, "Y") @ Matrix.Translation((0.145, side * 0.0745, 0.0))
                 @ Matrix.Diagonal(Vector((0.19, 0.012, 0.03, 1.0))))
            res = bmesh.ops.create_cube(bm, size=1.0, matrix=m)
            for f in {f for v in res["verts"] for f in v.link_faces}:
                f.material_index = 1
    return mesh_from_bm("BT_PulleyMesh", bm, mats)


def _make_arrow(tag, parent, loc, mat_arrow, mat_label, label, value_align):
    root = bpy.data.objects.new("BT_Arrow_%s" % tag, None)
    root.empty_display_type = "PLAIN_AXES"
    root.empty_display_size = 0.05
    COLL.objects.link(root)
    root.parent = parent
    root.location = loc
    bm = bmesh.new()
    bm_cyl(bm, (0, 0, 0), 0.035, 1.0, "Z", 24)               # unit shaft, scaled in Z later
    add_obj("BT_Arrow_%s_Shaft" % tag, mesh_from_bm("BT_ArrowShaft_%s" % tag, bm, [mat_arrow]), parent=root)
    bm = bmesh.new()                                          # cone, apex pointing down (-Z)
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=32, radius1=0.0005,
                          radius2=0.10, depth=0.3, matrix=Matrix.Translation((0, 0, 0.15)))
    add_obj("BT_Arrow_%s_Head" % tag, mesh_from_bm("BT_ArrowHead_%s" % tag, bm, [mat_arrow]), parent=root)
    add_text("BT_Arrow_%s_Label" % tag, label, 0.42, (0, 0, 1.0), mat_label, parent=root, extrude=0.03)
    vx = 0.22 if value_align == "LEFT" else -0.22
    add_text("BT_Arrow_%s_Value" % tag, "", 0.17, (vx, 0, 0.6), mat_label, parent=root, align=value_align)
    return root


def _add_light(name, kind, loc, energy, target, color=(1, 1, 1), size=6.0, angle=None):
    ld = bpy.data.lights.new(name, kind)
    ld.energy = energy
    ld.color = color
    if kind == "AREA":
        ld.shape = "RECTANGLE"
        ld.size, ld.size_y = size, size * 0.7
    elif kind == "SUN" and angle is not None:
        ld.angle = angle
    ob = bpy.data.objects.new(name, ld)
    COLL.objects.link(ob)
    ob.location = loc
    c = ob.constraints.new("TRACK_TO")
    c.target = target
    c.track_axis = "TRACK_NEGATIVE_Z"
    c.up_axis = "UP_Y"
    return ob


def build_scene(scene):
    global COLL
    _purge_previous()
    COLL = bpy.data.collections.new(COLL_NAME)
    scene.collection.children.link(COLL)

    # Hide (non-destructively) the default startup objects so they don't clutter the shot.
    for nm in ("Cube", "Light", "Camera"):
        ob = bpy.data.objects.get(nm)
        if ob is not None and ob.name not in COLL.objects:
            ob.hide_set(True)
            ob.hide_render = True

    # --- materials ---------------------------------------------------------
    steel = make_mat("BT_Steel", (0.78, 0.80, 0.83), 1.0, 0.22)
    dark_steel = make_mat("BT_DarkSteel", (0.20, 0.21, 0.23), 1.0, 0.32)
    rib_dark = make_mat("BT_RibDark", (0.04, 0.04, 0.05), 0.5, 0.45)
    blue = make_mat("BT_Blue", (0.03, 0.18, 0.80), 0.15, 0.32, coat=0.6)
    rope_m = make_mat("BT_Rope", (0.78, 0.62, 0.38), 0.0, 0.95, bump=0.35)
    yellow = make_mat("BT_Yellow", (1.0, 0.76, 0.02), 0.0, 0.38, coat=0.3)
    red = make_mat("BT_Red", (0.85, 0.03, 0.03), 0.0, 0.35, emit=(0.9, 0.02, 0.02, 0.4))
    label_red = make_mat("BT_LabelRed", (0.55, 0.02, 0.02), 0.0, 0.5)
    black = make_mat("BT_Black", (0.01, 0.01, 0.01), 0.0, 0.5)
    floor_m = make_mat("BT_Floor", (0.82, 0.84, 0.87), 0.0, 0.85)
    grip_m = make_mat("BT_Grip", (0.05, 0.05, 0.06), 0.0, 0.6)

    # --- studio backdrop (cyclorama: floor curving up into a wall) ----------
    prof = [(-16.0, 0.0), (3.0, 0.0)]
    for i in range(1, 17):
        a = -pi / 2 + (pi / 2) * i / 16
        prof.append((3 + 5 * cos(a), 5 + 5 * sin(a)))
    prof.append((8.0, 18.0))
    bm = bmesh.new()
    left = [bm.verts.new((-18.0, y, z)) for (y, z) in prof]
    right = [bm.verts.new((18.0, y, z)) for (y, z) in prof]
    for i in range(len(prof) - 1):
        bm.faces.new((left[i], right[i], right[i + 1], left[i + 1]))     # normals face the camera
    for f in bm.faces:
        f.smooth = True
    me = bpy.data.meshes.new("BT_BackdropMesh")
    bm.to_mesh(me)
    bm.free()
    me.materials.append(floor_m)
    add_obj("BT_Backdrop", me)

    # --- overhead I-beam -----------------------------------------------------
    bm = bmesh.new()
    bm_box(bm, (0, 0, 6.23), (3.2, 0.50, 0.06))     # bottom flange
    bm_box(bm, (0, 0, 6.57), (3.2, 0.50, 0.06))     # top flange
    bm_box(bm, (0, 0, 6.40), (3.2, 0.06, 0.28))     # web
    beam = add_obj("BT_Beam", mesh_from_bm("BT_BeamMesh", bm, [blue]))
    add_bevel(beam, 0.008)

    # --- rope anchor (clamp + eye rod under the beam) --------------------------
    bm = bmesh.new()
    bm_cyl(bm, (XS[0], 0, 5.98), 0.05, 0.14, "Z", 32)
    bm_cyl(bm, (XS[0], 0, 6.125), 0.02, 0.15, "Z", 16)
    add_obj("BT_Anchor", mesh_from_bm("BT_AnchorMesh", bm, [steel]))

    # --- pulley mesh shared by the four sheaves ---------------------------------
    pul_me = _pulley_mesh([steel, rib_dark])

    # --- lower block empty (everything that lifts is parented to it) -------------
    lb = bpy.data.objects.new("BT_LowerBlock", None)
    lb.empty_display_type = "PLAIN_AXES"
    lb.empty_display_size = 0.2
    COLL.objects.link(lb)

    # --- pulleys, axles, clevis hangers, lower side plates ------------------------
    for key, info in PULLEYS.items():
        x = info["x"]
        zc = ZM0 if info["movable"] else ZF
        parent = lb if info["movable"] else None
        add_obj("BT_Pulley_%s" % key, pul_me, loc=(x, 0, zc), parent=parent)
        bm = bmesh.new()
        bm_cyl(bm, (0, 0, 0), 0.04, 0.30, "Y", 24)
        for sd in (-1, 1):
            bm_cyl(bm, (0, sd * 0.13, 0), 0.065, 0.03, "Y", 24)
        add_obj("BT_Axle_%s" % key, mesh_from_bm("BT_AxleMesh_%s" % key, bm, [steel]),
                loc=(x, 0, zc), parent=parent)
        if not info["movable"]:
            # blue clevis: two cheek plates + bridge above the pulley, then a hanger rod to the beam
            bm = bmesh.new()
            for sd in (-1, 1):
                bm_box(bm, (x, sd * 0.10, ZF + 0.16), (0.76, 0.03, 0.64))
            bm_box(bm, (x, 0, ZF + 0.51), (0.76, 0.23, 0.06))
            cl = add_obj("BT_Clevis_%s" % key, mesh_from_bm("BT_ClevisMesh_%s" % key, bm, [blue]))
            add_bevel(cl, 0.008)
            bm = bmesh.new()
            bm_cyl(bm, (x, 0, 5.97), 0.045, 0.46, "Z", 24)
            bm_cyl(bm, (x, 0, 6.145), 0.075, 0.05, "Z", 6)       # hex nut under the beam
            add_obj("BT_HangerRod_%s" % key, mesh_from_bm("BT_RodMesh_%s" % key, bm, [steel]))

    # lower block: two steel side plates + yoke bar
    bm = bmesh.new()
    for sd in (-1, 1):
        bm_box(bm, (BLOCK_CX, sd * 0.10, ZM0 - 0.11), (2.04, 0.03, 0.62))
    bm_box(bm, (BLOCK_CX, 0, ZM0 - 0.46), (2.04, 0.23, 0.08))
    plates = add_obj("BT_LowerFrame", mesh_from_bm("BT_LowerFrameMesh", bm, [steel]), parent=lb)
    add_bevel(plates, 0.01)

    # --- lower hook (swept poly curve) + swivel collar -----------------------------
    z_bar = ZM0 - 0.50                              # bottom of yoke bar
    z0 = 0.738                                      # centre height of hook bowl
    hook_pts = [(BLOCK_CX, 0, z_bar), (BLOCK_CX, 0, z0)]
    for i in range(1, 25):
        phi = pi + (1.4 * pi) * i / 24
        hook_pts.append((BLOCK_CX + HOOK_DX + 0.1 * cos(phi), 0, z0 + 0.1 * sin(phi)))
    hcu = bpy.data.curves.new("BT_HookCurve", "CURVE")
    hcu.dimensions = "3D"
    hcu.bevel_depth = 0.018
    hcu.bevel_resolution = 4
    hcu.use_fill_caps = True
    sp = hcu.splines.new("POLY")
    sp.points.add(len(hook_pts) - 1)
    for p, c in zip(sp.points, hook_pts):
        p.co = (c[0], c[1], c[2], 1.0)
    hcu.materials.append(dark_steel)
    add_obj("BT_Hook", hcu, parent=lb)
    bm = bmesh.new()
    bm_cyl(bm, (BLOCK_CX, 0, z_bar + 0.015), 0.05, 0.06, "Z", 24)
    add_obj("BT_HookCollar", mesh_from_bm("BT_HookCollarMesh", bm, [dark_steel]), parent=lb)

    # --- load: eye ring hanging on the hook + yellow cube labelled W ---------------
    hb = z0 - 0.1                                   # lowest point of the hook bowl
    lx = BLOCK_CX + HOOK_DX                         # load x
    bm = bmesh.new()
    bm_lathe(bm, torus_profile(0.06, 0.012), 64)
    add_obj("BT_LoadEye", mesh_from_bm("BT_LoadEyeMesh", bm, [dark_steel]),
            loc=(lx, 0, hb - 0.066), rot=(0, 0, pi / 2), parent=lb)
    bm = bmesh.new()
    bm_box(bm, (0, 0, 0), (0.5, 0.5, 0.5))
    load = add_obj("BT_Load", mesh_from_bm("BT_LoadMesh", bm, [yellow]), loc=(lx, 0, 0.25), parent=lb)
    add_bevel(load, 0.02)
    add_text("BT_Load_W", "W", 0.36, (lx, -0.252, 0.25), black, parent=lb, extrude=0.02)

    # --- rope (poly curve; points are rewritten by apply_rig) -------------------------
    rcu = bpy.data.curves.new("BT_RopeCurve", "CURVE")
    rcu.dimensions = "3D"
    rcu.bevel_depth = ROPE_R
    rcu.bevel_resolution = 4
    rcu.use_fill_caps = True
    rsp = rcu.splines.new("POLY")
    pts = rope_points(0.0, 0.0)
    rsp.points.add(len(pts) - 1)
    for p, c in zip(rsp.points, pts):
        p.co = (c[0], c[1], c[2], 1.0)
    rcu.materials.append(rope_m)
    add_obj("BT_Rope", rcu)

    # --- pull handle + force arrows --------------------------------------------------
    bm = bmesh.new()
    bm_cyl(bm, (0, 0, 0), 0.035, 0.36, "Y", 24)
    handle = add_obj("BT_Handle", mesh_from_bm("BT_HandleMesh", bm, [grip_m]), loc=(XS[4], 0, Z_END0))
    _make_arrow("F", handle, (-0.35, 0, 0.05), red, label_red, "F", "RIGHT")
    _make_arrow("W", lb, (1.55, 0, 0.30), red, label_red, "W", "LEFT")

    # --- studio lighting ---------------------------------------------------------------
    tgt = bpy.data.objects.new("BT_CamTarget", None)
    tgt.location = (0, 0, 3.3)
    COLL.objects.link(tgt)
    _add_light("BT_Key", "AREA", (-7, -9, 9), 2200, tgt, (1.0, 0.97, 0.92), 6.0)
    _add_light("BT_Fill", "AREA", (8, -10, 4), 800, tgt, (0.88, 0.93, 1.0), 8.0)
    _add_light("BT_Rim", "AREA", (6, 4, 10), 900, tgt, (1, 1, 1), 5.0)
    sun = _add_light("BT_Sun", "SUN", (0, -10, 12), 2.5, tgt, (1, 0.98, 0.95), angle=radians(2))
    sun.constraints.clear()
    sun.rotation_euler = (radians(50), 0.0, radians(-30))     # front-left key -> shadows on the wall

    cam_d = bpy.data.cameras.new("BT_Camera")
    cam_d.lens = 55
    cam_d.clip_end = 300
    cam = bpy.data.objects.new("BT_Camera", cam_d)
    COLL.objects.link(cam)
    cam.location = (3.5, -20.5, 3.8)
    c = cam.constraints.new("TRACK_TO")
    c.target = tgt
    c.track_axis = "TRACK_NEGATIVE_Z"
    c.up_axis = "UP_Y"
    scene.camera = cam

    # --- world / render settings ----------------------------------------------------------
    world = bpy.data.worlds.new("BT_World")
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg is not None:
        bg.inputs[0].default_value = (0.60, 0.63, 0.68, 1.0)
        bg.inputs[1].default_value = 0.5
    scene.world = world
    scene.render.resolution_x, scene.render.resolution_y = 1920, 1080
    scene.render.film_transparent = False
    for eng in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):        # 4.2+ / 4.0-4.1 identifiers
        try:
            scene.render.engine = eng
            break
        except TypeError:
            continue
    try:
        scene.eevee.taa_render_samples = 64
    except Exception:
        pass

    # --- viewport: camera view + material preview (best effort) -----------------------------
    try:
        for win in bpy.context.window_manager.windows:
            for area in win.screen.areas:
                if area.type == "VIEW_3D":
                    sp3 = area.spaces.active
                    sp3.shading.type = "MATERIAL"
                    sp3.region_3d.view_perspective = "CAMERA"
    except Exception:
        pass

    s = scene.bt_sim
    s.anim_mode = "IDLE"
    s.rope_d = 0.0
    apply_rig(scene)


# ----------------------------------------------------------------------------
# 6. MOTION RIGGING
# ----------------------------------------------------------------------------
def O(name):
    return bpy.data.objects.get(name)


def _set_arrow(tag, force):
    ls = min(max(ARROW_K * force, ARROW_MIN), ARROW_MAX)
    sh, lab, val = O("BT_Arrow_%s_Shaft" % tag), O("BT_Arrow_%s_Label" % tag), O("BT_Arrow_%s_Value" % tag)
    if sh is None or lab is None or val is None:
        return
    sh.scale = (1.0, 1.0, ls)
    sh.location = (0.0, 0.0, 0.3 + ls / 2)
    lab.location = (0.0, 0.0, 0.3 + ls + 0.30)
    val.location = (val.location.x, 0.0, 0.3 + ls / 2)
    val.data.body = "= %.0f N" % force


def _update_rope(h, d):
    rope = O("BT_Rope")
    if rope is None:
        return
    cu = rope.data
    pts = rope_points(h, d)
    sp = cu.splines[0]
    if len(sp.points) != len(pts):
        return
    flat = []
    for (x, y, z) in pts:
        flat += [x, y, z, 1.0]
    sp.points.foreach_set("co", flat)
    cu.update_tag()
    rope.update_tag()


def apply_rig(scene):
    """Drive the whole mechanism from the single quantity d (rope pulled through).

    Kinematics (rope inextensible, anchor fixed):
      4 strands carry the lower block, so rope freed = 4h  ->  d = IMA*h, h = d/IMA.
      Rope speed relative to each sheave axle gives angular rates (R = groove radius):
        right movable  w = 1 * h'/R   (clockwise)
        right fixed    w = 2 * h'/R   (counter-clockwise)
        left movable   w = 3 * h'/R   (clockwise)
        left fixed     w = 4 * h'/R = d'/R (counter-clockwise, same as free-end speed)
      so the pulley angles are theta_k = k*h/R.  (Front view: +rot Y = clockwise.)
    """
    s = getattr(scene, "bt_sim", None)
    lb = O("BT_LowerBlock")
    if s is None or lb is None:
        return
    d = min(max(s.rope_d, 0.0), D_MAX)
    h = d / IMA
    lb.location = (0.0, 0.0, h)
    for key, info in PULLEYS.items():
        ob = O("BT_Pulley_%s" % key)
        if ob is not None:
            ob.rotation_euler = (0.0, info["sign"] * info["k"] * h / R_ROPE, 0.0)
    _update_rope(h, d)
    hd = O("BT_Handle")
    if hd is not None:
        hd.location = (XS[4], 0.0, Z_END0 - d)
    st = calc_state(s.load_w, s.efficiency, d)
    _set_arrow("W", st["W"])
    _set_arrow("F", st["F_actual"])


def _redraw():
    try:
        for win in bpy.context.window_manager.windows:
            for area in win.screen.areas:
                if area.type == "VIEW_3D":
                    area.tag_redraw()
    except Exception:
        pass


def _tick():
    """Timer (30 Hz): eased 'Pull' moves and the auto Presentation Mode cycle."""
    changed = False
    for sc in bpy.data.scenes:
        s = getattr(sc, "bt_sim", None)
        if s is None or s.anim_mode == "IDLE":
            continue
        step = max(s.anim_speed, 0.05) * TICK
        if s.anim_mode == "PULL":
            tgt = min(max(s.anim_target, 0.0), D_MAX)
            if abs(tgt - s.rope_d) <= step:
                s.rope_d = tgt
                s.anim_mode = "IDLE"
            else:
                s.rope_d += step if tgt > s.rope_d else -step
            changed = True
        elif s.anim_mode == "PLAY":
            top = min(IMA * s.lift_h, D_MAX)
            if top <= 1e-6:
                s.anim_mode = "IDLE"
                continue
            if s.play_phase == 0:                       # pull
                if s.rope_d + step >= top:
                    s.rope_d, s.play_phase, s.play_hold = top, 1, 0.9
                else:
                    s.rope_d += step
            elif s.play_phase == 2:                     # release
                if s.rope_d - step <= 0.0:
                    s.rope_d, s.play_phase, s.play_hold = 0.0, 3, 0.9
                else:
                    s.rope_d -= step
            else:                                       # holds
                s.play_hold -= TICK
                if s.play_hold <= 0:
                    s.play_phase = 2 if s.play_phase == 1 else 0
            changed = True
    if changed:
        _redraw()
    return TICK


@persistent
def _bt_load_post(_dummy=None):
    for sc in bpy.data.scenes:
        try:
            apply_rig(sc)
        except Exception:
            pass


_bt_load_post._bt_tag = True


# ----------------------------------------------------------------------------
# 7. PROPERTIES, OPERATORS, UI
# ----------------------------------------------------------------------------
def _on_param(self, context):
    apply_rig(self.id_data)


def _on_lift(self, context):
    if self.anim_mode == "IDLE":          # choosing a lift distance moves the mechanism there
        self.rope_d = min(IMA * self.lift_h, D_MAX)
    apply_rig(self.id_data)


class BT_Settings(bpy.types.PropertyGroup):
    load_w: FloatProperty(name="Load Weight W (N)", default=1000.0, min=1.0, max=3000.0,
                          precision=0, step=1000, update=_on_param,
                          description="Weight of the load (newtons)")
    lift_h: FloatProperty(name="Lift Distance h", default=0.5, min=0.0, max=H_MAX, unit="LENGTH",
                          precision=3, update=_on_lift,
                          description="Target lift of the load (used by presets, Play and CSV)")
    rope_d: FloatProperty(name="Rope Displacement d", default=0.0, min=0.0, max=D_MAX, unit="LENGTH",
                          precision=3, update=_on_param,
                          description="Rope pulled through at the free end (live; h = d / IMA)")
    efficiency: FloatProperty(name="Efficiency", default=80.0, min=5.0, max=100.0,
                              subtype="PERCENTAGE", precision=1, update=_on_param,
                              description="Overall mechanical efficiency of the system")
    pull_step: FloatProperty(name="Pull Step", default=0.25, min=0.02, max=1.0, unit="LENGTH",
                             description="Rope length added by one press of Pull")
    anim_speed: FloatProperty(name="Rope Speed (m/s)", default=0.8, min=0.05, max=3.0,
                              description="Speed of the animated rope pull")
    csv_path: StringProperty(name="CSV File", subtype="FILE_PATH", default="//block_tackle_telemetry.csv")
    anim_mode: EnumProperty(items=[("IDLE", "Idle", ""), ("PULL", "Pull", ""), ("PLAY", "Presentation", "")],
                            default="IDLE")
    anim_target: FloatProperty(default=0.0)
    play_phase: IntProperty(default=0)
    play_hold: FloatProperty(default=0.0)


class BT_OT_Build(bpy.types.Operator):
    bl_idname = "bt.build"
    bl_label = "Build / Rebuild Scene"
    bl_description = "Create (or recreate) the procedural block-and-tackle scene"

    def execute(self, context):
        build_scene(context.scene)
        return {"FINISHED"}


class BT_OT_Pull(bpy.types.Operator):
    bl_idname = "bt.pull"
    bl_label = "Pull"
    bl_description = "Advance the rope by one pull step (smoothly animated)"

    def execute(self, context):
        s = context.scene.bt_sim
        base = max(s.anim_target, s.rope_d) if s.anim_mode == "PULL" else s.rope_d
        s.anim_target = min(base + s.pull_step, D_MAX)
        s.anim_mode = "PULL"
        return {"FINISHED"}


class BT_OT_Reset(bpy.types.Operator):
    bl_idname = "bt.reset"
    bl_label = "Reset"
    bl_description = "Stop everything and return the mechanism to zero displacement"

    def execute(self, context):
        s = context.scene.bt_sim
        s.anim_mode = "IDLE"
        s.play_phase = 0
        s.rope_d = 0.0
        return {"FINISHED"}


class BT_OT_Play(bpy.types.Operator):
    bl_idname = "bt.play"
    bl_label = "Play / Pause Presentation"
    bl_description = "Auto-animated cycle: pull to the target lift, hold, release, repeat"

    def execute(self, context):
        s = context.scene.bt_sim
        if s.anim_mode == "PLAY":
            s.anim_mode = "IDLE"
        else:
            s.play_phase = 0 if s.rope_d < IMA * s.lift_h - 1e-6 else 1
            s.play_hold = 0.5
            s.anim_mode = "PLAY"
        return {"FINISHED"}


class BT_OT_Preset(bpy.types.Operator):
    bl_idname = "bt.preset"
    bl_label = "Load Test Case"
    bl_description = "Load a preset (W, h, efficiency) and animate the pull"
    case_id: IntProperty(default=1)

    def execute(self, context):
        loads = {1: 500.0, 2: 1000.0, 3: 1500.0}
        s = context.scene.bt_sim
        s.anim_mode = "PULL"                 # set first so the lift callback does not jump
        s.load_w = loads.get(self.case_id, 1000.0)
        s.lift_h = 0.50
        s.efficiency = 80.0
        s.rope_d = 0.0
        s.anim_target = IMA * 0.50
        return {"FINISHED"}


class BT_OT_ExportCSV(bpy.types.Operator):
    bl_idname = "bt.export_csv"
    bl_label = "Export Telemetry (CSV)"
    bl_description = "Write d, h, W_out, W_in, F_ideal, F_actual, AMA (sweep from 0 to the current/target d)"

    def execute(self, context):
        s = context.scene.bt_sim
        path = bpy.path.abspath(s.csv_path)
        if not bpy.data.filepath and s.csv_path.startswith("//"):
            path = os.path.join(os.path.expanduser("~"), s.csv_path[2:])
        d_end = s.rope_d if s.rope_d > 1e-6 else IMA * s.lift_h
        n = 21
        try:
            folder = os.path.dirname(path)
            if folder:
                os.makedirs(folder, exist_ok=True)
            with open(path, "w", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(["d_m", "h_m", "W_out_J", "W_in_J", "F_ideal_N", "F_actual_N", "AMA",
                            "W_N", "efficiency_pct"])
                for i in range(n):
                    st = calc_state(s.load_w, s.efficiency, d_end * i / (n - 1))
                    w.writerow(["%.6f" % st["d"], "%.6f" % st["h"], "%.4f" % st["W_out"],
                                "%.4f" % st["W_in"], "%.4f" % st["F_ideal"], "%.4f" % st["F_actual"],
                                "%.4f" % st["AMA"], "%.2f" % st["W"], "%.2f" % s.efficiency])
        except OSError as exc:
            self.report({"ERROR"}, "Could not write CSV: %s" % exc)
            return {"CANCELLED"}
        self.report({"INFO"}, "Telemetry saved: %s" % path)
        return {"FINISHED"}


def _kv(layout, key, value):
    sp = layout.split(factor=0.55, align=True)
    sp.label(text=key)
    sp.label(text=value)


def _wrapped(layout, text, width=38):
    col = layout.column(align=True)
    for line in textwrap.wrap(text, width):
        col.label(text=line)


class BT_PT_Main(bpy.types.Panel):
    bl_idname = "BT_PT_main"
    bl_label = "Block & Tackle Simulator"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Block & Tackle"

    def draw(self, context):
        lay = self.layout
        s = context.scene.bt_sim
        if O("BT_LowerBlock") is None:
            lay.operator("bt.build", icon="MOD_BUILD")
            return
        box = lay.box()
        box.label(text="Input Parameters", icon="PREFERENCES")
        box.prop(s, "load_w")
        box.prop(s, "lift_h")
        box.prop(s, "rope_d")
        box.prop(s, "efficiency")
        box = lay.box()
        box.label(text="Preset Test Cases (eff. 80%, h = 0.50 m)", icon="PRESET")
        row = box.row(align=True)
        for i, txt in ((1, "1: 500 N"), (2, "2: 1000 N"), (3, "3: 1500 N")):
            row.operator("bt.preset", text=txt).case_id = i
        box = lay.box()
        box.label(text="Actions", icon="PLAY")
        row = box.row(align=True)
        row.operator("bt.pull", icon="TRIA_DOWN")
        row.operator("bt.reset", icon="LOOP_BACK")
        playing = s.anim_mode == "PLAY"
        box.operator("bt.play", text="Pause Presentation" if playing else "Play Presentation",
                     icon="PAUSE" if playing else "PLAY", depress=playing)
        box.prop(s, "pull_step")
        box.prop(s, "anim_speed")
        box.prop(s, "csv_path", text="")
        box.operator("bt.export_csv", icon="EXPORT")
        lay.operator("bt.build", text="Rebuild Scene", icon="FILE_REFRESH")


class BT_PT_Telemetry(bpy.types.Panel):
    bl_idname = "BT_PT_telemetry"
    bl_label = "Live Telemetry"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Block & Tackle"
    bl_parent_id = "BT_PT_main"

    @classmethod
    def poll(cls, context):
        return O("BT_LowerBlock") is not None

    def draw(self, context):
        s = context.scene.bt_sim
        st = calc_state(s.load_w, s.efficiency, s.rope_d)
        lay = self.layout
        col = lay.column(align=True)
        _kv(col, "IMA = n", "%d" % IMA)
        _kv(col, "AMA = IMA x eff", "%.2f" % st["AMA"])
        _kv(col, "Rope pulled d", "%.3f m" % st["d"])
        _kv(col, "Lift h = d / IMA", "%.3f m" % st["h"])
        lay.separator()
        col = lay.column(align=True)
        _kv(col, "Load W", "%.1f N" % st["W"])
        _kv(col, "F ideal = W/IMA", "%.2f N" % st["F_ideal"])
        _kv(col, "F actual = W/AMA", "%.2f N" % st["F_actual"])
        lay.separator()
        col = lay.column(align=True)
        _kv(col, "W out = W x h", "%.2f J" % st["W_out"])
        _kv(col, "W in = F x d", "%.2f J" % st["W_in"])
        _kv(col, "Energy lost", "%.2f J" % st["loss"])
        _kv(col, "Efficiency", "%.1f %%" % st["eff"])
        lay.label(text="Mode: %s" % {"IDLE": "idle", "PULL": "pulling", "PLAY": "presentation"}[s.anim_mode])


class BT_PT_Notes(bpy.types.Panel):
    bl_idname = "BT_PT_notes"
    bl_label = "Physics Notes"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Block & Tackle"
    bl_parent_id = "BT_PT_main"

    def draw(self, context):
        lay = self.layout
        notes = (
            "Pulleys: a fixed pulley only changes the direction of the pull; a movable pulley also "
            "shares the load between the rope strands that support it.",
            "Mechanical advantage: 4 strands support the lower block, so IMA = n = 4 and ideally "
            "F = W / 4.",
            "Distance trade-off: pulling d = 4 x h of rope lifts the load by h. Force is gained, "
            "distance is paid (energy is conserved).",
            "Efficiency: friction in axles, rope bending and the weight of the lower block waste "
            "energy, so W_in > W_out, AMA = IMA x eff and F_actual = W / AMA > F_ideal.",
            "Check: eff = W_out / W_in x 100 = (W x h) / (F x d) x 100.",
        )
        for n in notes:
            _wrapped(lay, n)
            lay.separator(factor=0.4)


CLASSES = (BT_Settings, BT_OT_Build, BT_OT_Pull, BT_OT_Reset, BT_OT_Play, BT_OT_Preset,
           BT_OT_ExportCSV, BT_PT_Main, BT_PT_Telemetry, BT_PT_Notes)


# ----------------------------------------------------------------------------
# 8. CLEAN REGISTRATION
# ----------------------------------------------------------------------------
def unregister():
    try:
        if bpy.app.timers.is_registered(_tick):
            bpy.app.timers.unregister(_tick)
    except Exception:
        pass
    for h in list(bpy.app.handlers.load_post):
        if getattr(h, "_bt_tag", False):
            bpy.app.handlers.load_post.remove(h)
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
    if hasattr(bpy.types.Scene, "bt_sim"):
        try:
            del bpy.types.Scene.bt_sim
        except Exception:
            pass
    bpy.app.driver_namespace.pop(_NS_KEY, None)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.bt_sim = PointerProperty(type=BT_Settings)
    bpy.app.handlers.load_post.append(_bt_load_post)
    bpy.app.timers.register(_tick, first_interval=0.5, persistent=True)
    bpy.app.driver_namespace[_NS_KEY] = unregister


def _cleanup_previous_run():
    """Remove classes / handlers / timers left by an earlier run of this script."""
    old = bpy.app.driver_namespace.get(_NS_KEY)
    if callable(old):
        try:
            old()
        except Exception as exc:
            print("[BlockTackle] previous cleanup warning:", exc)
    for h in list(bpy.app.handlers.load_post):
        if getattr(h, "_bt_tag", False):
            bpy.app.handlers.load_post.remove(h)


if __name__ == "__main__":
    _selftest()
    _cleanup_previous_run()
    register()
    build_scene(bpy.context.scene)
    print("[BlockTackle] Ready - press N in the 3D viewport and open the 'Block & Tackle' tab.")


# ============================================================================
# USER GUIDE
# ============================================================================
# HOW TO RUN
#   1. Open Blender 4.x, switch to the "Scripting" workspace (top tabs).
#   2. Text Editor > New (or Open), paste/open this file, press "Run Script" (Alt+P).
#      Re-running is safe: the previous UI classes, timer, handlers and the old
#      "BT_Block_Tackle" collection are removed first.
#   3. Hover over the 3D viewport and press N. Open the "Block & Tackle" tab:
#      panel "Block & Tackle Simulator" (+ sub-panels "Live Telemetry" and
#      "Physics Notes"). The viewport switches to camera view (best effort);
#      press Numpad 0 if it does not.
#   4. Click Case 1/2/3 to load a test case and watch the animated pull, drag the
#      d slider by hand, use Pull / Reset, or Play Presentation for an auto cycle.
#      Export Telemetry writes a CSV (default: next to the .blend, or your home
#      folder if the file is unsaved) with columns d, h, W_out, W_in, F_ideal,
#      F_actual, AMA (+ W and efficiency).  Render with F12 (EEVEE).
#
# API TRADE-OFFS (being transparent)
#   * Kinematic rig, not a physics simulation: the rope is a poly curve whose
#     points are recomputed analytically; there is no cloth/soft-body solver and
#     no real friction. Efficiency is a user-set number that feeds the formulas.
#   * Animation is driven by a bpy.app.timers callback (30 Hz) instead of
#     keyframes, so it runs without pressing the timeline Play button. It does
#     not render to video by itself; for an MP4 you would keyframe d.
#   * Rope strands are vertical and exactly 2*R apart (staircase layout), which
#     guarantees no rope/rope or rope/pulley intersection; the two blocks are
#     therefore offset by 0.6 m in x - the strand centroid still sits on the hook.
#   * Principled BSDF socket names changed in 4.0 (Coat Weight); the script tries
#     both names. The EEVEE engine id differs between 4.0/4.1 and 4.2+; both are tried.
#   * Text labels use Blender's built-in font; no textures or external files.
#   * Arrow lengths scale with force (W vs F) for visual comparison, clamped to a
#     sensible range - they are illustrative, not to scale with metres.
# ============================================================================
