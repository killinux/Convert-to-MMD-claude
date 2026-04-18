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

from . import morph_rigs
from .morph_rigs import ALL_SLOTS, RIG_MAPS


# ---------- Path D: programmatic per-mesh morph synthesis ----------

def _expand_slot_pattern(pattern):
    """Expand a slot pattern to concrete slot names.

    '*' matches any single segment (between dots). Examples:
      'jaw'            → ['jaw']
      'lip.lower.*'    → ['lip.lower.L','lip.lower.M','lip.lower.R']
      'brow.*.L'       → ['brow.inner.L','brow.mid.L','brow.outer.L']
      'lip.corner.*'   → ['lip.corner.L','lip.corner.R']

    Returns sorted list. Unknown literal slot → empty list (recipe typo).
    """
    if '*' not in pattern:
        return [pattern] if pattern in ALL_SLOTS else []
    import re
    regex = re.compile('^' + re.escape(pattern).replace(r'\*', r'[^.]+') + '$')
    return sorted(s for s in ALL_SLOTS if regex.match(s))


def detect_rig():
    """Pick the rig whose signature vg is present in the scene.

    Signature ordering matters: check specific rigs first, fall back to
    more general ones. Returns rig key (see RIG_MAPS) or None.
    """
    all_vgs = set()
    for o in bpy.data.objects:
        if o.type == 'MESH':
            all_vgs |= {vg.name for vg in o.vertex_groups}
    # XPS Inase / XNA Lara family: distinctive `head lip lower middle`
    if 'head lip lower middle' in all_vgs:
        return 'xps_inase'
    # DAZ Genesis 8 family: distinctive `LipLowerMiddle` (no space, capitalised)
    if 'LipLowerMiddle' in all_vgs:
        return 'daz_g8'
    # Future: Mixamo / VRoid / iClone / Bip_001 signatures
    return None


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


def bake_programmatic_morph(src_mesh, morph_name, recipe, rig_map):
    """Generic programmatic morph synthesizer (slot-based).

    recipe: dict mapping
      slot_pattern_str -> (x_mm, y_mm, z_mm)
    where slot_pattern_str is a dot-separated slot name with optional '*'
    wildcards ('lip.lower.*', 'brow.inner.L', 'jaw').

    rig_map: dict mapping slot_name -> list[vg_name] for this rig. Slots
    missing from the rig map are silently skipped (lets a recipe target
    a slot some rigs don't have, e.g. cheek).

    For each recipe entry, summed weight across the resolved vgs masks
    the offset. Offsets accumulate if a vertex appears in multiple
    buckets.
    """
    import numpy as np
    N = len(src_mesh.data.vertices)
    offsets = np.zeros((N, 3))
    for slot_pattern, (x_mm, y_mm, z_mm) in recipe.items():
        slots = _expand_slot_pattern(slot_pattern)
        vg_names = []
        for s in slots:
            vg_names.extend(rig_map.get(s, []))
        if not vg_names:
            continue
        w = _vg_weights(src_mesh, vg_names)
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


# Universal MMD morph recipes (slot-based, rig-agnostic).
# Convention: +Y = backward (into face), -Y = forward (toward viewer).
# Units in millimeters. X is lateral (+L, -R). Offsets tuned against
# Inase XPS; magnitudes may need per-rig adjustment if proportions differ.
UNIVERSAL_RECIPES = {
    'あ': {  # mouth wide open
        'jaw':            (0,  1, -3),
        'lip.lower.*':    (0,  2, -5),
        'lip.corner.*':   (0,  0, -2),
        'lip.upper.*':    (0,  0, +0.5),
    },
    'い': {  # flat wide, corners strongly outward + tight pressed
        'lip.corner.L':   (+8, 0, 0),
        'lip.corner.R':   (-8, 0, 0),
        'lip.lower.*':    (0,  0, +1),
        'lip.upper.*':    (0,  0, -1),
    },
    'う': {  # small round, corners inward, lips forward
        'lip.corner.L':   (-5, -3, 0),
        'lip.corner.R':   (+5, -3, 0),
        'lip.lower.*':    (0, -4, 0),
        'lip.upper.*':    (0, -4, 0),
    },
    'え': {  # half-open wide (jaw + corners out)
        'lip.corner.L':   (+4, 0, -1),
        'lip.corner.R':   (-4, 0, -1),
        'lip.lower.*':    (0,  1, -3),
        'jaw':            (0,  0.5, -2.5),
    },
    'お': {  # round open (forward + down, corners in)
        'lip.lower.*':    (0, -4, -3),
        'lip.upper.*':    (0, -4, +1),
        'lip.corner.L':   (-3, -2.5, -1.5),
        'lip.corner.R':   (+3, -2.5, -1.5),
        'jaw':            (0,  0.5, -3),
    },
    'ん': {  # close-mouth hum — lips press together, corners drawn in slightly
        'lip.lower.*':    (0, 0, +1.5),
        'lip.upper.*':    (0, 0, -1.5),
        'lip.corner.L':   (-1.5, 0, 0),
        'lip.corner.R':   (+1.5, 0, 0),
    },
    # --- Eyelids ---
    'まばたき': {  # both eyes closed
        'eyelid.upper.L': (0, 0, -8),
        'eyelid.upper.R': (0, 0, -8),
        'eyelid.lower.L': (0, 0, +9),
        'eyelid.lower.R': (0, 0, +9),
    },
    'ウィンク': {  # model-left eye wink (viewer's right)
        'eyelid.upper.L': (0, 0, -8),
        'eyelid.lower.L': (0, 0, +9),
    },
    'ウィンク右': {  # model-right eye wink (viewer's left)
        'eyelid.upper.R': (0, 0, -8),
        'eyelid.lower.R': (0, 0, +9),
    },
    # --- Eyebrows ---
    '困る': {  # troubled / sad — inner brow drops, outer stays
        'brow.inner.*':   (0, 0, -10),
        'brow.outer.*':   (0, 0, +2),
    },
    '怒り': {  # angry — inner brow drops + pulled toward center
        'brow.inner.L':   (-4, 0, -8),
        'brow.inner.R':   (+4, 0, -8),
        'brow.outer.*':   (0, 0, -2),
    },
    '真面目': {  # serious / flat — whole brow lowered more noticeably
        'brow.*.*':       (0, 0, -8),
    },
    '上': {  # brow raised
        'brow.*.*':       (0, 0, +15),
    },
    '下': {  # brow lowered
        'brow.*.*':       (0, 0, -15),
    },
    # --- Mouth extras ---
    'にやり': {  # smirk — mouth corners pulled up + outward
        'lip.corner.L':   (+4, 0, +5),
        'lip.corner.R':   (-4, 0, +5),
        'lip.upper.*':    (0,  0, +2),
    },
    '激怒': {  # angry mouth — tight pressed + corners pulled inward/down
        'lip.corner.L':   (-3, +1, -5),
        'lip.corner.R':   (+3, +1, -5),
        'lip.lower.*':    (0,  +1, -2),
        'lip.upper.*':    (0,  0, -2),
        'jaw':            (0,  0, -2),
    },
    # --- Eye extras ---
    '笑い': {  # smile eyes (crescent shape — upper down slightly, lower up slightly)
        'eyelid.upper.L': (0, 0, -3),
        'eyelid.upper.R': (0, 0, -3),
        'eyelid.lower.L': (0, 0, +4),
        'eyelid.lower.R': (0, 0, +4),
    },
    'びっくり': {  # surprised — eyes wide open (upper up, lower down)
        'eyelid.upper.L': (0, 0, +3),
        'eyelid.upper.R': (0, 0, +3),
        'eyelid.lower.L': (0, 0, -2),
        'eyelid.lower.R': (0, 0, -2),
    },
    'じと目': {  # narrow/suspicious eyes (less close than まばたき)
        'eyelid.upper.L': (0, 0, -5),
        'eyelid.upper.R': (0, 0, -5),
        'eyelid.lower.L': (0, 0, +2),
        'eyelid.lower.R': (0, 0, +2),
    },
}


def bake_all_mouth_recipes(src_mesh, recipes, rig_map):
    results = []
    for name, recipe in recipes.items():
        sk = bake_programmatic_morph(src_mesh, name, recipe, rig_map)
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


def apply_morph_categories(mmd_root_obj):
    """Set mmd_root.vertex_morphs[*].category based on canonical MMD grouping.

    mmd_tools convert_to_mmd_model creates vertex_morphs with category=OTHER.
    PMX viewers organise morph sliders by category; without this fix the
    19 synthesised morphs all land in 'Other' and are awkward to scrub.
    """
    try:
        vms = mmd_root_obj.mmd_root.vertex_morphs
    except AttributeError:
        return 0
    changed = 0
    for m in vms:
        if m.name in MOUTH_MORPH_NAMES:
            cat = 'MOUTH'
        elif m.name in EYELID_MORPH_NAMES:
            cat = 'EYE'
        elif m.name in BROW_MORPH_NAMES:
            cat = 'EYEBROW'
        else:
            continue
        if m.category != cat:
            m.category = cat
            changed += 1
    return changed


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


def bake_all_universal(meshes_by_role, rig_map, recipes=UNIVERSAL_RECIPES):
    """Apply recipes to every mesh by its role.

    meshes_by_role: dict {role: [mesh,...]} from find_meshes_by_role()
      primary_face   — full recipe (all morphs)
      mouth_interior — skipped by default (Inase teeth, DAZ 4_Mouth)
      eyelashes      — only eyelid subset
      eyebrow        — only brow subset (Inase has dedicated mesh; DAZ empty)
      eyeball        — eye-recede helper for closing morphs
    rig_map: slot → vg names for this rig (see morph_rigs.py).
    """
    for m in meshes_by_role.get('primary_face', []):
        bake_all_mouth_recipes(m, recipes, rig_map)

    eyelid_subset = {n: recipes[n] for n in EYELID_MORPH_NAMES if n in recipes}
    for m in meshes_by_role.get('eyelashes', []):
        bake_all_mouth_recipes(m, eyelid_subset, rig_map)

    brow_subset = {n: recipes[n] for n in BROW_MORPH_NAMES if n in recipes}
    for m in meshes_by_role.get('eyebrow', []):
        bake_all_mouth_recipes(m, brow_subset, rig_map)

    for m in meshes_by_role.get('eyeball', []):
        bake_eyeball_morphs_for_wink(m)

    print(f"[bake_all_universal] primary_face={len(meshes_by_role.get('primary_face',[]))} "
          f"eyelashes={len(meshes_by_role.get('eyelashes',[]))} "
          f"eyebrow={len(meshes_by_role.get('eyebrow',[]))} "
          f"eyeball={len(meshes_by_role.get('eyeball',[]))}")


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


MESH_ROLES = ('primary_face', 'mouth_interior', 'eyelashes', 'eyebrow', 'eyeball')


def _slot_family_vgs(rig_map, prefix):
    """Gather all vg names for slots starting with prefix (e.g. 'lip.')."""
    vgs = set()
    for slot in ALL_SLOTS:
        if slot.startswith(prefix):
            vgs |= set(rig_map.get(slot, []))
    return vgs


def find_meshes_by_role(rig_map):
    """Classify every mesh by its face-slot vg signature.

    Returns {role: [mesh, ...]}. Meshes not matching any role are dropped.
    Two-phase fallback: pre-cleanup uses vg names (same file as rig_map);
    post-cleanup/post-bake uses shape-key presence (morph names).
    """
    result = find_meshes_by_role_vgs(rig_map)
    if any(result.values()):
        return result
    return find_meshes_by_role_morphs(rig_map)


def find_meshes_by_role_vgs(rig_map):
    """Pre-cleanup: classify by which rig_map vg names each mesh has."""
    lip_vgs = _slot_family_vgs(rig_map, 'lip.')
    eyelid_vgs = _slot_family_vgs(rig_map, 'eyelid.')
    brow_vgs = _slot_family_vgs(rig_map, 'brow.')
    eye_bone_vgs = set(rig_map.get('_eye_bone_vgs', []))

    result = {role: [] for role in MESH_ROLES}
    for o in bpy.data.objects:
        if o.type != 'MESH':
            continue
        vgs = {vg.name for vg in o.vertex_groups}
        has_lip = bool(vgs & lip_vgs)
        has_eyelid = bool(vgs & eyelid_vgs)
        has_brow = bool(vgs & brow_vgs)
        has_eye_bone = bool(vgs & eye_bone_vgs)

        # Ordering: brow rule BEFORE eyelid, because Inase brow hair mesh
        # (7_0003) has both brow + eyelid vgs — brow takes precedence.
        if has_lip and has_eyelid and has_brow:
            result['primary_face'].append(o)
        elif has_lip and not has_eyelid and not has_brow:
            # Teeth (Inase 24_0005) / mouth interior (DAZ 4_Mouth)
            result['mouth_interior'].append(o)
        elif has_brow and not has_lip:
            # Eyebrow-hair mesh (may also carry eyelid vgs for edge blend)
            result['eyebrow'].append(o)
        elif has_eyelid and not has_lip and not has_brow:
            result['eyelashes'].append(o)
        elif (has_eye_bone and not has_lip and not has_eyelid
              and not has_brow and len(vgs) < 10):
            result['eyeball'].append(o)
    return result


def find_meshes_by_role_morphs(rig_map):
    """Post-cleanup/post-bake: classify by which morph shape keys each mesh has."""
    eye_bone_vgs = set(rig_map.get('_eye_bone_vgs', []))
    result = {role: [] for role in MESH_ROLES}
    for o in bpy.data.objects:
        if o.type != 'MESH' or o.data.shape_keys is None:
            continue
        kbs = {k.name for k in o.data.shape_keys.key_blocks}
        vgs = {vg.name for vg in o.vertex_groups}
        has_mouth = 'あ' in kbs
        has_eyelid = 'まばたき' in kbs
        has_brow = '困る' in kbs
        has_eye_bone = bool(vgs & eye_bone_vgs)

        # Ordering mirrors the vg-path (brow before eyelid)
        if has_mouth and has_eyelid and has_brow:
            result['primary_face'].append(o)
        elif has_mouth and not has_eyelid and not has_brow:
            result['mouth_interior'].append(o)
        elif has_brow and not has_mouth:
            result['eyebrow'].append(o)
        elif has_eyelid and not has_mouth and not has_brow:
            if has_eye_bone and len(vgs) < 10:
                result['eyeball'].append(o)
            else:
                result['eyelashes'].append(o)
    return result


def _find_verify_meshes():
    """Return ordered list for verify operators: [primary_face, eyelashes..., eyebrow, eyeball]
    or None if primary_face is missing (no morphs yet). Preserves old 5-mesh signature
    roughly; callers that need structured access should use find_meshes_by_role directly.
    """
    rig = detect_rig()
    if rig is None:
        return None
    by_role = find_meshes_by_role(RIG_MAPS[rig])
    primary = by_role.get('primary_face') or []
    if not primary:
        return None
    out = [primary[0]]
    out.extend(by_role.get('eyelashes', []))
    out.extend(by_role.get('eyebrow', []))
    out.extend(by_role.get('eyeball', []))
    return out


class MORPH_OT_run_spec_check(bpy.types.Operator):
    bl_idname = "morph.run_spec_check"
    bl_label = "Run Spec Check (Tool B)"
    bl_description = "Automated max/moved-verts check against morph spec"

    def execute(self, context):
        meshes = _find_verify_meshes()
        if meshes is None:
            self.report({'ERROR'}, "No rig detected or primary_face missing — bake morphs first")
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
        meshes = _find_verify_meshes()
        if meshes is None:
            self.report({'ERROR'}, "No rig detected or primary_face missing — bake morphs first")
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
        meshes = _find_verify_meshes()
        if meshes is None:
            self.report({'ERROR'}, "No rig detected or primary_face missing — bake morphs first")
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


