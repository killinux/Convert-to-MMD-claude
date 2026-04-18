"""Path D programmatic MMD morph synthesis + verification tools A/B/C.

Operates entirely on the source mesh's own vertex groups (XPS-Canon
`head lip*` etc) using hand-authored per-morph offset recipes — no
target template, no cross-mesh transfer. Prior attempts at cross-mesh
transfer (TPS+IDW, Sumner, SurfaceDeform, BVH barycentric, KDTree)
all produced visually diluted or torn morphs; see `doc/pitfalls.md`.

Four Blender operators are exposed via `CLASSES`:
  - MORPH_OT_verify_modal           (Tool A core)
  - MORPH_OT_run_spec_check         (Tool B button)
  - MORPH_OT_run_batch_screenshot   (Tool C button)
  - MORPH_OT_start_verify_modal     (Tool A launcher)
The addon's `operators/morph_synth_operator.py` registers these plus
its own `OBJECT_OT_synth_vertex_morphs` ④ button.
"""

import bpy
import numpy as np
from mathutils import Vector


# ---------- Path D: programmatic per-mesh morph synthesis ----------

def _vg_weights(mesh_obj, vg_names):
    """Return per-vertex summed weight across given vertex-group names."""
    import numpy as np
    N = len(mesh_obj.data.vertices)
    w = np.zeros(N, dtype=np.float64)
    indices = set()
    for n in vg_names:
        vg = mesh_obj.vertex_groups.get(n)
        if vg is not None:
            indices.add(vg.index)
    if not indices:
        return w
    for i, v in enumerate(mesh_obj.data.vertices):
        for g in v.groups:
            if g.group in indices:
                w[i] += g.weight
    return np.minimum(w, 1.0)  # clamp to 1.0


def bake_programmatic_morph(src_mesh, morph_name, recipe):
    """Generic programmatic morph synthesizer.

    recipe: dict mapping
      tuple_of_vg_names -> (x_mm, y_mm, z_mm)

    For each bucket, summed weight across the listed vgs masks the offset.
    Offsets accumulate if a vertex appears in multiple buckets.
    """
    import numpy as np
    N = len(src_mesh.data.vertices)
    offsets = np.zeros((N, 3))
    for vg_names, (x_mm, y_mm, z_mm) in recipe.items():
        w = _vg_weights(src_mesh, list(vg_names))
        offsets += w[:, None] * np.array([x_mm * 1e-3, y_mm * 1e-3, z_mm * 1e-3])

    mag = np.linalg.norm(offsets, axis=1)
    print(f"[progD] '{morph_name}': max={mag.max()*1000:.2f}mm  verts>0.5mm={int((mag>0.0005).sum())}")

    if src_mesh.data.shape_keys is None:
        src_mesh.shape_key_add(name='Basis', from_mix=False)
    kbs = src_mesh.data.shape_keys.key_blocks
    if morph_name in kbs:
        src_mesh.shape_key_remove(kbs[morph_name])
    sk = src_mesh.shape_key_add(name=morph_name, from_mix=False)
    rest = np.array([v.co[:] for v in src_mesh.data.vertices])
    for i, c in enumerate(rest + offsets):
        sk.data[i].co = Vector(c)
    return sk


# Recipes for Inase-XPS-style face rig.
# Convention: +Y = backward (into face), -Y = forward (toward viewer).
# Units in millimeters. X is lateral (L positive, R negative).
LIP_LOWER = ('head lip lower left', 'head lip lower middle', 'head lip lower right')
LIP_UPPER = ('head lip upper left', 'head lip upper middle', 'head lip upper right')
JAW       = ('head jaw',)
CORNER_L  = ('head mouth corner left',)
CORNER_R  = ('head mouth corner right',)
CORNER_BOTH = CORNER_L + CORNER_R

# Eyelid groups. L/R follow mesh vg naming (model-centric).
EYELID_UPPER_L = ('head eyelid upper left',)
EYELID_UPPER_R = ('head eyelid upper right',)
EYELID_LOWER_L = ('head eyelid lower left',)
EYELID_LOWER_R = ('head eyelid lower right',)

# Eyebrow groups. 1=inner (near nose), 2=middle, 3=outer (near temple).
BROW_L_INNER  = ('head eyebrow left 1',)
BROW_L_MID    = ('head eyebrow left 2',)
BROW_L_OUTER  = ('head eyebrow left 3',)
BROW_R_INNER  = ('head eyebrow right 1',)
BROW_R_MID    = ('head eyebrow right 2',)
BROW_R_OUTER  = ('head eyebrow right 3',)
BROW_L_ALL    = BROW_L_INNER + BROW_L_MID + BROW_L_OUTER
BROW_R_ALL    = BROW_R_INNER + BROW_R_MID + BROW_R_OUTER
BROW_ALL      = BROW_L_ALL + BROW_R_ALL
BROW_INNER_BOTH = BROW_L_INNER + BROW_R_INNER
BROW_OUTER_BOTH = BROW_L_OUTER + BROW_R_OUTER

INASE_RECIPES = {
    'あ': {  # mouth wide open
        JAW:         (0,  1, -3),
        LIP_LOWER:   (0,  2, -5),
        CORNER_BOTH: (0,  0, -2),
        LIP_UPPER:   (0,  0, +0.5),
    },
    'い': {  # flat wide, corners strongly outward + tight pressed
        CORNER_L:    (+8, 0, 0),
        CORNER_R:    (-8, 0, 0),
        LIP_LOWER:   (0,  0, +1),
        LIP_UPPER:   (0,  0, -1),
    },
    'う': {  # small round, corners inward, lips forward
        CORNER_L:    (-5, -3, 0),
        CORNER_R:    (+5, -3, 0),
        LIP_LOWER:   (0, -4, 0),
        LIP_UPPER:   (0, -4, 0),
    },
    'え': {  # half-open wide (jaw + corners out)
        CORNER_L:    (+4, 0, -1),
        CORNER_R:    (-4, 0, -1),
        LIP_LOWER:   (0,  1, -3),
        JAW:         (0,  0.5, -2.5),
    },
    'お': {  # round open (forward + down, corners in)
        LIP_LOWER:   (0, -4, -3),
        LIP_UPPER:   (0, -4, +1),
        CORNER_L:    (-3, -2.5, -1.5),
        CORNER_R:    (+3, -2.5, -1.5),
        JAW:         (0,  0.5, -3),
    },
    'ん': {  # close-mouth hum — lips press together, corners drawn in slightly
        LIP_LOWER:   (0, 0, +1.5),
        LIP_UPPER:   (0, 0, -1.5),
        CORNER_L:    (-1.5, 0, 0),
        CORNER_R:    (+1.5, 0, 0),
    },
    # --- Eyelids ---
    'まばたき': {  # both eyes closed
        EYELID_UPPER_L: (0, 0, -8),
        EYELID_UPPER_R: (0, 0, -8),
        EYELID_LOWER_L: (0, 0, +9),
        EYELID_LOWER_R: (0, 0, +9),
    },
    'ウィンク': {  # model-left eye wink (viewer's right)
        EYELID_UPPER_L: (0, 0, -8),
        EYELID_LOWER_L: (0, 0, +9),
    },
    'ウィンク右': {  # model-right eye wink (viewer's left)
        EYELID_UPPER_R: (0, 0, -8),
        EYELID_LOWER_R: (0, 0, +9),
    },
    # --- Eyebrows ---
    '困る': {  # troubled / sad — inner brow drops, outer stays
        BROW_INNER_BOTH: (0, 0, -10),
        BROW_OUTER_BOTH: (0, 0, +2),
    },
    '怒り': {  # angry — inner brow drops + pulled toward center
        BROW_L_INNER: (-4, 0, -8),
        BROW_R_INNER: (+4, 0, -8),
        BROW_OUTER_BOTH: (0, 0, -2),
    },
    '真面目': {  # serious / flat — whole brow lowered more noticeably
        BROW_ALL: (0, 0, -8),
    },
    '上': {  # brow raised
        BROW_ALL: (0, 0, +15),
    },
    '下': {  # brow lowered
        BROW_ALL: (0, 0, -15),
    },
    # --- Mouth extras ---
    'にやり': {  # smirk — mouth corners pulled up + outward
        CORNER_L:    (+4, 0, +5),
        CORNER_R:    (-4, 0, +5),
        LIP_UPPER:   (0,  0, +2),
    },
    '激怒': {  # angry mouth — tight pressed + corners pulled inward/down
        CORNER_L:    (-3, +1, -5),
        CORNER_R:    (+3, +1, -5),
        LIP_LOWER:   (0,  +1, -2),
        LIP_UPPER:   (0,  0, -2),
        JAW:         (0,  0, -2),
    },
    # --- Eye extras ---
    '笑い': {  # smile eyes (crescent shape — upper down slightly, lower up slightly)
        EYELID_UPPER_L: (0, 0, -3),
        EYELID_UPPER_R: (0, 0, -3),
        EYELID_LOWER_L: (0, 0, +4),
        EYELID_LOWER_R: (0, 0, +4),
    },
    'びっくり': {  # surprised — eyes wide open (upper up, lower down)
        EYELID_UPPER_L: (0, 0, +3),
        EYELID_UPPER_R: (0, 0, +3),
        EYELID_LOWER_L: (0, 0, -2),
        EYELID_LOWER_R: (0, 0, -2),
    },
    'じと目': {  # narrow/suspicious eyes (less close than まばたき)
        EYELID_UPPER_L: (0, 0, -5),
        EYELID_UPPER_R: (0, 0, -5),
        EYELID_LOWER_L: (0, 0, +2),
        EYELID_LOWER_R: (0, 0, +2),
    },
}


def bake_all_mouth_recipes(src_mesh, recipes=INASE_RECIPES):
    results = []
    for name, recipe in recipes.items():
        sk = bake_programmatic_morph(src_mesh, name, recipe)
        results.append((name, sk))
    return results


def bake_eyeball_recede(eyeball_mesh, morph_name, back_mm=6.0, side='both'):
    """For eye-closing morphs, push eyeball mesh backward into socket so it
    doesn't protrude past a closed face-mesh eyelid.

    eyeball_mesh: object (e.g. Inase XPS 24_0006 eyes mesh).
    back_mm: how many mm in +Y direction (per XPS convention, +Y = backward).
    side: 'both' | 'left' | 'right' — per-vert X filter (Blender +X = model-left).
    """
    import numpy as np
    if eyeball_mesh.data.shape_keys is None:
        eyeball_mesh.shape_key_add(name='Basis', from_mix=False)
    kbs = eyeball_mesh.data.shape_keys.key_blocks
    if morph_name in kbs:
        eyeball_mesh.shape_key_remove(kbs[morph_name])
    sk = eyeball_mesh.shape_key_add(name=morph_name, from_mix=False)
    rest = np.array([v.co[:] for v in eyeball_mesh.data.vertices])
    offset = np.zeros_like(rest)
    if side == 'both':
        mask = np.ones(len(rest), dtype=bool)
    elif side == 'left':
        mask = rest[:, 0] > 0  # model-left
    elif side == 'right':
        mask = rest[:, 0] < 0  # model-right
    else:
        raise ValueError(f"side must be 'both'|'left'|'right', got {side!r}")
    offset[mask, 1] = back_mm * 1e-3  # +Y backward
    for i, c in enumerate(rest + offset):
        sk.data[i].co = Vector(c)
    print(f"[eye-recede] '{morph_name}' on {eyeball_mesh.name}: {back_mm}mm back, side={side} ({int(mask.sum())}/{len(rest)} verts)")
    return sk


EYEBALL_MORPHS = ('まばたき', 'ウィンク', 'ウィンク右', '笑い')  # morphs that should hide eyeball


MOUTH_MORPH_NAMES   = ('あ', 'い', 'う', 'え', 'お', 'ん', 'にやり', '激怒')
EYELID_MORPH_NAMES  = ('まばたき', 'ウィンク', 'ウィンク右', '笑い', 'びっくり', 'じと目')
BROW_MORPH_NAMES    = ('困る', '怒り', '真面目', '上', '下')


def set_morph_synced(meshes, morph_name, value=1.0):
    """Reset all non-basis sliders on every listed mesh, then set `morph_name`
    slider to `value` on every mesh that has it. Prevents cross-mesh
    slider drift during test/verify."""
    for m in meshes:
        if m is None or m.data.shape_keys is None:
            continue
        for k in m.data.shape_keys.key_blocks:
            if k.name != 'Basis':
                k.value = 0.0
        if morph_name in m.data.shape_keys.key_blocks:
            m.data.shape_keys.key_blocks[morph_name].value = float(value)
    bpy.context.view_layer.update()


def bake_all_for_inase(face_mesh, eyelash_meshes, eyebrow_mesh, eyeball_mesh,
                        recipes=INASE_RECIPES):
    """Apply recipes to every relevant mesh. Each mesh only gets the morphs
    whose vertex groups it actually has.

    face_mesh: main skin (all vgs)
    eyelash_meshes: list of eyelash meshes (only eyelid vgs)
    eyebrow_mesh: eyebrow hair mesh (only eyebrow vgs)
    eyeball_mesh: eyeballs (no vg, uses recede helper)
    """
    # Main face gets all recipes
    bake_all_mouth_recipes(face_mesh, recipes)

    # Eyelashes: only eyelid subset
    eyelid_subset = {n: recipes[n] for n in EYELID_MORPH_NAMES if n in recipes}
    for m in eyelash_meshes:
        bake_all_mouth_recipes(m, eyelid_subset)

    # Eyebrow mesh: only brow subset
    brow_subset = {n: recipes[n] for n in BROW_MORPH_NAMES if n in recipes}
    if eyebrow_mesh is not None:
        bake_all_mouth_recipes(eyebrow_mesh, brow_subset)

    # Eyeball mesh: recede for eye-closing morphs
    if eyeball_mesh is not None:
        bake_eyeball_morphs_for_wink(eyeball_mesh)

    print("[bake_all_for_inase] done on all meshes")


EYEBALL_SIDES = {  # per-vertex X filter for single-eye winks
    'まばたき':  'both',
    'ウィンク':   'left',   # model-left eye wink
    'ウィンク右': 'right',  # model-right eye wink
    '笑い':      'both',
}


def bake_eyeball_morphs_for_wink(eyeball_mesh, morph_names=EYEBALL_MORPHS, back_mm=6.0):
    """Add the above shape keys on an eyeball mesh too.

    Per-morph side filter (EYEBALL_SIDES): single-eye winks only recede the
    corresponding eye, both-eye closers recede both.
    """
    results = []
    for n in morph_names:
        side = EYEBALL_SIDES.get(n, 'both')
        sk = bake_eyeball_recede(eyeball_mesh, n, back_mm, side=side)
        results.append((n, sk))
    return results


# ---------- P0 Tool C: batch morph verification (screenshot + HTML report) ----------

VIEW_PRESETS = {
    # (view_location_z, view_distance) for XPS-scale Inase model. Front ortho.
    'face':  (1.60, 0.18),   # whole face
    'eye':   (1.64, 0.05),   # eye region close-up
    'mouth': (1.55, 0.06),   # mouth region close-up
    'brow':  (1.66, 0.07),   # brow region
}


def _morph_preset(morph_name):
    if morph_name in EYELID_MORPH_NAMES:
        return 'eye'
    if morph_name in MOUTH_MORPH_NAMES:
        return 'mouth'
    if morph_name in BROW_MORPH_NAMES:
        return 'brow'
    return 'face'


def _apply_view_preset(preset):
    """Set every VIEW_3D area to front ortho at the preset's z/distance."""
    z, d = VIEW_PRESETS[preset]
    for a in bpy.context.screen.areas:
        if a.type == 'VIEW_3D':
            r3d = a.spaces.active.region_3d
            r3d.view_perspective = 'ORTHO'
            r3d.view_rotation = (0.7071, 0.7071, 0, 0)
            r3d.view_location = Vector((0, 0, z))
            r3d.view_distance = d


def _opengl_render(filepath):
    """Render the first VIEW_3D area's current viewport to filepath (PNG)."""
    scene = bpy.context.scene
    scene.render.filepath = filepath
    scene.render.image_settings.file_format = 'PNG'
    for a in bpy.context.screen.areas:
        if a.type == 'VIEW_3D':
            with bpy.context.temp_override(area=a):
                bpy.ops.render.opengl(write_still=True)
            return True
    return False


def screenshot_all_morphs(meshes, out_dir='/tmp/morph_verify'):
    """Iterate every non-Basis shape key on meshes[0] (face), set slider=1.0
    via set_morph_synced across all meshes, OpenGL-render a categorised
    preset view, write PNG per morph + a basis reference.

    meshes: [face, lash1, lash2, brow, eyeball] ordering expected.
    """
    import os
    os.makedirs(out_dir, exist_ok=True)
    face = meshes[0]
    morph_names = [k.name for k in face.data.shape_keys.key_blocks if k.name != 'Basis']

    results = []
    # 3 basis shots, one per view preset category (for side-by-side comparison).
    set_morph_synced(meshes, '__reset__', 0.0)
    for preset in ('face', 'eye', 'mouth', 'brow'):
        _apply_view_preset(preset)
        p = os.path.join(out_dir, f'__basis_{preset}.png')
        _opengl_render(p)
        results.append((f'__basis_{preset}', p))

    for name in morph_names:
        set_morph_synced(meshes, name, 1.0)
        preset = _morph_preset(name)
        _apply_view_preset(preset)
        p = os.path.join(out_dir, f'{name}.png')
        _opengl_render(p)
        results.append((name, p))
        print(f"[verify] {name} ({preset}) -> {p}")

    set_morph_synced(meshes, '__reset__', 0.0)
    print(f"[verify] wrote {len(results)} PNGs to {out_dir}")
    return results


def generate_morph_html_report(out_dir='/tmp/morph_verify', report_path=None):
    """Scan out_dir for PNGs, write index.html grouping morphs by category
    (mouth/eyelid/brow) with the matching basis reference shown alongside."""
    import os
    if report_path is None:
        report_path = os.path.join(out_dir, 'index.html')

    groups = [
        ('Mouth',  'mouth', MOUTH_MORPH_NAMES),
        ('Eyelid', 'eye',   EYELID_MORPH_NAMES),
        ('Brow',   'brow',  BROW_MORPH_NAMES),
    ]

    parts = [
        '<!doctype html><html><head><meta charset="utf-8">',
        '<title>Morph Verification</title><style>',
        'body{font-family:sans-serif;background:#222;color:#eee;margin:20px}',
        'h1{margin-bottom:4px}h2{margin-top:28px;border-bottom:1px solid #555;padding-bottom:4px}',
        '.row{display:flex;flex-wrap:wrap;gap:12px;margin:8px 0}',
        '.cell{background:#333;padding:6px;border-radius:4px}',
        '.cell.basis{border:2px solid #5a5}',
        '.cell img{display:block;width:280px;height:auto}',
        '.cell .name{font-size:12px;margin-top:4px;text-align:center}',
        '</style></head><body>',
        f'<h1>MMD Morph Verification</h1>',
        f'<p>Source: {out_dir}</p>',
    ]

    for title, preset, names in groups:
        parts.append(f'<h2>{title}</h2><div class="row">')
        basis_png = f'__basis_{preset}.png'
        if os.path.exists(os.path.join(out_dir, basis_png)):
            parts.append(f'<div class="cell basis"><img src="{basis_png}"><div class="name">(basis)</div></div>')
        for n in names:
            fp = f'{n}.png'
            if os.path.exists(os.path.join(out_dir, fp)):
                parts.append(f'<div class="cell"><img src="{fp}"><div class="name">{n}</div></div>')
        parts.append('</div>')

    parts.append('</body></html>')
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(parts))
    print(f"[verify] wrote HTML report: {report_path}")
    return report_path


# ---------- P0 Tool B: automated morph spec check ----------

INASE_MORPH_SPECS = {
    # (max_mm_lo, max_mm_hi, moved_verts_min)
    'あ':     (3.0, 10.0, 50),
    'い':     (2.0, 12.0, 30),
    'う':     (2.0, 10.0, 30),
    'え':     (2.0, 8.0,  30),
    'お':     (3.0, 10.0, 30),
    'ん':     (1.0, 4.0,  20),
    'にやり':  (3.0, 10.0, 20),
    '激怒':    (3.0, 10.0, 30),
    'まばたき': (5.0, 15.0, 40),
    'ウィンク':  (5.0, 15.0, 20),
    'ウィンク右': (5.0, 15.0, 20),
    '笑い':    (2.0, 8.0,  20),
    'びっくり': (1.0, 5.0,  20),
    'じと目':  (1.0, 6.0,  20),
    '困る':    (5.0, 15.0, 20),
    '怒り':    (4.0, 15.0, 20),
    '真面目':  (5.0, 12.0, 20),
    '上':     (8.0, 20.0, 20),
    '下':     (8.0, 20.0, 20),
}


def verify_morph_data(mesh, morph_name, spec):
    """Compare one shape key's delta to spec (max_mm_lo, max_mm_hi, moved_min).
    Returns (ok, max_mm, moved_count, violations_list)."""
    import numpy as np
    violations = []
    kbs = mesh.data.shape_keys.key_blocks if mesh.data.shape_keys else None
    if kbs is None or morph_name not in kbs:
        return False, 0.0, 0, [f"shape key missing"]
    sk = kbs[morph_name]
    rest = np.array([v.co[:] for v in mesh.data.vertices])
    morph = np.array([sk.data[i].co[:] for i in range(len(rest))])
    mag = np.linalg.norm(morph - rest, axis=1)
    max_mm = float(mag.max() * 1000)
    moved = int((mag > 1e-5).sum())
    lo, hi, mv_min = spec
    if max_mm < lo:
        violations.append(f"max={max_mm:.2f}mm below min {lo}mm")
    if max_mm > hi:
        violations.append(f"max={max_mm:.2f}mm exceeds max {hi}mm")
    if moved < mv_min:
        violations.append(f"only {moved} verts moved (min {mv_min})")
    return (not violations), max_mm, moved, violations


def verify_all_morphs(meshes, specs=None):
    """Run spec check on meshes[0]. Returns dict {morph: (ok, max_mm, moved, viols)}."""
    if specs is None:
        specs = INASE_MORPH_SPECS
    face = meshes[0]
    results = {}
    for name, spec in specs.items():
        ok, max_mm, moved, viols = verify_morph_data(face, name, spec)
        results[name] = (ok, max_mm, moved, viols)
        tag = 'OK  ' if ok else 'FAIL'
        print(f"[verify-B] {tag} {name:6s} max={max_mm:5.2f}mm moved={moved:4d}" + (f"  {viols}" if viols else ""))
    n_ok = sum(1 for v in results.values() if v[0])
    print(f"\n[verify-B] {n_ok}/{len(results)} pass spec")
    return results


# ---------- P0 Tool A: interactive UI modal verification ----------

_verify_meshes_cache = []  # module-level stash for operator invoke


def start_verify_modal(meshes):
    """Stash meshes for the modal operator and invoke it. Call this from a
    cli.py exec; keyboard control then happens in the Blender window.

    Keys (focus the 3D viewport):
      O = OK, X = Issue, N = Skip/Next, ESC = Quit
    """
    global _verify_meshes_cache
    _verify_meshes_cache = list(meshes)
    bpy.ops.morph.verify_modal('INVOKE_DEFAULT')


class MORPH_OT_verify_modal(bpy.types.Operator):
    bl_idname = "morph.verify_modal"
    bl_label = "Verify Morphs (Interactive)"
    bl_description = "Cycle through every baked morph and record OK/Issue via keyboard"

    def invoke(self, context, event):
        if not _verify_meshes_cache:
            self.report({'ERROR'}, "Call start_verify_modal(meshes) first")
            return {'CANCELLED'}
        self.meshes = _verify_meshes_cache
        face = self.meshes[0]
        if face.data.shape_keys is None:
            self.report({'ERROR'}, "Face mesh has no shape keys")
            return {'CANCELLED'}
        self.morph_names = [k.name for k in face.data.shape_keys.key_blocks if k.name != 'Basis']
        if not self.morph_names:
            self.report({'ERROR'}, "No non-basis shape keys found")
            return {'CANCELLED'}
        self.idx = 0
        self.results = {}
        self._apply_current()
        self._draw_status(context)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _apply_current(self):
        set_morph_synced(self.meshes, self.morph_names[self.idx], 1.0)

    def _draw_status(self, context):
        if self.idx < len(self.morph_names):
            name = self.morph_names[self.idx]
            msg = f"[Verify] {self.idx+1}/{len(self.morph_names)} '{name}'  —  O=OK  X=Issue  N=Skip  ESC=Quit"
        else:
            n_ok = sum(1 for v in self.results.values() if v == 'OK')
            n_issue = sum(1 for v in self.results.values() if v == 'ISSUE')
            msg = f"[Verify] done: {n_ok} OK, {n_issue} issue. ESC to exit."
        context.workspace.status_text_set(msg)

    def modal(self, context, event):
        if event.type == 'ESC' and event.value == 'PRESS':
            self._finish(context)
            return {'CANCELLED'}
        if event.value != 'PRESS':
            return {'PASS_THROUGH'}
        if event.type in {'O', 'X', 'N'} and self.idx < len(self.morph_names):
            label = {'O': 'OK', 'X': 'ISSUE', 'N': 'SKIPPED'}[event.type]
            self.results[self.morph_names[self.idx]] = label
            self.idx += 1
            if self.idx < len(self.morph_names):
                self._apply_current()
            self._draw_status(context)
            if self.idx >= len(self.morph_names):
                self._finish(context)
                return {'FINISHED'}
            return {'RUNNING_MODAL'}
        return {'PASS_THROUGH'}

    def _finish(self, context):
        set_morph_synced(self.meshes, '__reset__', 0.0)
        context.workspace.status_text_set(None)
        print("\n[Verify-A] results:")
        for name in self.morph_names:
            v = self.results.get(name, '(not reviewed)')
            print(f"  {v:10s} {name}")
        n_ok = sum(1 for v in self.results.values() if v == 'OK')
        n_issue = sum(1 for v in self.results.values() if v == 'ISSUE')
        n_skip = sum(1 for v in self.results.values() if v == 'SKIPPED')
        print(f"[Verify-A] {n_ok} OK, {n_issue} issue, {n_skip} skipped")


EYE_BONE_VG_NAMES = ('目.L', '目.R', 'head eyeball left', 'head eyeball right')


def find_inase_meshes():
    """Auto-detect [face, lash1, lash2, brow, eyeball] from scene.

    Two strategies, tried in order:
      1. **vg probe** — works BEFORE addon step-6 cleanup_face_bones.
         face requires lip+eyelid+eyebrow; brow/lash/eyeball by their
         respective face-detail vgs + eye-bone vg.
      2. **shape-key probe** (fallback) — works AFTER cleanup_face_bones
         once the morphs are already baked. Identifies each mesh by
         which morph subset is present (face has all three categories;
         brow has only brow morphs; lash/eyeball distinguished by eye-bone vg).

    Returns list of 5 objects, or None if any slot missing.
    """
    result = _find_inase_meshes_by_vgs()
    if result:
        return result
    return _find_inase_meshes_by_morphs()


def _find_inase_meshes_by_vgs():
    """Pre-cleanup detection: face requires lip+eyelid+eyebrow vgs all present.
    Why three-vg face check: tooth mesh (e.g. Inase 24_0005) rigs to `head lip`
    too but has no eyelid/eyebrow, so a lone has_lip check misidentifies teeth.
    """
    face = None
    lashes = []
    brow = None
    eyeball = None
    for o in bpy.data.objects:
        if o.type != 'MESH':
            continue
        vg_names = {vg.name for vg in o.vertex_groups}
        has_lip = any(n.startswith('head lip') for n in vg_names)
        has_eyelid = any(n.startswith('head eyelid') for n in vg_names)
        has_brow = any(n.startswith('head eyebrow') for n in vg_names)
        has_eye_bone = any(n in vg_names for n in EYE_BONE_VG_NAMES)
        if has_lip and has_eyelid and has_brow:
            face = o
        elif has_brow and not has_lip:
            brow = o
        elif has_eyelid and not has_lip and not has_brow:
            lashes.append(o)
        elif has_eye_bone and not has_lip and not has_eyelid and not has_brow and len(vg_names) < 10:
            eyeball = o
    if face and len(lashes) == 2 and brow and eyeball:
        return [face, lashes[0], lashes[1], brow, eyeball]
    return None


def _find_inase_meshes_by_morphs():
    """Post-cleanup + post-bake detection via shape keys.
    face has all 3 category morphs; brow only brow morphs; lash vs eyeball
    distinguished by eye-bone vg presence.
    """
    face = None
    lashes = []
    brow = None
    eyeball = None
    for o in bpy.data.objects:
        if o.type != 'MESH' or o.data.shape_keys is None:
            continue
        kbs = {k.name for k in o.data.shape_keys.key_blocks}
        vg_names = {vg.name for vg in o.vertex_groups}
        has_mouth = 'あ' in kbs
        has_eyelid = 'まばたき' in kbs
        has_brow = '困る' in kbs
        has_eye_bone = any(n in vg_names for n in EYE_BONE_VG_NAMES)
        if has_mouth and has_eyelid and has_brow:
            face = o
        elif has_brow and not has_mouth:
            brow = o
        elif has_eyelid and not has_mouth and not has_brow:
            if has_eye_bone and len(vg_names) < 10:
                eyeball = o
            else:
                lashes.append(o)
    if face and len(lashes) == 2 and brow and eyeball:
        return [face, lashes[0], lashes[1], brow, eyeball]
    return None


class MORPH_OT_run_spec_check(bpy.types.Operator):
    bl_idname = "morph.run_spec_check"
    bl_label = "Run Spec Check (Tool B)"
    bl_description = "Automated max/moved-verts check against INASE_MORPH_SPECS"

    def execute(self, context):
        meshes = find_inase_meshes()
        if meshes is None:
            self.report({'ERROR'}, "Inase meshes not found — bake morphs first")
            return {'CANCELLED'}
        results = verify_all_morphs(meshes)
        n_pass = sum(1 for v in results.values() if v[0])
        n_total = len(results)
        if n_pass == n_total:
            self.report({'INFO'}, f"{n_pass}/{n_total} pass spec")
        else:
            fails = [n for n, v in results.items() if not v[0]]
            self.report({'WARNING'}, f"{n_pass}/{n_total} pass — FAIL: {', '.join(fails)}")
        return {'FINISHED'}


class MORPH_OT_run_batch_screenshot(bpy.types.Operator):
    bl_idname = "morph.run_batch_screenshot"
    bl_label = "Batch Screenshot + HTML (Tool C)"
    bl_description = "Render every morph to /tmp/morph_verify + index.html"
    out_dir: bpy.props.StringProperty(default='/tmp/morph_verify')  # type: ignore

    def execute(self, context):
        meshes = find_inase_meshes()
        if meshes is None:
            self.report({'ERROR'}, "Inase meshes not found — bake morphs first")
            return {'CANCELLED'}
        screenshot_all_morphs(meshes, self.out_dir)
        generate_morph_html_report(self.out_dir)
        self.report({'INFO'}, f"wrote {self.out_dir}/index.html")
        return {'FINISHED'}


class MORPH_OT_start_verify_modal(bpy.types.Operator):
    bl_idname = "morph.start_verify_modal"
    bl_label = "Verify Interactive (Tool A)"
    bl_description = "Cycle every morph; hover 3D viewport and press O/X/N/ESC"

    def execute(self, context):
        meshes = find_inase_meshes()
        if meshes is None:
            self.report({'ERROR'}, "Inase meshes not found — bake morphs first")
            return {'CANCELLED'}
        global _verify_meshes_cache
        _verify_meshes_cache = meshes
        bpy.ops.morph.verify_modal('INVOKE_DEFAULT')
        return {'FINISHED'}


# Operator classes (registered by the addon __init__, not here):
VERIFY_OPERATORS = (
    MORPH_OT_verify_modal,
    MORPH_OT_run_spec_check,
    MORPH_OT_run_batch_screenshot,
    MORPH_OT_start_verify_modal,
)


