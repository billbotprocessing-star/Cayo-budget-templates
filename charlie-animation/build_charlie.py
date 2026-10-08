"""
CHARLIE -- a short, Pixar-style Blender animation about one ordinary Tuesday
in the life of a 30-something.

Everything (characters, sets, lighting, animation, camera cuts) is built
procedurally, so the film can be regenerated from this one file.

Usage (Blender GUI or CLI):
    blender -b -P build_charlie.py -- --save charlie.blend
    blender -b -P build_charlie.py -- --render renders/frames/ --res 1280x720

Usage (bpy module from pip):
    python build_charlie.py --save charlie.blend --render renders/frames/

Options:
    --save PATH          write the .blend file
    --render DIR         render the animation as PNG frames into DIR
    --frames A-B         only render this frame range
    --stills F1,F2,...   render individual frames (for checking shots)
    --res WxH            resolution (default 960x540)
    --samples N          Cycles samples (default 14, denoised)
"""

import argparse
import math
import os
import sys

import bpy  # noqa: E402  (bpy must be imported before bmesh)
import bmesh
from mathutils import Euler, Vector

FPS = 24
R = math.radians

# --------------------------------------------------------------------------
# Story timeline (frames are laid out back to back from SCENES)
# --------------------------------------------------------------------------
SCENES = [
    ("title", 84),       # CHARLIE - an ordinary Tuesday
    ("bed", 216),        # 6:47 alarm, snooze, oversleeps
    ("kitchen", 216),    # coffee + notification avalanche
    ("desk", 360),       # WFH: calls, inbox, mugs, wilting plant, time-lapse
    ("couch", 228),      # takeout, group chat "next month?", phone dies
    ("window", 300),     # waters the plant, raises the blinds: sunset
    ("outside", 216),    # neighbour waves, pull back on the whole building
    ("end", 144),        # end card
]
START = {}
_f = 1
for _name, _len in SCENES:
    START[_name] = _f
    _f += _len
FRAME_END = _f - 1

# set origins along X, far enough apart that lights don't leak between sets
OX = dict(title=-80, end=-160, bed=0, kitchen=60, desk=120, couch=180, window=320)


# --------------------------------------------------------------------------
# Small utilities
# --------------------------------------------------------------------------
def srgb(h):
    """'#rrggbb' -> linear RGB tuple."""
    h = h.lstrip("#")
    out = []
    for i in (0, 2, 4):
        c = int(h[i:i + 2], 16) / 255.0
        out.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return tuple(out)


_INTERP = []  # (owner, rna path, frame, interpolation) applied in finalize_interp()


def _remember(owner, path, frame, interp):
    if interp != "BEZIER":
        _INTERP.append((owner, path, frame, interp))


def key(obj, path, frame, value=None, interp="BEZIER"):
    if value is not None:
        if path == "rotation_euler":
            value = [R(v) for v in value]
        setattr(obj, path, value)
    obj.keyframe_insert(path, frame=frame)
    _remember(obj, path, frame, interp)


def key_socket(sock, frame, value, interp="BEZIER"):
    sock.default_value = value
    sock.keyframe_insert("default_value", frame=frame)
    _remember(sock, "default_value", frame, interp)


def key_prop(owner, path, frame, value, interp="BEZIER"):
    setattr(owner, path, value)
    owner.keyframe_insert(path, frame=frame)
    _remember(owner, path, frame, interp)


def _fcurves(idb):
    ad = idb.animation_data
    if ad is None or ad.action is None:
        return []
    act = ad.action
    if hasattr(act, "fcurves") and not hasattr(act, "layers"):
        return act.fcurves
    try:
        from bpy_extras.anim_utils import action_get_channelbag_for_slot
        cb = action_get_channelbag_for_slot(act, ad.action_slot)
        return cb.fcurves if cb else []
    except ImportError:
        return act.fcurves


def finalize_interp():
    """Blender 4.4+/5.x ignore the 'new keyframe interpolation' preference when
    keys are inserted from Python, so set interpolation on the keys directly."""
    for owner, path, frame, interp in _INTERP:
        idb = owner.id_data
        full = owner.path_from_id(path) if owner != idb else path
        for fc in _fcurves(idb):
            if fc.data_path != full:
                continue
            for kp in fc.keyframe_points:
                if abs(kp.co.x - frame) < 0.01:
                    kp.interpolation = interp
    # visibility channels are booleans: always step
    for idb in list(bpy.data.objects):
        for fc in _fcurves(idb):
            if fc.data_path in ("hide_render", "hide_viewport"):
                for kp in fc.keyframe_points:
                    kp.interpolation = "CONSTANT"


def _tree(obj):
    return [obj] + list(obj.children_recursive)


def show(obj, frame, visible=True):
    """Key render/viewport visibility for an object and all its children."""
    for o in _tree(obj):
        o.hide_render = not visible
        o.hide_viewport = not visible
        o.keyframe_insert("hide_render", frame=frame)
        o.keyframe_insert("hide_viewport", frame=frame)
        if o.type == "LIGHT":
            pass


def only_between(obj, f0, f1):
    """Visible only for frames f0..f1 (inclusive)."""
    show(obj, 1, False)
    if f0 > 1:
        show(obj, f0, True)
    else:
        show(obj, 1, True)
    show(obj, f1 + 1, False)


def pop(obj, frame, dur=8, size=1.0):
    """Cartoon pop-in with overshoot."""
    s = size
    key(obj, "scale", frame - 1, (0.001, 0.001, 0.001))
    key(obj, "scale", frame + int(dur * 0.6), (s * 1.18, s * 1.18, s * 1.18))
    key(obj, "scale", frame + dur, (s, s, s))


def unpop(obj, frame, dur=6, size=1.0):
    s = size
    key(obj, "scale", frame, (s, s, s))
    key(obj, "scale", frame + int(dur * 0.4), (s * 1.12, s * 1.12, s * 1.12))
    key(obj, "scale", frame + dur, (0.001, 0.001, 0.001))


# --------------------------------------------------------------------------
# Materials
# --------------------------------------------------------------------------
_MATS = {}


def mat(name, color, rough=0.5, sss=0.0, metal=0.0, emit=None, strength=0.0,
        coat=0.0, sheen=0.0, spec=0.5):
    if name in _MATS:
        return _MATS[name]
    m = bpy.data.materials.new(name)
    try:
        m.use_nodes = True
    except Exception:
        pass
    b = m.node_tree.nodes.get("Principled BSDF")
    col = srgb(color) if isinstance(color, str) else color
    b.inputs["Base Color"].default_value = (*col, 1)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    if sss:
        b.inputs["Subsurface Weight"].default_value = sss
        b.inputs["Subsurface Radius"].default_value = (1.0, 0.45, 0.3)
        b.inputs["Subsurface Scale"].default_value = 0.04
    if coat:
        b.inputs["Coat Weight"].default_value = coat
    if sheen:
        b.inputs["Sheen Weight"].default_value = sheen
    if emit is not None:
        try:
            m.cycles.emission_sampling = "NONE"
        except Exception:
            pass
        ecol = srgb(emit) if isinstance(emit, str) else emit
        b.inputs["Emission Color"].default_value = (*ecol, 1)
        b.inputs["Emission Strength"].default_value = strength
    m.diffuse_color = (*col, 1)
    _MATS[name] = m
    return m


def emission_socket(m):
    return m.node_tree.nodes["Principled BSDF"].inputs["Emission Strength"]


def glow(name, color, strength=4.0, lights=False):
    """Pure emission material (screens, window glows, title backdrops).
    lights=False keeps Cycles from treating it as a light source (much faster)."""
    if name in _MATS:
        return _MATS[name]
    m = bpy.data.materials.new(name)
    try:
        m.use_nodes = True
    except Exception:
        pass
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    em = nt.nodes.new("ShaderNodeEmission")
    col = srgb(color) if isinstance(color, str) else color
    em.inputs["Color"].default_value = (*col, 1)
    em.inputs["Strength"].default_value = strength
    nt.links.new(em.outputs[0], out.inputs["Surface"])
    m.diffuse_color = (*col, 1)
    if not lights:
        try:
            m.cycles.emission_sampling = "NONE"
        except Exception:
            pass
    _MATS[name] = m
    return m


def glow_strength(m):
    return m.node_tree.nodes["Emission"].inputs["Strength"]


def glow_color(m):
    return m.node_tree.nodes["Emission"].inputs["Color"]


# --------------------------------------------------------------------------
# Geometry helpers
# --------------------------------------------------------------------------
COL = None  # active collection


def _link(o):
    COL.objects.link(o)
    return o


def _assign(o, m):
    if m is None:
        return
    if o.data is not None and hasattr(o.data, "materials"):
        if len(o.data.materials) == 0:
            o.data.materials.append(None)
        o.material_slots[0].link = "OBJECT"
        o.material_slots[0].material = m


def _place(o, loc, rot, scale, parent):
    o.parent = parent
    o.location = loc
    o.rotation_euler = [R(v) for v in rot]
    o.scale = scale
    return o


def empty(name, loc=(0, 0, 0), rot=(0, 0, 0), parent=None):
    o = _link(bpy.data.objects.new(name, None))
    o.empty_display_size = 0.15
    return _place(o, loc, rot, (1, 1, 1), parent)


_SPHERE = None


def _sphere_mesh():
    global _SPHERE
    if _SPHERE is None:
        me = bpy.data.meshes.new("unit_sphere")
        bm = bmesh.new()
        bmesh.ops.create_uvsphere(bm, u_segments=40, v_segments=24, radius=1.0)
        for f in bm.faces:
            f.smooth = True
        bm.to_mesh(me)
        bm.free()
        me.materials.append(None)
        _SPHERE = me
    return _SPHERE


def sphere(name, radii, loc=(0, 0, 0), m=None, rot=(0, 0, 0), parent=None):
    if isinstance(radii, (int, float)):
        radii = (radii, radii, radii)
    o = _link(bpy.data.objects.new(name, _sphere_mesh()))
    _place(o, loc, rot, radii, parent)
    _assign(o, m)
    return o


def hemisphere(name, radius, loc, m=None, rot=(0, 0, 0), parent=None):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=32, v_segments=20, radius=radius)
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if v.co.z < -0.02 * radius],
                     context="VERTS")
    for f in bm.faces:
        f.smooth = True
    bm.to_mesh(me)
    bm.free()
    o = _link(bpy.data.objects.new(name, me))
    _place(o, loc, rot, (1, 1, 1), parent)
    _assign(o, m)
    return o


def box(name, size, loc=(0, 0, 0), m=None, bevel=0.02, rot=(0, 0, 0), parent=None,
        segs=3):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co.x *= size[0]
        v.co.y *= size[1]
        v.co.z *= size[2]
    for f in bm.faces:
        f.smooth = True
    bm.to_mesh(me)
    bm.free()
    o = _link(bpy.data.objects.new(name, me))
    _place(o, loc, rot, (1, 1, 1), parent)
    if bevel > 0:
        md = o.modifiers.new("bevel", "BEVEL")
        md.width = min(bevel, min(size) * 0.49)
        md.segments = segs
        md.limit_method = "NONE"
        try:
            md.harden_normals = True
        except Exception:
            pass
    else:
        for p in me.polygons:
            p.use_smooth = False
    _assign(o, m)
    return o


def cylinder(name, r1, r2, depth, loc=(0, 0, 0), m=None, rot=(0, 0, 0), parent=None,
             segs=40):
    """Cylinder/cone with origin at its centre, axis along local Z."""
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=segs,
                          radius1=r1, radius2=r2, depth=depth)
    for f in bm.faces:
        f.smooth = abs(f.normal.z) < 0.7
    bm.to_mesh(me)
    bm.free()
    o = _link(bpy.data.objects.new(name, me))
    _place(o, loc, rot, (1, 1, 1), parent)
    _assign(o, m)
    return o


def torus(name, major, minor, loc=(0, 0, 0), m=None, rot=(0, 0, 0), parent=None,
          seg=40, ring=12):
    verts, faces = [], []
    for i in range(seg):
        a = 2 * math.pi * i / seg
        for j in range(ring):
            b = 2 * math.pi * j / ring
            rr = major + minor * math.cos(b)
            verts.append((rr * math.cos(a), rr * math.sin(a), minor * math.sin(b)))
    for i in range(seg):
        for j in range(ring):
            i2, j2 = (i + 1) % seg, (j + 1) % ring
            faces.append((i * ring + j, i2 * ring + j, i2 * ring + j2, i * ring + j2))
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    for p in me.polygons:
        p.use_smooth = True
    o = _link(bpy.data.objects.new(name, me))
    _place(o, loc, rot, (1, 1, 1), parent)
    _assign(o, m)
    return o


def curve_line(name, pts, depth, loc, m=None, parent=None, rot=(0, 0, 0)):
    cu = bpy.data.curves.new(name, "CURVE")
    cu.dimensions = "3D"
    cu.bevel_depth = depth
    cu.bevel_resolution = 4
    cu.use_fill_caps = True
    sp = cu.splines.new("BEZIER")
    sp.bezier_points.add(len(pts) - 1)
    for bp, p in zip(sp.bezier_points, pts):
        bp.co = p
        bp.handle_left_type = bp.handle_right_type = "AUTO"
    o = _link(bpy.data.objects.new(name, cu))
    _place(o, loc, rot, (1, 1, 1), parent)
    if m:
        cu.materials.append(m)
    return o


FONT_BOLD = None
FONT_SEMI = None


def _load_fonts():
    global FONT_BOLD, FONT_SEMI
    cands_b = ["/usr/share/fonts/opentype/inter/InterDisplay-Bold.otf",
               "/usr/share/fonts/opentype/inter/Inter-Bold.otf",
               "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
               "C:/Windows/Fonts/arialbd.ttf", "/Library/Fonts/Arial Bold.ttf"]
    cands_s = ["/usr/share/fonts/opentype/inter/Inter-SemiBold.otf",
               "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
               "C:/Windows/Fonts/arial.ttf", "/Library/Fonts/Arial.ttf"]
    for p in cands_b:
        if os.path.exists(p):
            FONT_BOLD = bpy.data.fonts.load(p)
            break
    for p in cands_s:
        if os.path.exists(p):
            FONT_SEMI = bpy.data.fonts.load(p)
            break


def text(name, body, loc, size, m, rot=(90, 0, 0), align="CENTER", parent=None,
         extrude=0.0, bold=True):
    cu = bpy.data.curves.new(name, "FONT")
    cu.body = body
    cu.size = size
    cu.align_x = align
    cu.align_y = "CENTER"
    cu.extrude = extrude
    f = FONT_BOLD if bold else (FONT_SEMI or FONT_BOLD)
    if f:
        cu.font = f
    cu.materials.append(m)
    o = _link(bpy.data.objects.new(name, cu))
    return _place(o, loc, rot, (1, 1, 1), parent)


def pill(name, w, h, d, loc, m, parent=None, rot=(0, 0, 0)):
    """Rounded 'notification' pill facing -Y."""
    g = empty(name, loc, rot, parent)
    box(name + "_mid", (max(w - h, 0.001), d, h), (0, 0, 0), m, bevel=0, parent=g)
    for s in (-1, 1):
        cylinder(name + "_cap%d" % s, h / 2, h / 2, d, (s * (w - h) / 2, 0, 0), m,
                 rot=(90, 0, 0), parent=g, segs=28)
    return g


def area_light(name, loc, target, energy, color="#ffffff", size=2.0, size_y=None,
               parent=None):
    ld = bpy.data.lights.new(name, "AREA")
    ld.energy = energy
    ld.color = srgb(color)
    if size_y:
        ld.shape = "RECTANGLE"
        ld.size = size
        ld.size_y = size_y
    else:
        ld.size = size
    o = _link(bpy.data.objects.new(name, ld))
    o.location = loc
    look_at(o, target)
    o.parent = parent
    return o


def point_light(name, loc, energy, color="#ffffff", radius=0.1):
    ld = bpy.data.lights.new(name, "POINT")
    ld.energy = energy
    ld.color = srgb(color)
    ld.shadow_soft_size = radius
    o = _link(bpy.data.objects.new(name, ld))
    o.location = loc
    return o


def look_at(o, target):
    d = Vector(target) - Vector(o.location)
    o.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()


def new_collection(name):
    global COL
    c = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(c)
    COL = c
    return c


# --------------------------------------------------------------------------
# Cameras
# --------------------------------------------------------------------------
CAM_CUTS = []  # (frame, camera)


def camera(name, loc, target, lens=40, focus=None, fstop=2.8):
    cd = bpy.data.cameras.new(name)
    cd.lens = lens
    cd.sensor_width = 36
    cd.clip_start = 0.05
    cd.clip_end = 400
    if focus is not None:
        cd.dof.use_dof = True
        cd.dof.focus_object = focus
        cd.dof.aperture_fstop = fstop
    o = _link(bpy.data.objects.new(name, cd))
    o.location = loc
    look_at(o, target)
    return o


def cam_key(cam, f, loc, target, lens=None):
    cam.location = loc
    look_at(cam, target)
    cam.keyframe_insert("location", frame=f)
    cam.keyframe_insert("rotation_euler", frame=f)
    if lens:
        cam.data.lens = lens
        cam.data.keyframe_insert("lens", frame=f)


def cut(frame, cam):
    CAM_CUTS.append((frame, cam))


# --------------------------------------------------------------------------
# Shared palette
# --------------------------------------------------------------------------
def palette():
    P = {}
    P["skin"] = mat("skin", "#e9b48f", rough=0.45, sss=0.25)
    P["blush"] = mat("blush", "#e8907a", rough=0.5, sss=0.2)
    P["hair"] = mat("hair", "#3b2416", rough=0.55, sheen=0.3)
    P["hoodie"] = mat("hoodie", "#e3a33b", rough=0.8, sheen=0.4)
    P["hoodie_dk"] = mat("hoodie_dk", "#b97a22", rough=0.85, sheen=0.4)
    P["jeans"] = mat("jeans", "#3e5c8a", rough=0.85, sheen=0.2)
    P["shoe"] = mat("shoe", "#f4f1ea", rough=0.5)
    P["sole"] = mat("sole", "#d0573f", rough=0.6)
    P["eye_white"] = mat("eye_white", "#fbf8f2", rough=0.15, coat=0.6)
    P["iris"] = mat("iris", "#5a8a3a", rough=0.25, coat=0.8)
    P["pupil"] = mat("pupil", "#0b0b0d", rough=0.2, coat=1.0)
    P["glint"] = glow("glint", "#ffffff", 6.0)
    P["brow"] = mat("brow", "#2e1b10", rough=0.6)
    P["mouth"] = mat("mouth", "#6b2a28", rough=0.5)
    P["glasses"] = mat("glasses", "#2a2a33", rough=0.3, coat=0.5)
    P["white"] = mat("white_soft", "#f3efe6", rough=0.5)
    P["ink"] = mat("ink", "#23252d", rough=0.5)
    P["wood"] = mat("wood", "#9b6a45", rough=0.55, coat=0.3)
    P["wood_dk"] = mat("wood_dk", "#5d3b26", rough=0.5, coat=0.3)
    P["phone"] = mat("phone_body", "#1d1f27", rough=0.25, coat=0.8)
    P["mug"] = mat("mug", "#e86f5a", rough=0.3, coat=0.6)
    P["mug2"] = mat("mug2", "#5fa8a0", rough=0.3, coat=0.6)
    P["mug3"] = mat("mug3", "#f2d15c", rough=0.3, coat=0.6)
    P["coffee"] = mat("coffee", "#3a2216", rough=0.1)
    P["steam"] = mat("steam", "#ffffff", rough=0.9)
    P["pot"] = mat("pot", "#d9785a", rough=0.6)
    P["soil"] = mat("soil", "#3b2a1e", rough=1.0)
    P["leaf"] = mat("leaf", "#4fa14a", rough=0.45, sss=0.2, sheen=0.2)
    P["leaf_dk"] = mat("leaf_dk", "#3c7d38", rough=0.45, sss=0.2)
    P["flower"] = mat("flower", "#ff7aa8", rough=0.4, sss=0.3)
    P["flower_c"] = mat("flower_c", "#ffd34d", rough=0.5)
    P["water"] = mat("water", "#8fd0ff", rough=0.05, coat=1.0)
    P["red"] = mat("notif_red", "#ff4b4b", rough=0.3)
    P["ui_white"] = mat("ui_white", "#ffffff", rough=0.35, emit="#ffffff", strength=0.35)
    P["ui_text"] = mat("ui_text", "#22252e", rough=0.5)
    P["ui_text_w"] = glow("ui_text_w", "#ffffff", 2.0)
    return P


# --------------------------------------------------------------------------
# Characters
# --------------------------------------------------------------------------
BASE_POSE = dict(
    root_loc=(0, 0, 0), root_rot=(0, 0, 0),
    spine=(0, 0, 0), head=(0, 0, 0),
    sh_L=(0, -8, 0), sh_R=(0, 8, 0), el_L=(-10, 0, 0), el_R=(-10, 0, 0),
    hip_L=(0, 0, 0), hip_R=(0, 0, 0), kn_L=(0, 0, 0), kn_R=(0, 0, 0),
    eyes=(0, 0, 0), lids=-38.0, brows=(0.0, 0.0), mouth="flat",
)
SIT = dict(BASE_POSE, hip_L=(-90, 0, -4), hip_R=(-90, 0, 4), kn_L=(88, 0, 0),
           kn_R=(88, 0, 0))


class Charlie:
    """Big-headed, big-eyed Pixar-ish 30-something in a mustard hoodie."""

    def __init__(self, P):
        self.P = P
        self.state = dict(BASE_POSE)
        s = self
        s.set = empty("Charlie_set")
        s.root = empty("Charlie_root", parent=s.set)
        # --- legs
        sphere("Ch_hips", (0.25, 0.21, 0.15), (0, 0, 0.55), P["jeans"], parent=s.root)
        s.hip_L = empty("Ch_hip_L", (0.12, 0, 0.52), parent=s.root)
        s.hip_R = empty("Ch_hip_R", (-0.12, 0, 0.52), parent=s.root)
        for side, hip in (("L", s.hip_L), ("R", s.hip_R)):
            sphere("Ch_thigh_" + side, (0.09, 0.09, 0.15), (0, 0, -0.11), P["jeans"],
                   parent=hip)
            knee = empty("Ch_knee_" + side, (0, 0, -0.24), parent=hip)
            sphere("Ch_shin_" + side, (0.078, 0.078, 0.14), (0, 0, -0.1), P["jeans"],
                   parent=knee)
            sphere("Ch_shoe_" + side, (0.085, 0.14, 0.065), (0, -0.05, -0.23),
                   P["shoe"], parent=knee)
            sphere("Ch_sole_" + side, (0.088, 0.142, 0.03), (0, -0.05, -0.268),
                   P["sole"], parent=knee)
            setattr(s, "kn_" + side, knee)
        # --- torso
        s.spine = empty("Ch_spine", (0, 0, 0.52), parent=s.root)
        sphere("Ch_torso", (0.3, 0.24, 0.37), (0, 0, 0.3), P["hoodie"], parent=s.spine)
        torus("Ch_hood", 0.16, 0.065, (0, 0.04, 0.62), P["hoodie_dk"], parent=s.spine,
              rot=(-12, 0, 0))
        for sx in (-0.05, 0.05):
            cylinder("Ch_string", 0.008, 0.008, 0.2, (sx, -0.2, 0.47), P["white"],
                     parent=s.spine, rot=(-25, 0, 0), segs=8)
        # --- arms
        for side, sx in (("L", 1), ("R", -1)):
            sh = empty("Ch_sh_" + side, (0.27 * sx, 0, 0.52), parent=s.spine)
            sphere("Ch_uarm_" + side, (0.075, 0.075, 0.14), (0, 0, -0.1), P["hoodie"],
                   parent=sh)
            el = empty("Ch_el_" + side, (0, 0, -0.22), parent=sh)
            sphere("Ch_farm_" + side, (0.066, 0.066, 0.13), (0, 0, -0.09), P["hoodie"],
                   parent=el)
            torus("Ch_cuff_" + side, 0.052, 0.022, (0, 0, -0.19), P["hoodie_dk"],
                  parent=el)
            sphere("Ch_hand_" + side, (0.062, 0.05, 0.068), (0, 0, -0.25), P["skin"],
                   parent=el)
            sphere("Ch_thumb_" + side, (0.024, 0.024, 0.04), (-0.045 * sx, -0.03, -0.24),
                   P["skin"], parent=el)
            hand = empty("Ch_handpt_" + side, (0, 0, -0.27), parent=el)
            setattr(s, "sh_" + side, sh)
            setattr(s, "el_" + side, el)
            setattr(s, "hand_" + side, hand)
        # --- head
        s.head = empty("Ch_head", (0, 0, 0.62), parent=s.spine)
        sphere("Ch_neck", (0.1, 0.1, 0.1), (0, 0, 0.02), P["skin"], parent=s.head)
        s.skull = sphere("Ch_skull", (0.36, 0.34, 0.36), (0, 0, 0.32), P["skin"],
                         parent=s.head)
        sphere("Ch_nose", (0.055, 0.05, 0.045), (0, -0.345, 0.24), P["skin"],
               parent=s.head)
        for sx in (-1, 1):
            sphere("Ch_ear", (0.035, 0.06, 0.075), (0.355 * sx, 0.02, 0.3), P["skin"],
                   parent=s.head)
            sphere("Ch_cheek", (0.06, 0.02, 0.035), (0.2 * sx, -0.285, 0.2),
                   P["blush"], parent=s.head)
        # hair: a soft cap plus a swoop of tufts
        sphere("Ch_hair_cap", (0.37, 0.36, 0.3), (0, 0.06, 0.44), P["hair"],
               parent=s.head)
        for i, (x, y, z, r) in enumerate([(-0.18, -0.2, 0.6, 0.13), (-0.04, -0.24, 0.63, 0.14),
                                          (0.1, -0.22, 0.64, 0.13), (0.22, -0.16, 0.58, 0.11),
                                          (0.0, -0.05, 0.72, 0.16), (-0.25, -0.05, 0.6, 0.12),
                                          (0.27, -0.03, 0.56, 0.11)]):
            sphere("Ch_tuft%d" % i, (r * 1.15, r, r * 0.8), (x, y, z), P["hair"],
                   parent=s.head, rot=(10, 0, 20 * (i % 3 - 1)))
        # eyes (eyeball pivots at their centres -> rotate to look around)
        s.eyes, s.lids, s.brows = [], [], []
        for side, sx in (("L", 1), ("R", -1)):
            ex, ey, ez = 0.13 * sx, -0.265, 0.33
            eye = empty("Ch_eye_" + side, (ex, ey, ez), parent=s.head)
            sphere("Ch_eyeball_" + side, 0.088, (0, 0, 0), P["eye_white"], parent=eye)
            sphere("Ch_iris_" + side, (0.05, 0.02, 0.05), (0, -0.078, 0), P["iris"],
                   parent=eye)
            sphere("Ch_pupil_" + side, (0.027, 0.012, 0.027), (0, -0.092, 0), P["pupil"],
                   parent=eye)
            sphere("Ch_glint_" + side, 0.011, (0.018 * sx, -0.097, 0.022), P["glint"],
                   parent=eye)
            lid_piv = empty("Ch_lidp_" + side, (ex, ey, ez), parent=s.head)
            hemisphere("Ch_lid_" + side, 0.113, (0, 0, 0), P["skin"], parent=lid_piv)
            brow = empty("Ch_brow_" + side, (0.13 * sx, -0.33, 0.475), parent=s.head)
            sphere("Ch_browm_" + side, (0.075, 0.025, 0.022), (0, 0, 0), P["brow"],
                   parent=brow, rot=(-20, 0, 0))
            s.eyes.append(eye)
            s.lids.append(lid_piv)
            s.brows.append(brow)
        # glasses
        for sx in (-1, 1):
            torus("Ch_lens_rim", 0.105, 0.009, (0.13 * sx, -0.395, 0.33), P["glasses"],
                  parent=s.head, rot=(90, 0, 0))
            cylinder("Ch_temple", 0.008, 0.008, 0.36, (0.24 * sx, -0.22, 0.35),
                     P["glasses"], parent=s.head, rot=(90, 0, 0), segs=8)
        cylinder("Ch_bridge", 0.008, 0.008, 0.06, (0, -0.405, 0.35), P["glasses"],
                 parent=s.head, rot=(0, 90, 0), segs=8)
        # mouths: swapped by visibility
        mloc = (0, -0.318, 0.135)
        s.mouths = {
            "flat": curve_line("Ch_m_flat", [(-0.06, 0.012, 0.0), (0, 0, -0.004),
                                             (0.06, 0.012, 0.0)], 0.011, mloc,
                               P["mouth"], s.head),
            "smile": curve_line("Ch_m_smile", [(-0.085, 0.03, 0.03), (0, 0, -0.022),
                                               (0.085, 0.03, 0.03)], 0.013, mloc,
                                P["mouth"], s.head),
            "frown": curve_line("Ch_m_frown", [(-0.06, 0.015, -0.02), (0, 0, 0.008),
                                               (0.06, 0.015, -0.02)], 0.011, mloc,
                                P["mouth"], s.head),
        }
        o_g = empty("Ch_m_o", (0, -0.312, 0.12), parent=s.head)
        sphere("Ch_m_o_in", (0.035, 0.02, 0.042), (0, 0, 0), P["mouth"], parent=o_g)
        s.mouths["o"] = o_g
        grin = empty("Ch_m_grin", (0, -0.31, 0.135), parent=s.head)
        sphere("Ch_m_grin_in", (0.075, 0.02, 0.04), (0, 0, -0.012), P["mouth"],
               parent=grin)
        sphere("Ch_m_grin_teeth", (0.062, 0.02, 0.016), (0, -0.006, 0.006), P["white"],
               parent=grin)
        s.mouths["grin"] = grin
        # head-follow empty for camera focus
        s.focus = empty("Ch_focus", (0, -0.3, 0.33), parent=s.head)
        # props in hands
        s.phone = empty("Ch_phone", (0, -0.035, -0.05), (0, 0, 0), parent=s.hand_R)
        box("Ch_phone_body", (0.085, 0.014, 0.165), (0, 0, -0.04), P["phone"],
            bevel=0.012, parent=s.phone)
        s.phone_screen_mat = glow("ch_phone_screen", "#9ad1ff", 3.0, lights=True)
        box("Ch_phone_screen", (0.074, 0.002, 0.15), (0, -0.0075, -0.04),
            s.phone_screen_mat, bevel=0, parent=s.phone)
        s.phone_light = point_light("Ch_phone_light", (0, 0, 0), 2.0, "#a8d8ff", 0.05)
        s.phone_light.parent = s.phone
        s.phone_light.location = (0, -0.12, -0.04)
        s.mug = empty("Ch_mug", (0.0, -0.075, -0.03), (110, 0, 0), parent=s.hand_L)
        make_mug("Ch_mugm", s.mug, P["mug"], P, steam=True)

    # ---------------------------------------------------------------- posing
    def place(self, f, loc, rot_z=0.0):
        key(self.set, "location", f, loc, interp="CONSTANT")
        key(self.set, "rotation_euler", f, (0, 0, rot_z), interp="CONSTANT")

    def pose(self, f, preset=None, **kw):
        if preset is not None:
            self.state = dict(preset)
        self.state.update(kw)
        st = self.state
        key(self.root, "location", f, st["root_loc"])
        key(self.root, "rotation_euler", f, st["root_rot"])
        for n in ("spine", "head", "sh_L", "sh_R", "el_L", "el_R", "hip_L", "hip_R",
                  "kn_L", "kn_R"):
            key(getattr(self, n), "rotation_euler", f, st[n])
        for e in self.eyes:
            key(e, "rotation_euler", f, st["eyes"])
        for lp in self.lids:
            key(lp, "rotation_euler", f, (st["lids"], 0, 0))
        raise_, sad = st["brows"]
        for b, sx in zip(self.brows, (1, -1)):
            key(b, "location", f, (0.13 * sx, -0.33 + 0.004 * raise_, 0.475 + 0.035 * raise_))
            key(b, "rotation_euler", f, (0, 16 * sad * sx, 0))
        self._mouth(f, st["mouth"])

    def _mouth(self, f, which):
        for n, o in self.mouths.items():
            show(o, f, n == which)

    def blink(self, f):
        cur = self.state["lids"]
        for lp in self.lids:
            key(lp, "rotation_euler", f - 2, (cur, 0, 0))
            key(lp, "rotation_euler", f, (92, 0, 0))
            key(lp, "rotation_euler", f + 3, (cur, 0, 0))

    def talk(self, f0, f1, period=5):
        f = f0
        shapes = ["o", "flat", "grin", "flat", "o", "smile"]
        i = 0
        while f < f1:
            self._mouth(f, shapes[i % len(shapes)])
            f += period
            i += 1
        self._mouth(f1, self.state["mouth"])

    def walk(self, f0, f1, p0, p1, step=12, **extra):
        n = max(1, round((f1 - f0) / (step / 2)))
        for i in range(n + 1):
            t = i / n
            f = round(f0 + (f1 - f0) * t)
            loc = tuple(a + (b - a) * t for a, b in zip(p0, p1))
            ph = 1 if i % 2 else -1
            if i == n:
                ph = 0
            bob = 0.03 if (i % 2 == 0 and 0 < i < n) else 0.0
            self.pose(f, root_loc=(loc[0], loc[1], loc[2] + bob),
                      hip_L=(-24 * ph, 0, 0), hip_R=(24 * ph, 0, 0),
                      kn_L=(18 if ph < 0 else 4, 0, 0), kn_R=(18 if ph > 0 else 4, 0, 0),
                      spine=(6 if ph else 0, 0, 3 * ph), **extra)


def make_mug(name, parent, m, P, steam=False, loc=(0, 0, 0)):
    g = empty(name, loc, parent=parent)
    cylinder(name + "_body", 0.052, 0.056, 0.11, (0, 0, 0.055), m, parent=g)
    cylinder(name + "_coffee", 0.047, 0.047, 0.004, (0, 0, 0.1), P["coffee"],
             parent=g)
    torus(name + "_handle", 0.032, 0.011, (0.062, 0, 0.055), m, parent=g,
          rot=(90, 0, 0))
    if steam:
        for i in range(3):
            puff = sphere(name + "_steam%d" % i, 0.02, (0.012 * (i - 1), 0, 0.14),
                          P["steam"], parent=g)
            for c in range(0, FRAME_END + 40, 36):
                f0 = c + i * 12
                key(puff, "location", f0, (0.012 * (i - 1), 0, 0.12), interp="LINEAR")
                key(puff, "scale", f0, (0.001,) * 3, interp="LINEAR")
                key(puff, "scale", f0 + 12, (0.03,) * 3, interp="LINEAR")
                key(puff, "location", f0 + 35, (0.03 * (i - 1) + 0.01, 0, 0.36),
                    interp="LINEAR")
                key(puff, "scale", f0 + 35, (0.001,) * 3, interp="LINEAR")
    return g


def make_plant(name, loc, P, parent=None, scale=1.0, n=7):
    g = empty(name, loc, parent=parent)
    g.scale = (scale,) * 3
    cylinder(name + "_pot", 0.1, 0.13, 0.2, (0, 0, 0.1), P["pot"], parent=g)
    torus(name + "_rim", 0.13, 0.018, (0, 0, 0.2), P["pot"], parent=g)
    cylinder(name + "_soil", 0.12, 0.12, 0.01, (0, 0, 0.19), P["soil"], parent=g)
    leaves = []
    for i in range(n):
        spin = empty(name + "_spin%d" % i, (0, 0, 0.19), (0, 0, i * 360 / n + 13 * (i % 2)),
                     parent=g)
        piv = empty(name + "_leafp%d" % i, (0, -0.02, 0), (18 + 6 * (i % 3), 0, 0),
                    parent=spin)
        L = 0.15 + 0.03 * (i % 3)
        cylinder(name + "_stem%d" % i, 0.006, 0.006, L * 0.8, (0, 0, L * 0.4),
                 P["leaf_dk"], parent=piv, segs=8)
        sphere(name + "_leaf%d" % i, (0.055, 0.014, L * 0.55), (0, -0.01, L * 1.05),
               P["leaf"] if i % 2 else P["leaf_dk"], parent=piv, rot=(-10, 0, 0))
        leaves.append(piv)
    flower = empty(name + "_flower", (0, 0, 0.45), parent=g)
    for k in range(5):
        a = k * 72
        sphere(name + "_petal%d" % k, (0.035, 0.015, 0.022),
               (0.035 * math.cos(R(a)), 0.035 * math.sin(R(a)), 0), P["flower"],
               parent=flower, rot=(0, 0, a))
    sphere(name + "_fc", 0.022, (0, 0, 0.005), P["flower_c"], parent=flower)
    cylinder(name + "_fstem", 0.006, 0.006, 0.26, (0, 0, -0.13), P["leaf_dk"],
             parent=flower, segs=8)
    flower.scale = (0.001,) * 3
    return g, leaves, flower


def droop(leaves, f, amount, jitter=True):
    """amount 0 = perky, 1 = fully wilted."""
    for i, lp in enumerate(leaves):
        up = 18 + 6 * (i % 3)
        down = 105 + 10 * (i % 2)
        key(lp, "rotation_euler", f, (up + (down - up) * amount, 0, 0))


class Neighbour:
    """Tiny backlit silhouette for windows across the street."""

    def __init__(self, name, loc, m, rot_z=0, scale=1.0, phone=False):
        self.g = empty(name, loc, (0, 0, rot_z))
        self.g.scale = (scale,) * 3
        sphere(name + "_body", (0.28, 0.2, 0.42), (0, 0, 0.45), m, parent=self.g)
        sphere(name + "_head", 0.25, (0, 0, 1.05), m, parent=self.g)
        self.arm = empty(name + "_arm", (-0.27, 0, 0.75), (0, 20, 0), parent=self.g)
        sphere(name + "_arm_m", (0.07, 0.07, 0.25), (0, 0, -0.2), m, parent=self.arm)
        if phone:
            sphere(name + "_phone", (0.06, 0.02, 0.09), (0.0, -0.32, 0.85),
                   glow("nb_phone", "#9ad1ff", 8.0), parent=self.g)


# --------------------------------------------------------------------------
# Room shell
# --------------------------------------------------------------------------
def wall_with_hole(name, axis, plane, span, height, hole, m, thick=0.12, parent=None):
    """axis 'y' -> wall in XZ plane at y=plane; axis 'x' -> wall in YZ plane at x=plane.
    span=(u0,u1) horizontal range; hole=(u0,u1,v0,v1) or None."""
    u0, u1 = span
    pieces = []
    if hole is None:
        pieces.append((u0, u1, 0, height))
    else:
        h0, h1, v0, v1 = hole
        pieces += [(u0, u1, 0, v0), (u0, u1, v1, height), (u0, h0, v0, v1),
                   (h1, u1, v0, v1)]
    objs = []
    for i, (a, b, c, d) in enumerate(pieces):
        if b - a < 1e-3 or d - c < 1e-3:
            continue
        cu, cv = (a + b) / 2, (c + d) / 2
        if axis == "y":
            o = box("%s_%d" % (name, i), (b - a, thick, d - c), (cu, plane, cv), m,
                    bevel=0, parent=parent)
        else:
            o = box("%s_%d" % (name, i), (thick, b - a, d - c), (plane, cu, cv), m,
                    bevel=0, parent=parent)
        objs.append(o)
    return objs


def window_frame(name, axis, plane, hole, m, parent=None, mullions=True):
    h0, h1, v0, v1 = hole
    t, dpt = 0.07, 0.2
    parts = [((h0 + h1) / 2, v0 - t / 2 + 0.02, h1 - h0 + 2 * t, t * 1.4),  # sill
             ((h0 + h1) / 2, v1, h1 - h0 + 2 * t, t),
             (h0, (v0 + v1) / 2, t, v1 - v0), (h1, (v0 + v1) / 2, t, v1 - v0)]
    if mullions:
        parts += [((h0 + h1) / 2, (v0 + v1) / 2, 0.04, v1 - v0)]
    for i, (u, v, w, h) in enumerate(parts):
        if axis == "y":
            box("%s_%d" % (name, i), (w, dpt, h), (u, plane, v), m, bevel=0.01,
                parent=parent)
        else:
            box("%s_%d" % (name, i), (dpt, w, h), (plane, u, v), m, bevel=0.01,
                parent=parent)


def room(ox, wall_m, floor_m, w=7.0, d=6.0, h=3.2, back_hole=None, left_hole=None,
         right_hole=None, left=True, right=True, trim_m=None):
    g = empty("room_%d" % ox, (ox, 0, 0))
    box("floor_%d" % ox, (w, d, 0.1), (0, 0, -0.05), floor_m, bevel=0, parent=g)
    box("ceiling_%d" % ox, (w, d, 0.1), (0, 0, h + 0.05), wall_m, bevel=0, parent=g)
    wall_with_hole("back_%d" % ox, "y", d / 2, (-w / 2, w / 2), h, back_hole, wall_m,
                   parent=g)
    if left:
        wall_with_hole("left_%d" % ox, "x", -w / 2, (-d / 2, d / 2), h, left_hole,
                       wall_m, parent=g)
    if right:
        wall_with_hole("right_%d" % ox, "x", w / 2, (-d / 2, d / 2), h, right_hole,
                       wall_m, parent=g)
    tm = trim_m or mat("trim", "#f6f1e7", rough=0.5)
    box("base_back_%d" % ox, (w, 0.03, 0.12), (0, d / 2 - 0.07, 0.06), tm, bevel=0,
        parent=g)
    return g


# --------------------------------------------------------------------------
# World (sky) with keyable colours
# --------------------------------------------------------------------------
class Sky:
    def __init__(self):
        w = bpy.data.worlds.new("Sky")
        bpy.context.scene.world = w
        try:
            w.use_nodes = True
        except Exception:
            pass
        nt = w.node_tree
        for n in list(nt.nodes):
            nt.nodes.remove(n)
        tc = nt.nodes.new("ShaderNodeTexCoord")
        sep = nt.nodes.new("ShaderNodeSeparateXYZ")
        mr = nt.nodes.new("ShaderNodeMapRange")
        mr.inputs["From Min"].default_value = -0.05
        mr.inputs["From Max"].default_value = 0.6
        self.hor = nt.nodes.new("ShaderNodeRGB")
        self.zen = nt.nodes.new("ShaderNodeRGB")
        mix = nt.nodes.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        bg = nt.nodes.new("ShaderNodeBackground")
        out = nt.nodes.new("ShaderNodeOutputWorld")
        nt.links.new(tc.outputs["Generated"], sep.inputs[0])
        nt.links.new(sep.outputs["Z"], mr.inputs["Value"])
        ins = {i.identifier: i for i in mix.inputs}
        outs = {o.identifier: o for o in mix.outputs}
        nt.links.new(mr.outputs[0], ins["Factor_Float"])
        nt.links.new(self.hor.outputs[0], ins["A_Color"])
        nt.links.new(self.zen.outputs[0], ins["B_Color"])
        nt.links.new(outs["Result_Color"], bg.inputs["Color"])
        nt.links.new(bg.outputs[0], out.inputs["Surface"])
        self.strength = bg.inputs["Strength"]

    def at(self, f, horizon, zenith, strength, interp="CONSTANT"):
        key_socket(self.hor.outputs[0], f, (*srgb(horizon), 1), interp)
        key_socket(self.zen.outputs[0], f, (*srgb(zenith), 1), interp)
        key_socket(self.strength, f, strength, interp)


# ==========================================================================
# SETS + ANIMATION
# ==========================================================================
def build_title(P, s, length, title, subtitle, name):
    new_collection(name)
    ox = OX[name]
    bg = glow(name + "_bg", "#f4b183", 1.0)
    box(name + "_backdrop", (30, 0.1, 18), (ox, 6, 2), bg, bevel=0)
    cam = camera(name + "_cam", (ox, -9, 1.6), (ox, 0, 1.6), lens=50)
    cut(s, cam)
    title_m = glow(name + "_title", "#3a2140", 1.0)
    sub_m = glow(name + "_sub", "#6e3d52", 1.0)
    lines = subtitle.split("\n")
    t = text(name + "_t", title, (ox, 0, 2.0 if len(lines) == 1 else 2.55), 1.0, title_m)
    pop(t, s + 6, 10)
    for i, line in enumerate(lines):
        st = text(name + "_s%d" % i, line, (ox, 0, (1.15 if len(lines) == 1 else 1.55) - i * 0.4),
                  0.22 if len(lines) > 1 else 0.34, sub_m, bold=False)
        pop(st, s + 24 + i * 18, 10)
    # little floating dots
    for i in range(14):
        a = i * 2.39996
        rr = 2.2 + 1.6 * ((i * 37) % 10) / 10
        d = sphere(name + "_dot%d" % i, 0.06 + 0.04 * (i % 3),
                   (ox + rr * math.cos(a) * 1.4, 1.5, 1.6 + rr * math.sin(a) * 0.7),
                   glow(name + "_dotm%d" % (i % 3), ["#ffd27f", "#ff9a8b", "#fff1d6"][i % 3],
                        1.2))
        key(d, "location", s, d.location)
        key(d, "location", s + length, (d.location.x, d.location.y, d.location.z + 0.4))
    return cam


def build_bed(P, C, sky, s):
    new_collection("bed")
    ox = OX["bed"]
    wall = mat("bed_wall", "#6f84b0", rough=0.9)
    floor = mat("bed_floor", "#8a5a3c", rough=0.6, coat=0.2)
    rg = room(ox, wall, floor, back_hole=(-2.4, -1.0, 1.1, 2.5))
    window_frame("bed_win", "y", 3.0, (-2.4, -1.0, 1.1, 2.5), P["white"], parent=rg)
    # blinds (closed) glowing blue-ish at the edges
    for i in range(12):
        box("bed_blind%d" % i, (1.4, 0.03, 0.105), (ox - 1.7, 2.9, 2.45 - i * 0.115),
            mat("blind", "#e8e2d6", rough=0.6), bevel=0.0)
    area_light("bed_moon", (ox - 1.7, 4.5, 2.0), (ox - 0.5, 0.5, 0.8), 120, "#7fa0ff",
               size=1.4)
    # bed
    box("bed_frame", (2.5, 1.8, 0.35), (ox - 0.15, 1.0, 0.25), P["wood"], bevel=0.04)
    box("bed_mattress", (2.35, 1.65, 0.25), (ox - 0.15, 1.0, 0.55), P["white"], bevel=0.08)
    box("bed_head", (0.14, 1.9, 1.15), (ox + 1.12, 1.0, 0.62),
        mat("velvet", "#c9a24a", rough=0.8, sheen=0.8), bevel=0.06)
    box("bed_pillow", (0.5, 0.85, 0.2), (ox + 0.78, 1.0, 0.76), P["white"], bevel=0.09)
    box("bed_duvet", (1.85, 1.75, 0.62), (ox - 0.45, 0.98, 0.98),
        mat("duvet", "#d47a5b", rough=0.85, sheen=0.6), bevel=0.26, segs=5)
    # nightstand + lamp + glass of water
    box("bed_ns", (0.55, 0.5, 0.6), (ox + 1.55, 0.7, 0.3), P["wood_dk"], bevel=0.03)
    cylinder("bed_lamp_base", 0.08, 0.1, 0.3, (ox + 1.6, 0.8, 0.75), P["mug3"])
    cylinder("bed_lamp_shade", 0.2, 0.13, 0.22, (ox + 1.6, 0.8, 1.0),
             mat("shade", "#fff4dc", rough=0.7, emit="#ffd9a0", strength=0.0))
    # phone (on the duvet, by the face)
    ph = empty("bed_phone", (ox + 0.38, 0.42, 1.27), (14, 0, -18))
    box("bed_phone_body", (0.09, 0.17, 0.014), (0, 0, 0), P["phone"], bevel=0.012,
        parent=ph)
    scr = glow("bed_phone_scr", "#bfe3ff", 0.0)
    box("bed_phone_scr", (0.078, 0.155, 0.002), (0, 0, 0.0075), scr, bevel=0, parent=ph)
    t1 = text("bed_t647", "6:47", (0, 0.02, 0.01), 0.04, P["ui_text"], rot=(0, 0, 0),
              parent=ph)
    t2 = text("bed_t712", "7:12", (0, 0.02, 0.01), 0.04, mat("late", "#e02424"),
              rot=(0, 0, 0), parent=ph)
    pl = point_light("bed_phone_light", (ox + 0.38, 0.3, 1.45), 0.0, "#bfe3ff", 0.08)
    sky.at(s, "#1b2440", "#0b1022", 0.15)

    f = s
    C.place(f, (ox, 0, 0))
    lying = dict(BASE_POSE, root_loc=(-0.84, 0.98, 1.0), root_rot=(0, 90, 0),
                 lids=92, mouth="flat", head=(0, -6, 0), sh_R=(-20, -6, 0), el_R=(-30, 0, 0),
                 sh_L=(0, -10, 0), hip_L=(-30, 0, 0), hip_R=(-35, 0, 0), kn_L=(40, 0, 0),
                 kn_R=(45, 0, 0))
    C.pose(f, lying)
    show(C.phone, f, False)
    show(C.mug, f, False)
    show(t1, f, False)
    show(t2, f, False)
    # breathing
    for k in range(f + 6, f + 90, 24):
        C.pose(k, spine=(0, 0, 0))
        C.pose(k + 12, spine=(3, 0, 0))

    def buzz(f0, f1, txt):
        key_socket(glow_strength(scr), f0 - 1, 0.0)
        key_socket(glow_strength(scr), f0, 3.0)
        key_prop(pl.data, "energy", f0 - 1, 0.0)
        key_prop(pl.data, "energy", f0, 18.0)
        show(txt, f0, True)
        for k in range(f0, f1, 2):
            key(ph, "rotation_euler", k, (14, 0, -18 + (4 if (k // 2) % 2 else -4)),
                interp="CONSTANT")
            key(ph, "location", k, (ox + 0.38 + (0.006 if (k // 2) % 2 else -0.006),
                                    0.42, 1.27), interp="CONSTANT")
        key(ph, "rotation_euler", f1, (14, 0, -18), interp="CONSTANT")
        key(ph, "location", f1, (ox + 0.38, 0.42, 1.27), interp="CONSTANT")

    def dark(f0, txt):
        key_socket(glow_strength(scr), f0 - 1, 3.0)
        key_socket(glow_strength(scr), f0, 0.0)
        key_prop(pl.data, "energy", f0 - 1, 18.0)
        key_prop(pl.data, "energy", f0, 0.0)
        show(txt, f0, False)

    buzz(f + 14, f + 64, t1)
    C.pose(f + 28, brows=(-0.4, 0.6), mouth="frown")           # ugh.
    C.pose(f + 44, sh_R=(-150, 40, 0), el_R=(-35, 0, 0))        # arm emerges
    C.pose(f + 58, sh_R=(-165, 55, 0), el_R=(-25, 0, 0))        # slaps phone
    dark(f + 64, t1)
    C.pose(f + 70, sh_R=(-168, 52, 0), el_R=(-20, 0, 0))
    C.pose(f + 88, sh_R=(-168, 52, 0), brows=(0, 0), mouth="smile")  # snooze bliss
    for k in range(f + 92, f + 132, 22):
        C.pose(k, spine=(2, 0, 0))
        C.pose(k + 11, spine=(0, 0, 0))
    # 25 minutes later...
    buzz(f + 134, f + 175, t2)
    C.pose(f + 140, lids=30, eyes=(12, 0, 25), brows=(0.4, 0), mouth="flat")
    C.pose(f + 150, lids=30)
    C.pose(f + 156, lids=-70, brows=(1.4, -0.3), mouth="o", head=(0, -14, 0),
           eyes=(15, 0, 30))                                      # !!!
    C.pose(f + 200, lids=-72, brows=(1.5, -0.3), mouth="o", head=(-6, -18, 0))
    C.pose(f + 215, lids=-72, brows=(1.5, -0.3))

    cam = camera("bed_cam", (ox + 0.25, -1.55, 1.75), (ox + 0.45, 0.9, 1.05), lens=42,
                 focus=C.focus, fstop=2.2)
    cam_key(cam, f, (ox + 0.25, -1.55, 1.75), (ox + 0.45, 0.9, 1.05))
    cam_key(cam, f + 150, (ox + 0.32, -1.2, 1.62), (ox + 0.5, 0.9, 1.08))
    cam_key(cam, f + 160, (ox + 0.4, -0.75, 1.5), (ox + 0.55, 0.9, 1.1))  # snap zoom
    cam_key(cam, f + 215, (ox + 0.4, -0.7, 1.5), (ox + 0.55, 0.9, 1.1))
    cut(f, cam)
    return dark


def notification(name, label, dot_col, loc, P, w=1.25, parent=None):
    g = empty(name, loc, parent=parent)
    pill(name + "_bg", w, 0.22, 0.04, (0, 0, 0), P["ui_white"], parent=g)
    sphere(name + "_dot", (0.055, 0.02, 0.055), (-w / 2 + 0.14, -0.025, 0),
           mat("dot_" + dot_col, dot_col, rough=0.3), parent=g)
    text(name + "_t", label, (-w / 2 + 0.24, -0.03, -0.005), 0.085, P["ui_text"],
         align="LEFT", parent=g, bold=False)
    g.scale = (0.001,) * 3
    return g


def build_kitchen(P, C, sky, s):
    new_collection("kitchen")
    ox = OX["kitchen"]
    wall = mat("k_wall", "#a8d8c8", rough=0.9)
    floor = mat("k_floor", "#e9dcc6", rough=0.4, coat=0.2)
    rg = room(ox, wall, floor, back_hole=(-2.9, -1.3, 1.25, 2.5))
    window_frame("k_win", "y", 3.0, (-2.9, -1.3, 1.25, 2.5), P["white"], parent=rg)
    area_light("k_sun", (ox - 2.1, 5.0, 3.5), (ox, 0.5, 0.8), 900, "#ffe2b8", size=2.0)
    area_light("k_fill", (ox + 1.5, -3.0, 3.0), (ox, 0.5, 1.2), 260, "#cfe6ff", size=3.0)
    navy = mat("k_cab", "#2f4058", rough=0.5, coat=0.2)
    top = mat("k_top", "#f5f2ec", rough=0.25, coat=0.4)
    # island
    box("k_island", (2.6, 0.85, 0.9), (ox, -0.2, 0.45), navy, bevel=0.03)
    box("k_island_top", (2.75, 0.98, 0.06), (ox, -0.2, 0.93), top, bevel=0.02)
    # back counter + upper cabinets + fridge
    box("k_back", (4.6, 0.65, 0.9), (ox + 0.6, 2.62, 0.45), navy, bevel=0.03)
    box("k_back_top", (4.7, 0.7, 0.06), (ox + 0.6, 2.62, 0.93), top, bevel=0.02)
    for i in range(3):
        box("k_upper%d" % i, (0.95, 0.4, 0.75), (ox + 0.0 + i * 1.0, 2.78, 2.2), navy,
            bevel=0.03)
        cylinder("k_knob%d" % i, 0.018, 0.018, 0.03, (ox + 0.35 + i * 1.0, 2.56, 1.95),
                 P["white"], rot=(90, 0, 0), segs=12)
    box("k_fridge", (1.0, 0.9, 2.1), (ox + 3.0, 2.4, 1.05), mat("fridge", "#f7c9b6",
                                                                  rough=0.3, coat=0.5),
        bevel=0.08)
    # coffee machine
    box("k_coffee", (0.35, 0.35, 0.45), (ox + 1.4, 2.6, 1.2), mat("cm", "#1f1f24",
                                                                  rough=0.3, metal=0.3))
    # pendant lamps
    for i, x in enumerate((-0.7, 0.7)):
        cylinder("k_cord%d" % i, 0.006, 0.006, 0.9, (ox + x, -0.2, 2.75), P["ink"], segs=8)
        cylinder("k_pend%d" % i, 0.08, 0.22, 0.2, (ox + x, -0.2, 2.2),
                 mat("pend", "#f2c14e", rough=0.4, coat=0.3))
        point_light("k_pl%d" % i, (ox + x, -0.2, 2.05), 40, "#ffc98a", 0.12)
    # island props: fruit bowl, keys, mail
    cylinder("k_bowl", 0.18, 0.12, 0.1, (ox - 0.85, -0.25, 1.01), P["white"])
    for i, (dx, dy, c) in enumerate([(0, 0, "#ff8c42"), (0.08, 0.06, "#ffd34d"),
                                     (-0.07, 0.05, "#e84a5f")]):
        sphere("k_fruit%d" % i, 0.065, (ox - 0.85 + dx, -0.25 + dy, 1.1),
               mat("fruit%d" % i, c, rough=0.35, coat=0.4))
    # wall clock
    cylinder("k_clock", 0.26, 0.26, 0.05, (ox - 0.1, 2.93, 2.0), P["white"], rot=(90, 0, 0))
    torus("k_clock_rim", 0.26, 0.025, (ox - 0.1, 2.92, 2.0), P["ink"], rot=(90, 0, 0))
    text("k_clock_t", "7:58", (ox - 0.1, 2.89, 2.0), 0.15, P["ui_text"])
    sky.at(s, "#ffe7c4", "#9cc8ff", 0.6)

    f = s
    C.place(f, (ox, 0, 0))
    hold = dict(BASE_POSE, root_loc=(0, 0.6, 0),
                sh_R=(-18, 0, 12), el_R=(-100, 0, 8),
                sh_L=(-14, 0, -14), el_L=(-96, 0, -8),
                head=(22, 0, 0), eyes=(16, 0, 0), lids=-12, mouth="flat", brows=(0, 0.2))
    C.pose(f, hold)
    show(C.phone, f, True)
    show(C.mug, f, True)
    key_socket(glow_strength(C.phone_screen_mat), f, 3.0, "CONSTANT")
    key_prop(C.phone_light.data, "energy", f, 2.0, "CONSTANT")
    C.blink(f + 14)
    notes = [("Slack  -  23 new messages", "#8e44ad", (-1.05, 0.2, 2.05)),
             ("Email  -  47 unread", "#2d7ff9", (1.0, 0.2, 2.15)),
             ("Calendar  -  9:00 Stand-up", "#27ae60", (-1.1, 0.2, 2.42)),
             ("Bank  -  Rent due Friday", "#e67e22", (1.05, 0.2, 2.52)),
             ("Group chat  -  112 messages", "#16a085", (-0.95, 0.2, 2.79)),
             ("Mom  -  Call me when u can", "#e84a5f", (1.0, 0.2, 2.89)),
             ("Weather  -  73\u00b0 and sunny", "#f1c40f", (0.0, 0.2, 3.12))]
    gaps = [26, 16, 13, 11, 9, 8, 7]
    nf = f + 22
    groups = []
    for i, (lbl, col, (x, y, z)) in enumerate(notes):
        g = notification("k_note%d" % i, lbl, col, (ox + x, y - 0.2, z - 0.55), P)
        pop(g, nf, 7)
        groups.append(g)
        nf += gaps[i]
    # reactions
    C.pose(f + 24, lids=-30, brows=(0.4, 0), head=(14, 0, 0))
    C.pose(f + 48, lids=-40, eyes=(0, 0, 18), head=(8, 0, 10))
    C.pose(f + 66, lids=-50, eyes=(-10, 0, -15), head=(4, 0, -10), brows=(0.9, 0))
    C.pose(f + 90, lids=-66, eyes=(-14, 0, 0), head=(-4, 0, 0), brows=(1.4, -0.2),
           mouth="o", spine=(-4, 0, 0))
    C.pose(f + 110, lids=-66)
    # the big sigh
    C.pose(f + 128, lids=10, brows=(-0.2, 0.9), mouth="frown", spine=(12, 0, 0),
           head=(22, 0, 0), sh_R=(-10, 0, 10), el_R=(-95, 0, 8), sh_L=(-8, 0, -12),
           el_L=(-90, 0, -8), root_loc=(0, 0.6, -0.04))
    C.pose(f + 150, lids=8)
    # sip of coffee
    C.pose(f + 166, sh_L=(-48, 0, -20), el_L=(-118, 0, -10), head=(-6, 0, 0), spine=(4, 0, 0),
           lids=40, mouth="flat", root_loc=(0, 0.6, 0))
    C.pose(f + 186, sh_L=(-48, 0, -20), el_L=(-118, 0, -10), lids=50,
           brows=(0.2, -0.2), mouth="smile")
    C.pose(f + 204, sh_L=(-14, 0, -14), el_L=(-96, 0, -8), head=(16, 0, 0), lids=-20,
           mouth="flat", brows=(0, 0.3), eyes=(14, 0, 0))
    for g in groups:
        unpop(g, f + 150 + groups.index(g) * 2, 6)

    cam = camera("k_cam", (ox, -3.4, 1.8), (ox, 0.6, 1.75), lens=36, focus=C.focus,
                 fstop=3.5)
    cam_key(cam, f, (ox, -3.4, 1.85), (ox, 0.6, 1.95))
    cam_key(cam, f + 120, (ox, -2.9, 1.8), (ox, 0.6, 1.8))
    cam_key(cam, f + 125, (ox + 0.05, -2.0, 1.3), (ox, 0.6, 1.4))  # punch in on sigh
    cam_key(cam, f + 215, (ox + 0.12, -1.85, 1.3), (ox, 0.6, 1.4))
    cut(f, cam)


def build_desk(P, C, sky, s):
    new_collection("desk")
    ox = OX["desk"]
    wall = mat("d_wall", "#efe2c8", rough=0.9)
    floor = mat("d_floor", "#a8744e", rough=0.55, coat=0.2)
    rg = room(ox, wall, floor, left_hole=(-1.6, 0.6, 1.0, 2.5))
    window_frame("d_win", "x", -3.5, (-1.6, 0.6, 1.0, 2.5), P["white"], parent=rg)
    sun = area_light("d_sun", (ox - 5.5, -0.5, 2.6), (ox, 0.4, 0.8), 1400, "#fff2dc",
                     size=2.0)
    fill = area_light("d_fill", (ox + 1.0, -3.0, 2.6), (ox, 0.5, 1.2), 160, "#d6e6ff",
                      size=3.0)
    # desk
    box("d_top", (1.9, 0.85, 0.05), (ox, -0.1, 0.75), P["wood"], bevel=0.015)
    for sx in (-0.88, 0.88):
        for sy in (-0.45, 0.25):
            cylinder("d_leg", 0.025, 0.025, 0.73, (ox + sx, sy, 0.37), P["ink"], segs=12)
    # chair
    chair = mat("chair", "#3c3f4a", rough=0.6)
    box("d_seat", (0.6, 0.58, 0.09), (ox, 0.62, 0.45), chair, bevel=0.04)
    box("d_back", (0.6, 0.09, 0.75), (ox, 0.95, 0.9), chair, bevel=0.04)
    cylinder("d_post", 0.035, 0.035, 0.38, (ox, 0.62, 0.21), P["ink"], segs=12)
    # laptop: base + lid (lid faces Charlie at +Y)
    box("d_lap_base", (0.42, 0.29, 0.02), (ox, -0.08, 0.785), mat("alu", "#c9ccd3",
                                                                    rough=0.25, metal=0.8))
    lid = empty("d_lid", (ox, -0.225, 0.795), (-12, 0, 0))
    box("d_lid_m", (0.42, 0.015, 0.29), (0, 0, 0.145), mat("alu", "#c9ccd3"), parent=lid)
    sticker = sphere("d_sticker", (0.04, 0.004, 0.04), (0.08, -0.009, 0.17),
                     mat("sticker", "#ff6f91", rough=0.4), parent=lid)
    screen_m = glow("d_screen", "#eaf3ff", 1.6, lights=True)
    box("d_scr", (0.39, 0.002, 0.26), (0, 0.009, 0.145), screen_m, bevel=0, parent=lid)
    tile_cols = ["#ff9f80", "#7ec8e3", "#b39ddb", "#a5d6a7", "#ffd180", "#90a4ae"]
    initials = ["JD", "MK", "", "AP", "TS", "RW"]
    tiles = []
    for i in range(6):
        cx = -0.125 + 0.125 * (i % 3)
        cz = 0.205 - 0.11 * (i // 3)
        tm = glow("tile%d" % i, tile_cols[i], 1.4)
        t = box("d_tile%d" % i, (0.115, 0.002, 0.1), (cx, 0.0115, cz), tm, bevel=0,
                parent=lid)
        tiles.append(t)
        if initials[i]:
            text("d_ini%d" % i, initials[i], (cx, 0.0135, cz), 0.035, P["ui_text_w"],
                 rot=(90, 0, 180), parent=lid)
        else:  # Charlie's own tile: tiny face
            sphere("d_me_head", (0.03, 0.002, 0.032), (cx, 0.0135, cz + 0.005),
                   glow("me_skin", "#e9b48f", 1.2), parent=lid)
            sphere("d_me_hair", (0.032, 0.002, 0.015), (cx, 0.0137, cz + 0.03),
                   glow("me_hair", "#3b2416", 1.0), parent=lid)
    text("d_call_t", "Q3 Sync (running long)", (0, 0.0135, 0.27), 0.017, P["ui_text"],
         rot=(90, 0, 180), parent=lid)
    lap_light = area_light("d_lap_light", (ox, -0.15, 1.0), (ox, 0.55, 1.25), 6,
                           "#dbe9ff", size=0.35)
    # desk lamp
    cylinder("d_lamp_b", 0.08, 0.09, 0.03, (ox + 0.75, -0.3, 0.79), P["ink"])
    cylinder("d_lamp_a", 0.012, 0.012, 0.45, (ox + 0.75, -0.3, 1.0), P["ink"], segs=8)
    cylinder("d_lamp_s", 0.05, 0.12, 0.14, (ox + 0.68, -0.3, 1.2), P["mug3"],
             rot=(0, -30, 0))
    lamp = point_light("d_lamp_l", (ox + 0.62, -0.3, 1.1), 0.0, "#ffbf72", 0.08)
    # wilting plant
    plant, leaves, _ = make_plant("d_plant", (ox - 0.72, -0.3, 0.775), P, scale=0.9)
    # sticky notes on the wall behind
    note_m = mat("sticky", "#ffe36e", rough=0.7)
    note_p = mat("sticky_p", "#ff9ec4", rough=0.7)
    for i, (x, z, txt, m_, sz) in enumerate([(-0.9, 1.9, "CALL MOM\nBACK!!", note_p, 0.075),
                                             (-0.45, 2.05, "rent\ndue 1st", note_m, 0.06),
                                             (0.55, 1.95, "dentist??", note_m, 0.05),
                                             (0.95, 2.15, "drink\nwater", note_m, 0.06)]):
        box("d_note%d" % i, (0.36, 0.01, 0.36), (ox + x, 2.93, z), m_, bevel=0,
            rot=(0, 4 * (i % 2 * 2 - 1), 0))
        text("d_notet%d" % i, txt, (ox + x, 2.92, z), sz, P["ui_text"], bold=True)
    # shelf + books
    box("d_shelf", (1.4, 0.25, 0.04), (ox - 1.6, 2.85, 1.55), P["wood"])
    for i in range(7):
        box("d_book%d" % i, (0.06, 0.2, 0.26 + 0.04 * (i % 3)),
            (ox - 2.15 + i * 0.08, 2.85, 1.71 + 0.02 * (i % 3)),
            mat("book%d" % (i % 4), ["#e84a5f", "#2d7ff9", "#f2c14e", "#27ae60"][i % 4],
                rough=0.6), bevel=0.005)
    # wall clock with swapping times
    cylinder("d_clock", 0.24, 0.24, 0.05, (ox + 1.9, 2.93, 2.35), P["white"], rot=(90, 0, 0))
    torus("d_clock_rim", 0.24, 0.022, (ox + 1.9, 2.92, 2.35), P["ink"], rot=(90, 0, 0))
    times = ["9:02", "11:30", "2:15", "4:50", "6:38"]
    tt = [text("d_clock_%d" % i, t, (ox + 1.9, 2.89, 2.35), 0.13, P["ui_text"])
          for i, t in enumerate(times)]
    tswap = [s, s + 200, s + 240, s + 280, s + 320, s + 361]
    for i, t in enumerate(tt):
        only_between(t, tswap[i], tswap[i + 1] - 1)
    # extra mugs + envelopes (appear over the time-lapse)
    mugs = []
    for i, (x, y, m_) in enumerate([(-0.45, -0.38, P["mug2"]), (0.5, -0.38, P["mug3"]),
                                    (-0.3, 0.12, P["mug"])]):
        mg = make_mug("d_mug%d" % i, None, m_, P, loc=(ox + x, y, 0.775))
        mg.scale = (0.001,) * 3
        pop(mg, s + 205 + i * 40, 6)
        mugs.append(mg)
    env_m = mat("env", "#fdfaf3", rough=0.6)
    for i in range(14):
        e = empty("d_env%d" % i, (ox + 0.62, 0.05, 2.5), (0, 0, 7 * ((i * 5) % 7 - 3)))
        box("d_env_m%d" % i, (0.26, 0.17, 0.014), (0, 0, 0), env_m, bevel=0.003, parent=e)
        sphere("d_env_dot%d" % i, (0.018, 0.018, 0.004), (0.1, 0.06, 0.008), P["red"],
               parent=e)
        f0 = s + 180 + i * 11
        key(e, "location", f0, (ox + 0.62, 0.05, 2.0))
        key(e, "location", f0 + 6, (ox + 0.62 + 0.01 * ((i * 3) % 5 - 2),
                                    0.05 + 0.01 * ((i * 7) % 5 - 2), 0.785 + 0.016 * i))
        only_between(e, f0, FRAME_END)

    # lighting over the day
    sky.at(s, "#fff0d6", "#8ec5ff", 0.7)
    key_prop(sun.data, "energy", s, 1400)
    key_prop(sun.data, "color", s, srgb("#fff2dc"))
    key_prop(sun.data, "energy", s + 240, 1500)
    key_prop(sun.data, "color", s + 240, srgb("#fff2dc"))
    key_prop(sun.data, "energy", s + 300, 900)
    key_prop(sun.data, "color", s + 300, srgb("#ffb070"))
    key_prop(sun.data, "energy", s + 350, 260)
    key_prop(sun.data, "color", s + 350, srgb("#7d8cff"))
    key_prop(lamp.data, "energy", s + 300, 0.0, "CONSTANT")
    key_prop(lamp.data, "energy", s + 301, 30.0, "CONSTANT")

    # --- animation
    f = s
    C.place(f, (ox, 0, 0))
    show(C.phone, f, False)
    show(C.mug, f, False)
    seat = dict(SIT, root_loc=(0, 0.62, 0.05), spine=(6, 0, 0),
                sh_L=(-42, 0, -8), el_L=(-52, 0, 10), sh_R=(-42, 0, 8), el_R=(-52, 0, -10),
                head=(10, 0, 0), eyes=(12, 0, 0), lids=-28, mouth="flat", brows=(0, 0))
    C.pose(f, seat)

    def typing(f0, f1, period=4, slump=0.0):
        k = f0
        i = 0
        while k < f1:
            a = 6 if i % 2 else -4
            C.pose(k, el_L=(-52 + a, 0, 10), el_R=(-52 - a, 0, -10))
            k += period
            i += 1

    typing(f, f + 56)
    C.pose(f + 60, head=(16, 0, 0))
    C.pose(f + 66, head=(4, 0, 0))     # nod
    C.pose(f + 72, head=(16, 0, 0))
    C.pose(f + 78, head=(6, 0, 0), mouth="smile")
    C.talk(f + 82, f + 112)
    C.pose(f + 112, mouth="flat")
    C.blink(f + 30)
    C.blink(f + 100)
    typing(f + 114, f + 178)
    # time-lapse
    C.pose(f + 180, spine=(8, 0, 0), lids=-20)
    typing(f + 182, f + 218, period=3)
    C.pose(f + 220, spine=(10, 0, 4), head=(14, 0, -12), eyes=(8, 0, -14), lids=-10,
           brows=(-0.3, 0.3))
    typing(f + 222, f + 258, period=3)
    # chin on hand
    C.pose(f + 262, spine=(16, 0, 6), head=(6, -12, 0), sh_R=(-52, 0, 18),
           el_R=(-130, 0, -10), lids=10, mouth="frown", brows=(0, 0.6))
    C.pose(f + 290, spine=(16, 0, 6), head=(8, -14, 0), lids=18)
    typing(f + 296, f + 322, period=3)
    # stretch + yawn
    C.pose(f + 328, spine=(-10, 0, 0), head=(-14, 0, 0), sh_L=(-170, -20, 0),
           sh_R=(-170, 20, 0), el_L=(-10, 0, 0), el_R=(-10, 0, 0), lids=92, mouth="o",
           brows=(1.0, 0))
    C.pose(f + 342, spine=(-12, 0, 0), sh_L=(-175, -25, 0), sh_R=(-175, 25, 0))
    C.pose(f + 356, preset=dict(seat, spine=(20, 0, 0), head=(16, 0, 0), lids=12,
                                mouth="flat", brows=(-0.2, 0.7), root_loc=(0, 0.66, 0.02)))
    # plant wilts through the day
    droop(leaves, f, 0.15)
    droop(leaves, f + 180, 0.2)
    droop(leaves, f + 340, 0.85)
    # call tiles: active-speaker flicker
    for i, t in enumerate(tiles):
        for k in range(f + 120, f + 180, 10):
            key(t, "scale", k, (1.0 if (k // 10 + i) % 6 else 1.08,) * 3, interp="CONSTANT")

    # cameras: wide 3/4, over-the-shoulder on the call, wide time-lapse
    camA = camera("d_camA", (ox - 1.45, -1.9, 1.5), (ox, 0.6, 1.25), lens=38,
                  focus=C.focus, fstop=3.2)
    cam_key(camA, f, (ox - 1.45, -1.9, 1.5), (ox, 0.6, 1.3))
    cam_key(camA, f + 119, (ox - 1.1, -1.5, 1.48), (ox, 0.6, 1.4))
    camB = camera("d_camB", (ox + 0.95, 0.75, 1.45), (ox, -0.25, 0.95), lens=40,
                  focus=lid, fstop=4.0)
    cam_key(camB, f + 120, (ox + 0.95, 0.75, 1.45), (ox - 0.05, -0.25, 0.95))
    cam_key(camB, f + 179, (ox + 0.8, 0.55, 1.38), (ox - 0.05, -0.25, 0.95))
    camC = camera("d_camC", (ox - 0.3, -3.0, 1.9), (ox, 0.5, 1.15), lens=30,
                  focus=C.focus, fstop=5.6)
    cam_key(camC, f + 180, (ox - 0.3, -3.0, 1.9), (ox, 0.5, 1.15))
    cam_key(camC, f + 360, (ox - 0.15, -2.35, 1.7), (ox, 0.5, 1.15))
    cut(f, camA)
    cut(f + 120, camB)
    cut(f + 180, camC)


def chat_bubble(name, label, me, loc, P, parent=None):
    w = 0.085 * len(label) * 0.55 + 0.25
    col = mat("chat_me", "#34c759", rough=0.35, emit="#34c759", strength=0.6) if me else \
        mat("chat_them", "#e9e9ef", rough=0.35, emit="#ffffff", strength=0.25)
    g = empty(name, loc, parent=parent)
    pill(name + "_bg", w, 0.2, 0.04, (0, 0, 0), col, parent=g)
    text(name + "_t", label, (0, -0.03, -0.005), 0.085,
         P["ui_text_w"] if me else P["ui_text"], parent=g, bold=False)
    g.scale = (0.001,) * 3
    return g


def build_couch(P, C, sky, s):
    new_collection("couch")
    ox = OX["couch"]
    wall = mat("c_wall", "#c9a98e", rough=0.9)
    floor = mat("c_floor", "#7a4f33", rough=0.6, coat=0.2)
    room(ox, wall, floor)
    box("c_rug", (3.4, 2.4, 0.02), (ox, 0.3, 0.01), mat("rug", "#e7d3b0", rough=1.0),
        bevel=0)
    velvet = mat("couch_v", "#2f7f7a", rough=0.75, sheen=0.9)
    box("c_base", (2.5, 0.95, 0.42), (ox, 1.25, 0.3), velvet, bevel=0.08)
    for sx in (-0.6, 0.6):
        box("c_cush", (1.15, 0.82, 0.2), (ox + sx, 1.15, 0.6), velvet, bevel=0.09)
        box("c_backc", (1.15, 0.3, 0.55), (ox + sx, 1.62, 0.95), velvet, bevel=0.12,
            rot=(-8, 0, 0))
    for sx in (-1.3, 1.3):
        box("c_arm", (0.28, 0.95, 0.62), (ox + sx, 1.25, 0.52), velvet, bevel=0.12)
    box("c_throw", (0.5, 0.5, 0.12), (ox + 0.8, 1.45, 0.82), mat("throw", "#f2c14e",
                                                                  rough=0.9, sheen=0.5),
        bevel=0.05, rot=(-20, 0, 15))
    # coffee table + takeout
    box("c_table", (1.3, 0.65, 0.06), (ox, 0.05, 0.42), P["wood"], bevel=0.02)
    for sx in (-0.58, 0.58):
        for sy in (-0.26, 0.26):
            cylinder("c_tleg", 0.025, 0.025, 0.4, (ox + sx, 0.05 + sy, 0.2), P["wood_dk"],
                     segs=10)
    to_m = mat("takeout", "#fbfaf6", rough=0.6)
    for i, (x, y, rz) in enumerate([(-0.25, 0.05, 45), (0.15, 0.12, 30)]):
        cylinder("c_takeout%d" % i, 0.09, 0.13, 0.17, (ox + x, y, 0.535), to_m,
                 rot=(0, 0, rz), segs=4)
        sphere("c_seal%d" % i, (0.03, 0.006, 0.03), (ox + x, y - 0.1, 0.55), P["red"])
    for k in range(2):
        cylinder("c_chop%d" % k, 0.006, 0.004, 0.24, (ox - 0.2 + 0.02 * k, 0.03, 0.66),
                 P["wood"], rot=(0, 30, 10), segs=8)
    # floor lamp + plant on side table
    cylinder("c_flamp_p", 0.015, 0.015, 1.5, (ox + 1.85, 1.3, 0.75), P["ink"], segs=8)
    cylinder("c_flamp_s", 0.18, 0.24, 0.3, (ox + 1.85, 1.3, 1.6),
             mat("shade2", "#fff1d0", rough=0.8, emit="#ffcf8a", strength=1.5))
    point_light("c_flamp_l", (ox + 1.85, 1.3, 1.5), 60, "#ffb866", 0.15)
    box("c_side", (0.45, 0.45, 0.55), (ox + 1.85, 0.6, 0.275), P["wood_dk"], bevel=0.02)
    _, sleaves, _ = make_plant("c_plant", (ox + 1.85, 0.6, 0.55), P, scale=0.85)
    droop(sleaves, s, 0.9)
    # framed art + clock
    box("c_frame", (1.2, 0.04, 0.8), (ox - 0.2, 2.94, 2.0), P["wood_dk"], bevel=0.01)
    box("c_art", (1.08, 0.01, 0.68), (ox - 0.2, 2.915, 2.0), mat("art", "#f28c6f",
                                                                  rough=0.8), bevel=0)
    sphere("c_art_sun", (0.18, 0.01, 0.18), (ox - 0.05, 2.905, 2.05),
           mat("art2", "#ffd36e", rough=0.8))
    cylinder("c_clock", 0.2, 0.2, 0.04, (ox + 1.3, 2.93, 2.2), P["white"], rot=(90, 0, 0))
    text("c_clock_t", "7:41", (ox + 1.3, 2.9, 2.2), 0.11, P["ui_text"])
    # TV glow from behind camera
    tv = area_light("c_tv", (ox + 0.3, -3.2, 1.0), (ox - 0.2, 1.2, 1.0), 220, "#6f9bff",
                    size=1.4, size_y=0.8)
    for k in range(s, s + 229, 9):
        key_prop(tv.data, "energy", k, 160 + 120 * ((k * 7919) % 13) / 13, "CONSTANT")
    sky.at(s, "#2b2f55", "#151832", 0.2)

    f = s
    C.place(f, (ox, 0, 0))
    show(C.phone, f, True)
    show(C.mug, f, False)
    key_socket(glow_strength(C.phone_screen_mat), f, 3.0, "CONSTANT")
    key_prop(C.phone_light.data, "energy", f, 3.0, "CONSTANT")
    slump = dict(SIT, root_loc=(-0.35, 1.15, 0.1), spine=(-24, 0, 0), head=(30, 0, 0),
                 hip_L=(-74, 0, -6), hip_R=(-70, 0, 8), kn_L=(64, 0, 0), kn_R=(70, 0, 0),
                 sh_R=(-30, 0, 16), el_R=(-112, 0, 6), sh_L=(-6, -20, 0), el_L=(-20, 0, 0),
                 eyes=(14, 0, 0), lids=-6, mouth="flat", brows=(0, 0.1))
    C.pose(f, slump)
    C.blink(f + 16)
    sx_, sy_, sz_ = ox + 0.55, 0.7, 1.3
    stack = empty("c_chat_stack", (sx_, sy_, sz_))
    msgs = [("we NEED to catch up!!", False), ("omg yes", True), ("next week?", False),
            ("can't - wedding", False), ("next month then!", True),
            ("put it in the group cal", False), ("...", True)]
    bubbles = []
    k = f + 18
    for i, (lbl, me) in enumerate(msgs):
        b = chat_bubble("c_msg%d" % i, lbl, me, (0.32 if me else -0.32, 0, -0.27 * 0),
                        P, parent=stack)
        # each new message pushes the stack up
        key(stack, "location", k - 1, (sx_, sy_, sz_ + 0.26 * (i - 1)))
        key(stack, "location", k + 4, (sx_, sy_, sz_ + 0.26 * i))
        b.location = (0.32 if me else -0.32, 0, -0.26 * i)
        pop(b, k, 6)
        bubbles.append(b)
        k += 16
    C.pose(f + 36, mouth="smile", brows=(0.4, 0))
    C.pose(f + 50, mouth="grin", lids=-20)
    C.pose(f + 70, mouth="flat", lids=-8, brows=(0, 0.3))
    C.pose(f + 92, mouth="smile", brows=(0.2, 0.2))
    C.pose(f + 112, mouth="flat", brows=(-0.2, 0.6), lids=4)
    C.blink(f + 100)
    # battery dies
    bat = empty("c_bat", (ox - 0.38, 0.45, 1.48))
    pill("c_bat_bg", 0.62, 0.22, 0.04, (0, 0, 0), mat("bat_red", "#ff3b30", rough=0.3,
                                                       emit="#ff3b30", strength=1.2),
         parent=bat)
    text("c_bat_t", "Battery 1%", (0, -0.03, -0.005), 0.09, P["ui_text_w"], parent=bat)
    bat.scale = (0.001,) * 3
    pop(bat, f + 132, 7)
    C.pose(f + 132, lids=-50, brows=(1.0, 0), mouth="o")
    C.pose(f + 146, lids=-50)
    dead = f + 150
    key_socket(glow_strength(C.phone_screen_mat), dead - 1, 3.0, "CONSTANT")
    key_socket(glow_strength(C.phone_screen_mat), dead, 0.0, "CONSTANT")
    key_prop(C.phone_light.data, "energy", dead - 1, 3.0, "CONSTANT")
    key_prop(C.phone_light.data, "energy", dead, 0.0, "CONSTANT")
    for b in bubbles:
        show(b, dead, False)
    show(bat, dead, False)
    C.pose(dead, mouth="flat", lids=-40)
    C.blink(dead + 14)
    C.pose(dead + 26, head=(10, 0, 0), eyes=(0, 0, 0), lids=-30, brows=(0, 0))
    C.blink(dead + 38)
    C.pose(dead + 50, head=(6, 0, 24), eyes=(10, 0, 28), lids=-34, brows=(0.3, 0.6))
    C.pose(dead + 77, head=(6, 0, 26), eyes=(10, 0, 30), lids=-34, brows=(0.3, 0.8),
           mouth="frown")

    cam = camera("c_cam", (ox + 0.35, -2.5, 1.25), (ox - 0.3, 1.15, 1.25), lens=38,
                 focus=C.focus, fstop=2.8)
    cam_key(cam, f, (ox + 0.35, -2.5, 1.25), (ox - 0.3, 1.15, 1.35))
    cam_key(cam, f + 140, (ox + 0.2, -1.75, 1.25), (ox - 0.32, 1.15, 1.35))
    cam_key(cam, f + 228, (ox + 0.15, -1.55, 1.22), (ox - 0.32, 1.15, 1.33))
    cut(f, cam)


def build_window(P, C, sky, s_in, s_out):
    new_collection("window")
    ox = OX["window"]
    wall = mat("w_wall", "#e8d9c4", rough=0.9)
    floor = mat("w_floor", "#9a6a46", rough=0.55, coat=0.2)
    hole = (-0.6, 1.4, 0.95, 2.45)
    rg = room(ox, wall, floor, left=False, d=6.0, w=7.0)
    # interior skin of the left wall (with the window opening)
    wall_with_hole("w_inner", "x", -3.43, (-3.0, 3.0), 3.2, hole, wall, thick=0.02,
                   parent=rg)
    # ---- building facade (the outside of that wall) with a grid of windows
    brick = mat("facade", "#c86b4f", rough=0.85)
    trim = mat("facade_trim", "#f1e6d6", rough=0.6)
    cols = [0.4 + 4.5 * j for j in range(-3, 4)]
    rows = [0.95 + 3.4 * k for k in range(-2, 3)]
    ww, wh = 2.0, 1.5
    fx = ox - 3.52
    y_min, y_max = cols[0] - 2.25, cols[-1] + 2.25
    z_min, z_max = rows[0] - 1.6, rows[-1] + wh + 1.6
    # piers between columns
    edges = [y_min] + [c for col in cols for c in (col - ww / 2, col + ww / 2)] + [y_max]
    for i in range(0, len(edges), 2):
        a, b = edges[i], edges[i + 1]
        box("fac_pier%d" % i, (0.16, b - a, z_max - z_min), (fx, (a + b) / 2,
                                                              (z_min + z_max) / 2),
            brick, bevel=0)
    for j, c in enumerate(cols):
        vs = [z_min] + [v for r in rows for v in (r, r + wh)] + [z_max]
        for i in range(0, len(vs), 2):
            a, b = vs[i], vs[i + 1]
            box("fac_sp%d_%d" % (j, i), (0.16, ww, b - a), (fx, c, (a + b) / 2), brick,
                bevel=0)
        for r in rows:
            box("fac_sill%d" % j, (0.3, ww + 0.25, 0.08), (fx - 0.08, c, r - 0.04), trim,
                bevel=0.01)
            box("fac_lintel%d" % j, (0.22, ww + 0.15, 0.1), (fx - 0.04, c, r + wh + 0.05),
                trim, bevel=0.01)
    box("fac_cornice", (0.5, y_max - y_min + 0.4, 0.3), (fx - 0.1, (y_min + y_max) / 2,
                                                         z_max + 0.15), trim, bevel=0.03)
    box("street", (60, 60, 0.1), (fx - 20, 0.4, z_min - 0.05), mat("street", "#5a5560",
                                                                   rough=0.9), bevel=0)
    # neighbours' windows: glowing rooms (+ little silhouettes)
    glows = ["#ffd59a", "#ffc27a", "#a9c8ff", "#ffe2b8", "#ffb27a", "#c2b5ff"]
    neighbours = []
    win_glows = []
    rng = 0
    for j, c in enumerate(cols):
        for k, r in enumerate(rows):
            if c == 0.4 and r == 0.95:
                continue
            rng = (rng * 1103515245 + 12345 + j * 31 + k * 17) % 2147483648
            gm = glow("winglow%d_%d" % (j, k), glows[rng % len(glows)], 0.0)
            box("fac_glow%d_%d" % (j, k), (0.02, ww, wh), (fx + 0.6, c, r + wh / 2), gm,
                bevel=0)
            win_glows.append(gm)
            if rng % 3 != 0:
                nb = Neighbour("nb%d_%d" % (j, k), (fx + 0.45, c - 0.3 + 0.6 * (rng % 2),
                                                    r - 0.55),
                               mat("silh", "#2a2032", rough=0.9), rot_z=-90,
                               phone=(rng % 4 == 1))
                neighbours.append(nb)
    # the waving neighbour, next window over
    waver = Neighbour("nb_waver", (fx + 0.5, cols[4] - 0.3, rows[2] - 0.55),
                      mat("silh2", "#3a2c46", rough=0.9), rot_z=-90)

    # ---- interior props
    window_frame("w_frame", "x", -3.5, hole, P["white"], parent=rg, mullions=False)
    sill_y = (hole[0] + hole[1]) / 2
    box("w_sill_in", (0.34, hole[1] - hole[0] + 0.2, 0.05), (ox - 3.3, sill_y, hole[2]),
        P["white"], bevel=0.01)
    plant, leaves, flower = make_plant("w_plant", (ox - 3.26, 1.12, hole[2] + 0.025), P,
                                       scale=0.9)
    droop(leaves, s_in, 0.9)
    # blinds
    slats = []
    blind_m = mat("blind2", "#f4eee2", rough=0.6)
    n_sl = 14
    for i in range(n_sl):
        z = hole[3] - 0.06 - i * 0.107
        sl = box("w_slat%d" % i, (0.03, hole[1] - hole[0] + 0.1, 0.098),
                 (ox - 3.39, sill_y, z), blind_m, bevel=0.0)
        slats.append((sl, z))
    box("w_blind_head", (0.06, hole[1] - hole[0] + 0.15, 0.06),
        (ox - 3.39, sill_y, hole[3] + 0.02), blind_m, bevel=0.01)
    cord = cylinder("w_cord", 0.006, 0.006, 0.9, (ox - 3.36, hole[1] - 0.02, hole[3] - 0.45),
                    P["white"], segs=8)
    # sunset light through the window
    sun = area_light("w_sun", (ox - 8, 0.6, 2.6), (ox - 1.5, 0.4, 1.0), 40, "#ff9a4d",
                     size=2.5)
    area_light("w_fill", (ox + 2.0, -3.0, 2.8), (ox - 2.0, 0.5, 1.2), 140, "#b6c4ff",
               size=3.0)
    lamp = point_light("w_lamp", (ox + 2.4, 2.3, 2.0), 25, "#ffb866", 0.2)
    # living room dressing
    box("w_shelf", (1.6, 0.4, 1.8), (ox + 1.9, 2.7, 0.9), P["wood"], bevel=0.02)
    for i in range(10):
        box("w_book%d" % i, (0.07, 0.25, 0.28 + 0.03 * (i % 3)),
            (ox + 1.3 + i * 0.12, 2.68, 1.15 + 0.6 * (i // 5)),
            mat("book%d" % (i % 4), ["#e84a5f", "#2d7ff9", "#f2c14e", "#27ae60"][i % 4]))
    box("w_rug", (2.6, 2.0, 0.02), (ox - 0.4, 0.3, 0.01), mat("rug2", "#d9c2e8",
                                                              rough=1.0), bevel=0)
    # what you see through the window: a low sun and a distant skyline
    sun_disc = sphere("w_sun_disc", 2.2, (ox - 60, 3.0, 4.5), glow("sun_disc", "#ffd08a", 6.0))
    for i in range(16):
        hgt = 4 + 9 * (((i * 7) % 11) / 11)
        box("w_sky%d" % i, (6, 3.5, hgt), (ox - 45 - 6 * (i % 3), -22 + i * 3.2, hgt / 2 - 3),
            glow("skyline", "#6b4a7a", 0.6), bevel=0)
    # water drops
    drops = []
    for i in range(10):
        d = sphere("w_drop%d" % i, (0.012, 0.012, 0.02), (ox - 3.2, 0.72, 1.6), P["water"])
        drops.append(d)

    # ----------------------------------------------------- interior animation
    f = s_in
    C.place(f, (ox, 0, 0))
    show(C.phone, f, False)
    show(C.mug, f, True)
    for sl, z in slats:
        key(sl, "location", f, (ox - 3.39, sill_y, z))
    sky.at(f, "#ff8a4d", "#4a3d8f", 0.0)
    key_prop(sun.data, "energy", f, 40)
    stand = dict(BASE_POSE, root_loc=(1.5, 0.0, 0), root_rot=(0, 0, -90),
                 sh_L=(-14, 0, -14), el_L=(-90, 0, -8), lids=-24, mouth="flat",
                 brows=(0, 0.4), head=(8, 0, 0))
    C.pose(f, stand)
    C.walk(f, f + 60, (1.5, 0.0, 0), (-2.45, 0.55, 0), sh_L=(-14, 0, -14),
           el_L=(-90, 0, -8))
    C.pose(f + 66, root_rot=(0, 0, -62), head=(22, 0, 14), eyes=(20, 0, 10),
           brows=(0.2, 0.8), mouth="frown")
    C.blink(f + 74)
    # pour
    C.pose(f + 84, sh_L=(-62, 0, -26), el_L=(-46, 0, 0), spine=(10, 0, 0), head=(26, 0, 16))
    C.pose(f + 92, sh_L=(-66, 0, -26), el_L=(-28, 0, 0))
    for i, d in enumerate(drops):
        f0 = f + 92 + i * 3
        key(d, "location", f0, (ox - 3.22, 1.09 + 0.01 * (i % 3), 1.62), interp="LINEAR")
        key(d, "location", f0 + 9, (ox - 3.25, 1.12, 1.17), interp="LINEAR")
        only_between(d, f0, f0 + 9)
    C.pose(f + 126, sh_L=(-62, 0, -26), el_L=(-28, 0, 0))
    C.pose(f + 136, sh_L=(-14, 0, -14), el_L=(-90, 0, -8), spine=(4, 0, 0))
    # plant perks up, flower blooms
    droop(leaves, f + 118, 0.9)
    for i, lp in enumerate(leaves):
        up = 18 + 6 * (i % 3)
        key(lp, "rotation_euler", f + 130 + i * 2, (up - 10, 0, 0))
        key(lp, "rotation_euler", f + 138 + i * 2, (up, 0, 0))
    key(flower, "scale", f + 132, (0.001,) * 3)
    key(flower, "scale", f + 146, (1.25,) * 3)
    key(flower, "scale", f + 152, (1.0,) * 3)
    C.pose(f + 140, brows=(0.9, -0.2), lids=-50, mouth="o", head=(20, 0, 14))
    C.pose(f + 156, brows=(0.6, 0), lids=-36, mouth="smile")
    # raise the blinds
    C.pose(f + 170, sh_R=(-150, 0, -30), el_R=(-30, 0, 0), head=(-6, 0, 20), eyes=(-10, 0, 10),
           root_rot=(0, 0, -70))
    C.pose(f + 186, sh_R=(-150, 0, -30), el_R=(-30, 0, 0))
    for i, (sl, z) in enumerate(slats):
        top = hole[3] - 0.06 - i * 0.012
        key(sl, "location", f + 186 + (n_sl - 1 - i), (ox - 3.39, sill_y, z))
        key(sl, "location", f + 212, (ox - 3.39, sill_y, top))
    key(cord, "location", f + 186, cord.location)
    key(cord, "location", f + 212, (cord.location.x, cord.location.y, cord.location.z - 0.35))
    key_prop(sun.data, "energy", f + 192, 40)
    key_prop(sun.data, "energy", f + 214, 2600)
    sky.at(f + 186, "#ff8a4d", "#4a3d8f", 0.0, interp="BEZIER")
    sky.at(f + 214, "#ff8a4d", "#4a3d8f", 1.4, interp="BEZIER")
    C.pose(f + 200, sh_R=(-20, 0, 10), el_R=(-20, 0, 0), lids=40, brows=(-0.3, 0.3),
           mouth="flat", head=(-4, 0, 22))                              # squint
    C.pose(f + 222, lids=-30, brows=(0.6, 0), mouth="grin", head=(-6, 0, 24))
    C.pose(f + 238, lids=-30, mouth="smile")
    # step to the sill and lean out
    C.pose(f + 252, root_loc=(-2.6, 0.55, 0), root_rot=(0, 0, -90), head=(-4, 0, 0),
           eyes=(0, 0, 0))
    C.pose(f + 272, root_loc=(-2.92, 0.45, 0), spine=(24, 0, 0), sh_L=(-62, 0, -10),
           el_L=(-40, 0, 0), sh_R=(-62, 0, 10), el_R=(-40, 0, 0), head=(-18, 0, 0),
           lids=-30, mouth="smile")
    C.pose(f + 299, root_loc=(-2.92, 0.45, 0), lids=-30)

    cam = camera("w_cam", (ox + 0.9, -2.6, 1.55), (ox - 2.4, 0.6, 1.3), lens=32,
                 focus=C.focus, fstop=3.5)
    cam_key(cam, f, (ox + 0.9, -2.6, 1.55), (ox - 0.5, 0.4, 1.3))
    cam_key(cam, f + 60, (ox + 0.4, -2.3, 1.5), (ox - 2.4, 0.5, 1.35))
    cam_key(cam, f + 170, (ox - 0.6, -1.6, 1.45), (ox - 2.8, 0.6, 1.5))
    cam_key(cam, f + 300, (ox - 0.4, -1.9, 1.5), (ox - 2.8, 0.6, 1.5))
    cut(f, cam)

    # ----------------------------------------------------- exterior animation
    g = s_out
    sky.at(g, "#ff9a5c", "#5b4aa0", 1.6)
    ext_sun = area_light("ext_sun", (fx - 25, -12, 14), (fx, 0.4, 2.0), 32000, "#ff9a5c",
                         size=10)
    ext_fill = area_light("ext_fill", (fx - 18, 14, 4), (fx, 0.4, 2.0), 6000, "#a48cff",
                          size=12)
    only_between(ext_sun, s_out, FRAME_END)
    only_between(ext_fill, s_out, FRAME_END)
    C.pose(g, root_loc=(-2.92, 0.45, 0), lids=-30, mouth="smile")
    C.pose(g + 24, lids=40, mouth="smile", brows=(0.3, 0), head=(-22, 0, 0))   # content
    C.pose(g + 50, lids=40)
    # neighbour waves
    for k in range(g + 46, g + 110, 8):
        key(waver.arm, "rotation_euler", k, (0, 150, 0))
        key(waver.arm, "rotation_euler", k + 4, (0, 120, 0))
    C.pose(g + 60, lids=-50, head=(-10, 0, -34), eyes=(0, 0, -30), brows=(1.0, 0),
           mouth="o")
    C.pose(g + 72, mouth="grin", lids=-36)
    C.pose(g + 78, sh_R=(-160, 0, -10), el_R=(-20, 0, 0))
    for k in range(g + 84, g + 132, 8):
        C.pose(k, el_R=(-50, 0, 0))
        C.pose(k + 4, el_R=(-10, 0, 0))
    C.pose(g + 140, sh_R=(-62, 0, 10), el_R=(-40, 0, 0), head=(-18, 0, -6), eyes=(0, 0, 0),
           mouth="smile", lids=-28)
    C.pose(g + 215, lids=-28)
    C.blink(g + 160)
    # windows light up one by one as we pull back
    for i, gm in enumerate(win_glows):
        on = g + 100 + (i * 37) % 90
        key_socket(glow_strength(gm), g, 1.4 if i % 4 == 0 else 0.0, "CONSTANT")
        key_socket(glow_strength(gm), on, 2.2, "CONSTANT")

    cam2 = camera("ext_cam", (fx - 4.0, 0.0, 1.7), (fx, 0.45, 1.6), lens=40,
                  focus=C.focus, fstop=4.0)
    cam_key(cam2, g, (fx - 3.4, -0.4, 1.65), (fx, 0.55, 1.65), lens=40)
    cam_key(cam2, g + 60, (fx - 3.8, 0.4, 1.8), (fx, 1.6, 1.7), lens=36)
    cam_key(cam2, g + 100, (fx - 4.6, 0.9, 1.9), (fx, 1.2, 1.8), lens=35)
    cam_key(cam2, g + 215, (fx - 30, 1.0, 3.6), (fx, 0.6, 3.0), lens=30)
    cam2.data.dof.aperture_fstop = 4.0
    key_prop(cam2.data.dof, "aperture_fstop", g + 100, 4.0)
    key_prop(cam2.data.dof, "aperture_fstop", g + 200, 22.0)
    cut(g, cam2)


# ==========================================================================
def build():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scn = bpy.context.scene
    scn.render.fps = FPS
    scn.frame_start = 1
    scn.frame_end = FRAME_END
    _load_fonts()
    new_collection("characters")
    P = palette()
    C = Charlie(P)
    sky = Sky()
    sky.at(1, "#f4b183", "#f4b183", 0.6)

    cam = build_title(P, START["title"], 84, "CHARLIE", "an ordinary Tuesday", "title")
    C.place(1, (OX["title"], 40, -50))  # parked off-stage during the title
    build_bed(P, C, sky, START["bed"])
    C.pose(START["kitchen"] - 1)
    build_kitchen(P, C, sky, START["kitchen"])
    C.pose(START["desk"] - 1)
    build_desk(P, C, sky, START["desk"])
    C.pose(START["couch"] - 1)
    build_couch(P, C, sky, START["couch"])
    C.pose(START["window"] - 1)
    build_window(P, C, sky, START["window"], START["outside"])
    build_title(P, START["end"], 144, "Charlie, 34.",
                "Inbox: 99+\nPlans with friends: next month (probably)\n"
                "Plant: alive\nCharlie: doing okay.", "end")
    C.place(START["end"], (OX["end"], 40, -50))
    sky.at(START["end"], "#f4b183", "#f4b183", 0.6)

    finalize_interp()
    for frame, cam in CAM_CUTS:
        m = scn.timeline_markers.new(cam.name, frame=frame)
        m.camera = cam
    scn.camera = CAM_CUTS[0][1]
    return scn


def setup_render(scn, res=(960, 540), samples=14):
    scn.render.engine = "CYCLES"
    scn.cycles.device = "CPU"
    scn.cycles.samples = samples
    scn.cycles.use_adaptive_sampling = True
    scn.cycles.adaptive_threshold = 0.05
    scn.cycles.use_denoising = True
    try:
        scn.cycles.denoiser = "OPENIMAGEDENOISE"
    except Exception:
        pass
    scn.cycles.use_light_tree = False
    scn.cycles.max_bounces = 4
    scn.cycles.diffuse_bounces = 2
    scn.cycles.glossy_bounces = 2
    scn.cycles.transmission_bounces = 2
    scn.cycles.transparent_max_bounces = 4
    scn.cycles.caustics_reflective = False
    scn.cycles.caustics_refractive = False
    scn.cycles.sample_clamp_indirect = 6.0
    scn.render.resolution_x, scn.render.resolution_y = res
    scn.render.resolution_percentage = 100
    scn.render.use_persistent_data = True
    scn.render.film_transparent = False
    try:
        scn.view_settings.view_transform = "AgX"
        for look in ("AgX - Punchy", "Punchy", "AgX - Medium High Contrast",
                     "Medium High Contrast"):
            try:
                scn.view_settings.look = look
                break
            except Exception:
                pass
    except Exception:
        pass
    scn.view_settings.exposure = 0.0
    scn.render.image_settings.file_format = "PNG"
    scn.render.image_settings.color_mode = "RGB"


def main():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else argv[1:]
    ap = argparse.ArgumentParser()
    ap.add_argument("--save")
    ap.add_argument("--render")
    ap.add_argument("--frames")
    ap.add_argument("--stills")
    ap.add_argument("--res", default="960x540")
    ap.add_argument("--samples", type=int, default=14)
    a = ap.parse_args(argv)
    scn = build()
    w, h = (int(v) for v in a.res.lower().split("x"))
    setup_render(scn, (w, h), a.samples)
    if a.save:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(a.save))
        print("saved", a.save)
    if a.stills:
        out = a.render or "stills"
        os.makedirs(out, exist_ok=True)
        for fr in [int(x) for x in a.stills.split(",")]:
            scn.frame_set(fr)
            scn.render.filepath = os.path.join(os.path.abspath(out), "still_%04d.png" % fr)
            bpy.ops.render.render(write_still=True)
            print("rendered still", fr, flush=True)
    elif a.render:
        os.makedirs(a.render, exist_ok=True)
        if a.frames:
            f0, f1 = (int(v) for v in a.frames.split("-"))
            scn.frame_start, scn.frame_end = f0, f1
        scn.render.filepath = os.path.join(os.path.abspath(a.render), "frame_")
        bpy.ops.render.render(animation=True)


if __name__ == "__main__":
    main()
