"""
Physics cloning operator.

Apply a pre-extracted rigid body + joint physics template (JSON under
`presets/physics/`) to the active MMD model, mapping rigids by bone name.

Also supports extracting physics from another loaded mmd_root into a JSON
template for later reuse.
"""
import bpy
import json
import os
from bpy.props import StringProperty, EnumProperty, BoolProperty
from mathutils import Matrix, Vector

SHAPE_IDX = {'SPHERE': 0, 'BOX': 1, 'CAPSULE': 2}


# Standard PMX author convention: `左X` / `右X` bone name prefixes.
# Our converted models use `X.L` / `X.R`. Target PMXes authored with the
# canonical Japanese prefix won't line up unless we normalize first.
# Callers should try the normalized name first, fall back to the raw name.
JP_SIDE_PREFIX_MAP = {
    '左': '.L',
    '右': '.R',
}


def _normalize_pmx_bone_name(name):
    """Map `左肩` → `肩.L`, `右腕` → `腕.R`, etc. Returns (normalized, original).

    If the first char isn't a side prefix, returns (name, name) — caller can
    still try it verbatim.
    """
    if not name:
        return name, name
    prefix = name[:1]
    suffix = JP_SIDE_PREFIX_MAP.get(prefix)
    if suffix is None:
        return name, name
    return name[1:] + suffix, name


# Canonical MMD body bones — Tier 3 skips these subtrees (they're handled
# by the Inase-style template, or by target-clone). Anything outside this
# set that forms a bone chain anchored on a body bone is a candidate for
# auto-generated physics (hair, skirt, tails, accessories).
#
# Fingers use BOTH half-width (0-3) and full-width (０-３) digits — different
# XPS converters produce different versions, so include both.
_FINGER_ROOTS = ('親指', '人指', '中指', '薬指', '小指')
_FINGER_HALF = tuple(f'{root}{i}{side}' for root in _FINGER_ROOTS
                     for i in '0123' for side in ('.L', '.R'))
_FINGER_FULL = tuple(f'{root}{i}{side}' for root in _FINGER_ROOTS
                     for i in '０１２３' for side in ('.L', '.R'))

CANONICAL_BODY_BONES = frozenset([
    '全ての親', '操作中心', 'センター', 'グルーブ', '腰',
    '上半身', '上半身1', '上半身2', '上半身3',
    '下半身',
    '首', '首1', '頭', '両目', '目.L', '目.R',
    '肩.L', '肩.R', '肩C.L', '肩C.R', '肩P.L', '肩P.R',
    '腕.L', '腕.R', 'ひじ.L', 'ひじ.R', '手首.L', '手首.R',
    'ダミー.L', 'ダミー.R',
    '腕捩.L', '腕捩.R', '手捩.L', '手捩.R',
    '腕捩1.L', '腕捩1.R', '腕捩2.L', '腕捩2.R', '腕捩3.L', '腕捩3.R',
    '手捩1.L', '手捩1.R', '手捩2.L', '手捩2.R', '手捩3.L', '手捩3.R',
    '足.L', '足.R', 'ひざ.L', 'ひざ.R', '足首.L', '足首.R',
    '足D.L', '足D.R', 'ひざD.L', 'ひざD.R', '足首D.L', '足首D.R',
    '足先EX.L', '足先EX.R',
    '足IK.L', '足IK.R', 'つま先IK.L', 'つま先IK.R',
    '足ＩＫ.L', '足ＩＫ.R', 'つま先ＩＫ.L', 'つま先ＩＫ.R',
    '足IK親.L', '足IK親.R', '足ＩＫ親.L', '足ＩＫ親.R',
    'つま先.L', 'つま先.R',
    '乳奶.L', '乳奶.R',
    '腰キャンセル.L', '腰キャンセル.R',
    *_FINGER_HALF, *_FINGER_FULL,
])


def _is_internal_helper_bone(name):
    """mmd_tools creates `_dummy_*` and `_shadow_*` helper bones for
    additional_transform constraint plumbing. They shouldn't get physics."""
    return name.startswith('_dummy_') or name.startswith('_shadow_')


def _presets_physics_dir():
    return os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))),
                        'presets', 'physics')


def _list_physics_templates(self, context):
    d = _presets_physics_dir()
    items = []
    if os.path.isdir(d):
        for name in sorted(os.listdir(d)):
            if name.endswith('.json'):
                stem = os.path.splitext(name)[0]
                items.append((stem, stem, ""))
    if not items:
        items = [('__empty__', '(no templates found)', '')]
    return items


def _find_mmd_root(obj):
    """Walk up to find the mmd_root (mmd_type == 'ROOT')."""
    cur = obj
    while cur is not None:
        if getattr(cur, 'mmd_type', '') == 'ROOT':
            return cur
        cur = cur.parent
    # try children
    if obj is not None:
        for c in obj.children_recursive if hasattr(obj, 'children_recursive') else []:
            if getattr(c, 'mmd_type', '') == 'ROOT':
                return c
    return None


def _bone_world_rest(arm, name):
    return arm.matrix_world @ arm.data.bones[name].matrix_local


def _get_model(root_obj):
    from mmd_tools.core.model import Model as MMDModel
    return MMDModel(root_obj)


def _stash_and_clear_pose(arm):
    """Capture current pose bone transforms and reset to rest. Returns stash for restore."""
    stash = []
    for pb in arm.pose.bones:
        stash.append((pb.name,
                      pb.location.copy(),
                      pb.rotation_quaternion.copy(),
                      pb.rotation_euler.copy(),
                      pb.scale.copy()))
        pb.location = (0, 0, 0)
        pb.rotation_quaternion = (1, 0, 0, 0)
        pb.rotation_euler = (0, 0, 0)
        pb.scale = (1, 1, 1)
    return stash


def _restore_pose(arm, stash):
    for name, loc, rq, re, sc in stash:
        pb = arm.pose.bones.get(name)
        if pb is None:
            continue
        pb.location = loc
        pb.rotation_quaternion = rq
        pb.rotation_euler = re
        pb.scale = sc


def extract_physics(src_root):
    """Extract physics from a src mmd_root object. Returns JSON-able dict.

    Forces the source armature into rest pose during extraction so rigid
    body positions are captured relative to the bind pose. Original pose
    is restored on exit.
    """
    src_model = _get_model(src_root)
    src_arm = src_model.armature()

    pose_stash = _stash_and_clear_pose(src_arm)
    bpy.context.view_layer.update()
    try:
        return _extract_locked(src_model, src_arm, src_root)
    finally:
        _restore_pose(src_arm, pose_stash)
        bpy.context.view_layer.update()


def _extract_locked(src_model, src_arm, src_root):
    rigids = []
    rigid_name_to_idx = {}
    for i, sr in enumerate(src_model.rigidBodies()):
        bname = sr.mmd_rigid.bone
        if not bname or bname not in src_arm.data.bones:
            rigids.append(None)
            continue
        sb_mat = _bone_world_rest(src_arm, bname)
        rigid_local_mat = sb_mat.inverted() @ sr.matrix_world
        sbl = src_arm.data.bones[bname].length
        rigids.append({
            'idx': i,
            'name_j': sr.mmd_rigid.name_j or sr.name,
            'name_e': sr.mmd_rigid.name_e,
            'bone': bname,
            'shape': sr.mmd_rigid.shape,
            'type': sr.mmd_rigid.type,
            'size': list(sr.mmd_rigid.size),
            'size_per_bone_length': [s / sbl for s in sr.mmd_rigid.size] if sbl > 1e-6 else list(sr.mmd_rigid.size),
            'local_matrix': [list(row) for row in rigid_local_mat],
            'collision_group_number': sr.mmd_rigid.collision_group_number,
            'collision_group_mask': list(sr.mmd_rigid.collision_group_mask),
            'friction': sr.rigid_body.friction,
            'mass': sr.rigid_body.mass,
            'angular_damping': sr.rigid_body.angular_damping,
            'linear_damping': sr.rigid_body.linear_damping,
            'bounce': sr.rigid_body.restitution,
        })
        rigid_name_to_idx[sr.name] = i

    joints = []
    for sj in src_model.joints():
        rbc = sj.rigid_body_constraint
        a = rbc.object1
        b = rbc.object2
        if a is None or b is None:
            continue
        ai = rigid_name_to_idx.get(a.name)
        bi = rigid_name_to_idx.get(b.name)
        if ai is None or bi is None:
            continue
        if rigids[ai] is None or rigids[bi] is None:
            continue
        joint_local_mat = a.matrix_world.inverted() @ sj.matrix_world
        mj = sj.mmd_joint
        joints.append({
            'name_j': mj.name_j or sj.name.replace('J.', ''),
            'name_e': mj.name_e,
            'rigid_a_idx': ai,
            'rigid_b_idx': bi,
            'local_matrix_in_a': [list(row) for row in joint_local_mat],
            'maximum_location': [rbc.limit_lin_x_upper, rbc.limit_lin_y_upper, rbc.limit_lin_z_upper],
            'minimum_location': [rbc.limit_lin_x_lower, rbc.limit_lin_y_lower, rbc.limit_lin_z_lower],
            'maximum_rotation': [rbc.limit_ang_x_upper, rbc.limit_ang_y_upper, rbc.limit_ang_z_upper],
            'minimum_rotation': [rbc.limit_ang_x_lower, rbc.limit_ang_y_lower, rbc.limit_ang_z_lower],
            'spring_angular': list(sj.mmd_joint.spring_angular),
            'spring_linear': list(sj.mmd_joint.spring_linear),
        })

    head = src_arm.data.bones.get('頭')
    ankle = src_arm.data.bones.get('足首.L')
    body_h = None
    if head and ankle:
        body_h = float((_bone_world_rest(src_arm, '頭').to_translation()
                        - _bone_world_rest(src_arm, '足首.L').to_translation()).z)

    return {
        'version': 1,
        'source': src_root.name,
        'body_height_m': body_h,
        'rigids': rigids,
        'joints': joints,
    }


def _body_height(arm):
    head = arm.data.bones.get('頭')
    ankle = arm.data.bones.get('足首.L')
    if head is None or ankle is None:
        return None
    return float((_bone_world_rest(arm, '頭').to_translation()
                  - _bone_world_rest(arm, '足首.L').to_translation()).z)


def _find_body_mesh(mmd_root):
    """Pick the mesh that best represents the body surface for physics fitting.

    Raw-vert-count ranking breaks on DAZ models whose strand meshes (hair,
    pubes) have tens of thousands of verts covering a tiny region. Score by
    how many canonical body bones each mesh carries non-trivial weights on,
    then break ties by total weighted vert count. A mesh rigged to 上半身 +
    下半身 + 腕 + 足 + 頭 is obviously the body, regardless of absolute size.
    """
    body_bones = ('上半身', '上半身2', '下半身', '腕.L', '腕.R',
                  'ひじ.L', 'ひじ.R', '足.L', '足.R', 'ひざ.L', 'ひざ.R',
                  '頭', '首')
    best = None
    best_score = (-1, -1)  # (bones_covered, weighted_verts)
    for c in mmd_root.children_recursive:
        if c.type != 'MESH' or getattr(c, 'mmd_type', '') == 'RIGID_BODY':
            continue
        bones_covered = 0
        weighted = 0
        for bname in body_bones:
            for an in _BONE_WEIGHT_ALIASES.get(bname, (bname,)):
                vg = c.vertex_groups.get(an)
                if vg is None:
                    continue
                nv = 0
                for v in c.data.vertices:
                    for g in v.groups:
                        if g.group == vg.index and g.weight > 0.3:
                            nv += 1
                            break
                if nv > 20:
                    bones_covered += 1
                    weighted += nv
                    break
        score = (bones_covered, weighted)
        if score > best_score:
            best_score = score
            best = c
    return best


_STRAND_BODY_BONES = ('上半身', '上半身2', '下半身', '腕.L', '腕.R',
                       '足.L', '足.R', '頭', '首')


def _mesh_bone_coverage(mesh, bone_aliases_dict=_BONE_WEIGHT_ALIASES):
    """Count how many canonical body bones the mesh carries weights on
    (≥20 verts at weight>0.3). Strand meshes (pubes, single hair patch)
    score 0-1; real body/outfit meshes score 5+. Used to reject strand
    meshes from being used as thickness reference for bones they happen
    to all weight to."""
    covered = 0
    for bname in _STRAND_BODY_BONES:
        for an in bone_aliases_dict.get(bname, (bname,)):
            vg = mesh.vertex_groups.get(an)
            if vg is None:
                continue
            n = 0
            for v in mesh.data.vertices:
                for g in v.groups:
                    if g.group == vg.index and g.weight > 0.3:
                        n += 1
                        if n >= 20:
                            break
                if n >= 20:
                    break
            if n >= 20:
                covered += 1
                break
    return covered


def _find_best_mesh_for_bone(mmd_root, bone_name):
    """Pick the mesh with the most verts weighted (>0.3) to bone_name or its
    twist/D-bone aliases. Rejects strand-like meshes (coverage<2 body bones)
    so a pubic/hair patch entirely weighted to 下半身 doesn't become the
    thickness reference for the hip rigid. Falls back to _find_body_mesh
    if no eligible mesh weights this bone."""
    alias_names = _BONE_WEIGHT_ALIASES.get(bone_name, [bone_name])
    best = None
    best_n = 0
    for c in mmd_root.children_recursive:
        if c.type != 'MESH' or getattr(c, 'mmd_type', '') == 'RIGID_BODY':
            continue
        n = 0
        for an in alias_names:
            vg = c.vertex_groups.get(an)
            if vg is None:
                continue
            for v in c.data.vertices:
                for g in v.groups:
                    if g.group == vg.index and g.weight > 0.3:
                        n += 1
                        break
        if n <= best_n:
            continue
        # Reject strand-like meshes: a mesh entirely weighted to 1 bone is
        # typically hair/pubes and measures a narrow region, not the body.
        if _mesh_bone_coverage(c) < 2:
            continue
        best_n = n
        best = c
    return best if best_n >= 20 else _find_body_mesh(mmd_root)


# Some bones have their skin weights redirected to alias bones after the
# convert pipeline (D-bones for legs, twist bones for arms).  When fitting
# a rigid's radius we need to include those aliases so the vertex samples
# actually represent the body part.
_BONE_WEIGHT_ALIASES = {
    '足.L':   ['足.L', '足D.L'],
    '足.R':   ['足.R', '足D.R'],
    'ひざ.L': ['ひざ.L', 'ひざD.L'],
    'ひざ.R': ['ひざ.R', 'ひざD.R'],
    '足首.L': ['足首.L', '足首D.L'],
    '足首.R': ['足首.R', '足首D.R'],
    '腕.L':   ['腕.L', '腕捩.L', '腕捩1.L', '腕捩2.L', '腕捩3.L'],
    '腕.R':   ['腕.R', '腕捩.R', '腕捩1.R', '腕捩2.R', '腕捩3.R'],
    'ひじ.L': ['ひじ.L', '手捩.L', '手捩1.L', '手捩2.L', '手捩3.L'],
    'ひじ.R': ['ひじ.R', '手捩.R', '手捩1.R', '手捩2.R', '手捩3.R'],
}


def _fit_rigid_to_bone_verts(rigid_obj, arm, mesh, bone_name, shape, *, pad=1.0,
                              percentile=0.90, weight_threshold=0.3):
    """Shrink rigid radius to match mesh thickness if the template's radius
    exceeds the actual weighted-vert extent.

    Rule: ``new_r = min(template_r, measured_r * pad)``. Never grows the rigid
    — the template is assumed to be hand-authored by the source model's creator
    and should be respected when the mesh is wider than the capsule.

    Sampling uses verts whose total weight on this bone (or its
    ``_BONE_WEIGHT_ALIASES``) exceeds ``weight_threshold``. Perpendicular
    distances to the bone's Y axis are collected, sorted, and the given
    ``percentile`` is taken to guard against a few outlier clothing/hair verts.
    """
    if mesh is None or bone_name not in arm.data.bones:
        return None

    alias_names = _BONE_WEIGHT_ALIASES.get(bone_name, [bone_name])
    alias_vg_indices = []
    for n in alias_names:
        vg = mesh.vertex_groups.get(n)
        if vg is not None:
            alias_vg_indices.append(vg.index)
    if not alias_vg_indices:
        return None
    alias_set = set(alias_vg_indices)

    bone = arm.data.bones[bone_name]
    bone_world_mat = arm.matrix_world @ bone.matrix_local
    bone_world_inv = bone_world_mat.inverted()
    mesh_world = mesh.matrix_world

    candidates = []
    for v in mesh.data.vertices:
        w = 0.0
        for g in v.groups:
            if g.group in alias_set:
                w += g.weight
                if w >= weight_threshold:
                    break
        if w < weight_threshold:
            continue
        local = bone_world_inv @ (mesh_world @ v.co)
        candidates.append(local.x * local.x + local.z * local.z)

    if len(candidates) < 10:
        return None
    candidates.sort()
    idx = int(len(candidates) * percentile)
    if idx >= len(candidates):
        idx = len(candidates) - 1
    measured_r = (candidates[idx] ** 0.5) * pad

    old_size = list(rigid_obj.mmd_rigid.size)
    template_r = old_size[0]
    # Shrink-only: never grow the rigid beyond the hand-authored template value.
    new_r = min(template_r, measured_r)

    if shape == 'SPHERE':
        rigid_obj.mmd_rigid.size = (new_r, 0.0, 0.0)
    elif shape == 'CAPSULE':
        rigid_obj.mmd_rigid.size = (new_r, old_size[1], 0.0)
    else:
        return None
    return (old_size, list(rigid_obj.mmd_rigid.size), len(candidates))


def apply_physics(dst_root, data, *, rescale_by_bone_length=True, fit_to_mesh=True, fit_pad=1.10):
    """Apply extracted data to dst mmd_root. Returns (n_rigids, n_joints, skipped_bones).

    Size scaling policy (rescale_by_bone_length=True):
      * global_scale = dst_body_height / src_body_height — used for thickness
      * CAPSULE: radius = src_radius * global_scale,
                 length = dst_bone_length (bone-fitting, so capsule hugs bone)
      * SPHERE/BOX: all dims * global_scale
    This keeps body cage & hair proportions right on models whose bones are
    re-segmented (e.g. 上半身 being 2× longer without the character being 2× thicker).
    """
    dst_model = _get_model(dst_root)
    dst_arm = dst_model.armature()
    dst_bone_names = set(dst_arm.data.bones.keys())

    src_body_height = data.get('body_height_m') or 1.0
    dst_body_height = _body_height(dst_arm) or src_body_height
    global_scale = dst_body_height / src_body_height if src_body_height > 1e-6 else 1.0

    rigid_idx_to_obj = {}
    skipped = []
    for entry in data['rigids']:
        if entry is None:
            continue
        bname = entry['bone']
        if bname not in dst_bone_names:
            skipped.append(bname)
            continue
        db_mat = _bone_world_rest(dst_arm, bname)
        rigid_local_mat = Matrix(entry['local_matrix'])
        new_mat = db_mat @ rigid_local_mat
        dbl = dst_arm.data.bones[bname].length
        src_size = entry['size']

        if rescale_by_bone_length:
            shape = entry['shape']
            if shape == 'CAPSULE':
                new_size = (src_size[0] * global_scale, dbl, 0.0)
            else:  # SPHERE / BOX
                new_size = tuple(s * global_scale for s in src_size)
        else:
            new_size = tuple(src_size)
        nr = dst_model.createRigidBody(
            shape_type=SHAPE_IDX[entry['shape']],
            location=new_mat.to_translation(),
            rotation=new_mat.to_euler(),
            size=new_size,
            dynamics_type=int(entry['type']),
            name=entry['name_j'],
            name_e=entry.get('name_e'),
            bone=bname,
            friction=entry.get('friction'),
            mass=entry.get('mass'),
            angular_damping=entry.get('angular_damping'),
            linear_damping=entry.get('linear_damping'),
            bounce=entry.get('bounce'),
            collision_group_number=entry.get('collision_group_number'),
            collision_group_mask=entry.get('collision_group_mask'),
        )
        rigid_idx_to_obj[entry['idx']] = nr

    n_joints = 0
    for j in data['joints']:
        ai = j['rigid_a_idx']
        bi = j['rigid_b_idx']
        if ai not in rigid_idx_to_obj or bi not in rigid_idx_to_obj:
            continue
        na = rigid_idx_to_obj[ai]
        nb = rigid_idx_to_obj[bi]
        joint_local_mat = Matrix(j['local_matrix_in_a'])
        new_jmat = na.matrix_world @ joint_local_mat
        dst_model.createJoint(
            name=j['name_j'],
            name_e=j.get('name_e'),
            location=new_jmat.to_translation(),
            rotation=new_jmat.to_euler(),
            rigid_a=na,
            rigid_b=nb,
            maximum_location=tuple(j['maximum_location']),
            minimum_location=tuple(j['minimum_location']),
            maximum_rotation=tuple(j['maximum_rotation']),
            minimum_rotation=tuple(j['minimum_rotation']),
            spring_angular=tuple(j['spring_angular']),
            spring_linear=tuple(j['spring_linear']),
        )
        n_joints += 1

    # Post-process: fit radii to actual mesh thickness using vertex group weights.
    # Pick a mesh per-bone — DAZ outfit layers may carry skin weights on
    # different bones (Suit.Body for torso, Suit.Legs for legs, etc.), and
    # strand meshes (pubes, hair) would dominate a single-mesh pick.
    fit_stats = []
    fallback_mesh = _find_body_mesh(dst_root) if fit_to_mesh else None
    if fit_to_mesh and fallback_mesh is not None:
        print(f"[CTMMD physics] fit_to_mesh fallback mesh: {fallback_mesh.name}")
        for entry in data['rigids']:
            if entry is None:
                continue
            if entry['idx'] not in rigid_idx_to_obj:
                continue
            nr = rigid_idx_to_obj[entry['idx']]
            per_bone_mesh = _find_best_mesh_for_bone(dst_root, entry['bone']) or fallback_mesh
            res = _fit_rigid_to_bone_verts(nr, dst_arm, per_bone_mesh, entry['bone'],
                                           entry['shape'], pad=fit_pad)
            if res is not None:
                old, new, n = res
                # Only log if there was a meaningful change (>=2mm)
                if abs(old[0] - new[0]) > 0.002:
                    fit_stats.append((entry['bone'], round(old[0], 4), round(new[0], 4), n, per_bone_mesh.name))
        if fit_stats:
            print(f"[CTMMD physics] fit_to_mesh adjustments ({len(fit_stats)}):")
            for b, o, nw, n, mn in fit_stats:
                arrow = '↓' if nw < o else '↑'
                print(f"  {b:12} {o:.4f} {arrow} {nw:.4f}  ({n} verts from {mn})")

    return len(rigid_idx_to_obj), n_joints, skipped


def apply_breast_physics(dst_root, data, *, rescale_by_bone_length=True,
                         fit_to_mesh=True, fit_pad=1.10):
    """Apply ONLY 乳奶.L / 乳奶.R rigids + their joints from a physics template.

    Joints need a torso-side anchor rigid (typically 上半身2 in the standard
    MMD template). If the target model already has a rigid on that anchor
    bone (from a prior setup_physics run), reuse it. Otherwise the joint is
    skipped and the missing anchor bone is returned for caller to report.

    Returns (n_rigids_created, n_joints_created, skipped_breast_bones,
             missing_anchor_bones).
    """
    dst_model = _get_model(dst_root)
    dst_arm = dst_model.armature()
    dst_bone_names = set(dst_arm.data.bones.keys())

    existing_by_bone = {}
    for r in dst_model.rigidBodies():
        bname = r.mmd_rigid.bone
        if bname:
            existing_by_bone[bname] = r

    src_body_height = data.get('body_height_m') or 1.0
    dst_body_height = _body_height(dst_arm) or src_body_height
    global_scale = dst_body_height / src_body_height if src_body_height > 1e-6 else 1.0

    def _is_breast(bname):
        return bname.startswith('乳奶')

    rigid_idx_to_obj = {}
    skipped = []
    for entry in data['rigids']:
        if entry is None or not _is_breast(entry['bone']):
            continue
        bname = entry['bone']
        if bname not in dst_bone_names:
            skipped.append(bname)
            continue
        # Avoid duplicate if target already has a rigid on this bone
        if bname in existing_by_bone:
            rigid_idx_to_obj[entry['idx']] = existing_by_bone[bname]
            continue
        db_mat = _bone_world_rest(dst_arm, bname)
        new_mat = db_mat @ Matrix(entry['local_matrix'])
        dbl = dst_arm.data.bones[bname].length
        src_size = entry['size']
        if rescale_by_bone_length:
            if entry['shape'] == 'CAPSULE':
                new_size = (src_size[0] * global_scale, dbl, 0.0)
            else:
                new_size = tuple(s * global_scale for s in src_size)
        else:
            new_size = tuple(src_size)
        nr = dst_model.createRigidBody(
            shape_type=SHAPE_IDX[entry['shape']],
            location=new_mat.to_translation(),
            rotation=new_mat.to_euler(),
            size=new_size,
            dynamics_type=int(entry['type']),
            name=entry['name_j'],
            name_e=entry.get('name_e'),
            bone=bname,
            friction=entry.get('friction'),
            mass=entry.get('mass'),
            angular_damping=entry.get('angular_damping'),
            linear_damping=entry.get('linear_damping'),
            bounce=entry.get('bounce'),
            collision_group_number=entry.get('collision_group_number'),
            collision_group_mask=entry.get('collision_group_mask'),
        )
        rigid_idx_to_obj[entry['idx']] = nr

    # Build idx -> bone lookup for anchor resolution
    idx_to_bone = {r['idx']: r['bone'] for r in data['rigids'] if r is not None}

    n_joints = 0
    missing_anchors = []
    for j in data['joints']:
        ai, bi = j['rigid_a_idx'], j['rigid_b_idx']
        # Only process joints that involve a breast rigid
        a_bone = idx_to_bone.get(ai, '')
        b_bone = idx_to_bone.get(bi, '')
        if not (_is_breast(a_bone) or _is_breast(b_bone)):
            continue

        def _resolve(idx, bone):
            if idx in rigid_idx_to_obj:
                return rigid_idx_to_obj[idx]
            return existing_by_bone.get(bone)

        na = _resolve(ai, a_bone)
        nb = _resolve(bi, b_bone)
        if na is None or nb is None:
            miss = a_bone if na is None else b_bone
            if miss and miss not in missing_anchors:
                missing_anchors.append(miss)
            continue
        joint_local_mat = Matrix(j['local_matrix_in_a'])
        new_jmat = na.matrix_world @ joint_local_mat
        dst_model.createJoint(
            name=j['name_j'],
            name_e=j.get('name_e'),
            location=new_jmat.to_translation(),
            rotation=new_jmat.to_euler(),
            rigid_a=na,
            rigid_b=nb,
            maximum_location=tuple(j['maximum_location']),
            minimum_location=tuple(j['minimum_location']),
            maximum_rotation=tuple(j['maximum_rotation']),
            minimum_rotation=tuple(j['minimum_rotation']),
            spring_angular=tuple(j['spring_angular']),
            spring_linear=tuple(j['spring_linear']),
        )
        n_joints += 1

    # fit_to_mesh for newly created breast rigids
    if fit_to_mesh:
        fallback_mesh = _find_body_mesh(dst_root)
        for entry in data['rigids']:
            if entry is None or not _is_breast(entry['bone']):
                continue
            if entry['idx'] not in rigid_idx_to_obj:
                continue
            nr = rigid_idx_to_obj[entry['idx']]
            # skip if it's a reused existing rigid (don't mutate user's rigid)
            if existing_by_bone.get(entry['bone']) is nr:
                continue
            per_bone_mesh = _find_best_mesh_for_bone(dst_root, entry['bone']) or fallback_mesh
            if per_bone_mesh is None:
                continue
            _fit_rigid_to_bone_verts(nr, dst_arm, per_bone_mesh, entry['bone'],
                                     entry['shape'], pad=fit_pad)

    return len(rigid_idx_to_obj), n_joints, skipped, missing_anchors


class OBJECT_OT_apply_breast_physics(bpy.types.Operator):
    """仅应用胸部物理 (乳奶.L/R) 从物理模板。需要目标模型已有胸部骨(乳奶.L/R)
    和 joint 锚点骨(如 上半身2) 的对应 rigid (或先跑一次 setup_physics)。"""
    bl_idname = "object.apply_breast_physics"
    bl_label = "应用胸部物理 (乳奶.L/R)"
    bl_description = "从物理模板抽取胸部 2 个 rigid + 对应 joint, 应用到当前 MMD 模型"
    bl_options = {'REGISTER', 'UNDO'}

    template: EnumProperty(
        name="模板",
        description="从哪个物理模板抽取胸部数据",
        items=_list_physics_templates,
    )
    build_rig: BoolProperty(
        name="应用后 build_rig",
        default=True,
    )
    fit_to_mesh: BoolProperty(
        name="贴合 mesh 实际粗细",
        default=True,
    )

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=320)

    def execute(self, context):
        if self.template == '__empty__':
            self.report({'ERROR'}, "presets/physics/ 下没有模板 JSON")
            return {'CANCELLED'}
        active = context.active_object
        if active is None:
            self.report({'ERROR'}, "没有 active object")
            return {'CANCELLED'}
        root = _find_mmd_root(active)
        if root is None:
            self.report({'ERROR'}, "active 不在任何 mmd_root 下 (先跑 use_mmd_tools_convert)")
            return {'CANCELLED'}

        template_path = os.path.join(_presets_physics_dir(), self.template + '.json')
        try:
            with open(template_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            self.report({'ERROR'}, f"读取模板失败: {e}")
            return {'CANCELLED'}

        # Pre-check: does target have 乳奶.L / 乳奶.R bones?
        model = _get_model(root)
        arm = model.armature()
        missing_bones = [b for b in ('乳奶.L', '乳奶.R') if b not in arm.data.bones]
        if missing_bones:
            self.report({'ERROR'}, f"目标模型缺少骨: {', '.join(missing_bones)}")
            return {'CANCELLED'}

        try:
            n_r, n_j, skipped, missing_anchors = apply_breast_physics(
                root, data, fit_to_mesh=self.fit_to_mesh)
        except Exception as e:
            self.report({'ERROR'}, f"应用胸部物理失败: {e}")
            return {'CANCELLED'}

        msg_parts = [f"胸部 rigid: {n_r}, joint: {n_j}"]
        if skipped:
            msg_parts.append(f"skipped bones: {skipped}")
        if missing_anchors:
            msg_parts.append(f"缺 joint 锚点: {missing_anchors} (建议先跑一次 setup_physics)")
        msg = '; '.join(msg_parts)
        print(f"[CTMMD physics] {msg}")
        self.report({'INFO'}, msg)

        if self.build_rig:
            for o in bpy.data.objects: o.select_set(False)
            root.select_set(True)
            context.view_layer.objects.active = root
            try:
                bpy.ops.mmd_tools.build_rig()
            except Exception as e:
                self.report({'WARNING'}, f"build_rig 失败: {e}")
        return {'FINISHED'}


# ---------- Tier 1: clone rigids + joints from a target PMX file ----------

def _pmx_rigid_to_entry(rigid, model, scale):
    """Convert a mmd_tools `pmx.Rigid` to the JSON entry shape that
    `apply_physics()` already consumes. Coordinate/size conversion mirrors
    `mmd_tools.core.pmx.importer.PMXImporter.__importRigids` so the output
    lands in Blender space exactly as mmd_tools would import it.
    """
    bone_idx = rigid.bone
    if bone_idx is None or bone_idx < 0 or bone_idx >= len(model.bones):
        return None
    raw_bone = model.bones[bone_idx].name
    norm_bone, _ = _normalize_pmx_bone_name(raw_bone)

    # importer path: loc .xzy * scale, rot .xzy * -1, size .xzy (BOX only) * scale
    loc = Vector(rigid.location).xzy * scale
    rot = Vector(rigid.rotation).xzy * -1
    if rigid.type == SHAPE_IDX['BOX']:
        size = (Vector(rigid.size).xzy) * scale
    else:
        size = Vector(rigid.size) * scale

    shape_name = ('SPHERE', 'BOX', 'CAPSULE')[rigid.type]

    # Assemble a matrix we can later compose as db_bone_mat @ local_matrix.
    # But apply_physics expects local_matrix in dst-arm-bone space, and here
    # we're working from raw PMX world coords. Simplest: build a world matrix
    # and have clone_physics_from_pmx call apply_physics_world instead (new
    # helper below that skips local_matrix re-composition).
    from mathutils import Euler
    rigid_world_mat = Matrix.Translation(loc) @ Euler(rot, 'YXZ').to_matrix().to_4x4()

    sbl = 1.0  # bone length: unused by clone path (we keep target size verbatim)
    return {
        'name_j': rigid.name,
        'name_e': getattr(rigid, 'name_e', None) or '',
        'bone': norm_bone,
        'bone_raw': raw_bone,
        'shape': shape_name,
        'type': rigid.mode,  # 0/1/2 STATIC/DYNAMIC/DYNAMIC_BONE
        'size': list(size),
        'world_matrix': [list(row) for row in rigid_world_mat],
        'collision_group_number': rigid.collision_group_number,
        'collision_group_mask': [rigid.collision_group_mask & (1 << i) == 0 for i in range(16)],
        'friction': rigid.friction,
        'mass': rigid.mass,
        'angular_damping': rigid.rotation_attenuation,
        'linear_damping': rigid.velocity_attenuation,
        'bounce': rigid.bounce,
    }


def _pmx_joint_to_entry(joint, pmx_idx_to_entry_idx, scale):
    """Convert `pmx.Joint` → JSON joint entry. Mirrors `__importJoints`
    coordinate swaps. `pmx_idx_to_entry_idx` maps original PMX rigid index
    to the index into our entries list (skipping None entries).
    """
    ai = pmx_idx_to_entry_idx.get(joint.src_rigid)
    bi = pmx_idx_to_entry_idx.get(joint.dest_rigid)
    if ai is None or bi is None:
        return None
    loc = Vector(joint.location).xzy * scale
    rot = Vector(joint.rotation).xzy * -1
    max_loc = Vector(joint.maximum_location).xzy * scale
    min_loc = Vector(joint.minimum_location).xzy * scale
    # importer swaps min/max rotation (see __importJoints):
    #   maximum_rotation = Vector(joint.minimum_rotation).xzy * -1
    #   minimum_rotation = Vector(joint.maximum_rotation).xzy * -1
    max_rot = Vector(joint.minimum_rotation).xzy * -1
    min_rot = Vector(joint.maximum_rotation).xzy * -1
    from mathutils import Euler
    joint_world_mat = Matrix.Translation(loc) @ Euler(rot, 'YXZ').to_matrix().to_4x4()
    return {
        'name_j': joint.name,
        'name_e': getattr(joint, 'name_e', None) or '',
        'rigid_a_idx': ai,
        'rigid_b_idx': bi,
        'world_matrix': [list(row) for row in joint_world_mat],
        'maximum_location': list(max_loc),
        'minimum_location': list(min_loc),
        'maximum_rotation': list(max_rot),
        'minimum_rotation': list(min_rot),
        'spring_linear': list(Vector(joint.spring_constant).xzy),
        'spring_angular': list(Vector(joint.spring_rotation_constant).xzy),
    }


def _apply_cloned_physics(dst_root, data, *, fit_to_mesh=True, fit_pad=1.10):
    """Apply cloned PMX data (world-space matrices, no src bone rest pose
    reference). Similar to apply_physics() but skips global_scale and uses
    world_matrix directly since target PMX and converted model share the
    same coordinate space (assuming both at scale 0.08).
    """
    from mmd_tools.core.rigid_body import shapeType

    dst_model = _get_model(dst_root)
    dst_arm = dst_model.armature()
    dst_bone_names = set(dst_arm.data.bones.keys())

    rigid_entry_idx_to_obj = {}
    skipped = []
    for ei, entry in enumerate(data['rigids']):
        if entry is None:
            continue
        bone = entry['bone']
        if bone not in dst_bone_names:
            # try raw (original) name as fallback
            raw = entry.get('bone_raw')
            if raw and raw in dst_bone_names:
                bone = raw
            else:
                skipped.append(entry['bone'])
                continue
        world_mat = Matrix(entry['world_matrix'])
        nr = dst_model.createRigidBody(
            shape_type=SHAPE_IDX[entry['shape']],
            location=world_mat.to_translation(),
            rotation=world_mat.to_euler('YXZ'),
            size=entry['size'],
            dynamics_type=int(entry['type']),
            name=entry['name_j'],
            name_e=entry.get('name_e'),
            bone=bone,
            friction=entry.get('friction'),
            mass=entry.get('mass'),
            angular_damping=entry.get('angular_damping'),
            linear_damping=entry.get('linear_damping'),
            bounce=entry.get('bounce'),
            collision_group_number=entry.get('collision_group_number'),
            collision_group_mask=entry.get('collision_group_mask'),
        )
        rigid_entry_idx_to_obj[ei] = nr

    n_joints = 0
    for j in data['joints']:
        if j is None:
            continue
        ai = j['rigid_a_idx']
        bi = j['rigid_b_idx']
        if ai not in rigid_entry_idx_to_obj or bi not in rigid_entry_idx_to_obj:
            continue
        na = rigid_entry_idx_to_obj[ai]
        nb = rigid_entry_idx_to_obj[bi]
        world_mat = Matrix(j['world_matrix'])
        dst_model.createJoint(
            name=j['name_j'],
            name_e=j.get('name_e'),
            location=world_mat.to_translation(),
            rotation=world_mat.to_euler('YXZ'),
            rigid_a=na,
            rigid_b=nb,
            maximum_location=tuple(j['maximum_location']),
            minimum_location=tuple(j['minimum_location']),
            maximum_rotation=tuple(j['maximum_rotation']),
            minimum_rotation=tuple(j['minimum_rotation']),
            spring_angular=tuple(j['spring_angular']),
            spring_linear=tuple(j['spring_linear']),
        )
        n_joints += 1

    fit_stats = []
    if fit_to_mesh:
        fallback_mesh = _find_body_mesh(dst_root)
        if fallback_mesh is not None:
            print(f"[CTMMD clone] fit_to_mesh fallback mesh: {fallback_mesh.name}")
            for ei, entry in enumerate(data['rigids']):
                if entry is None or ei not in rigid_entry_idx_to_obj:
                    continue
                nr = rigid_entry_idx_to_obj[ei]
                bone = nr.mmd_rigid.bone
                per_bone_mesh = _find_best_mesh_for_bone(dst_root, bone) or fallback_mesh
                res = _fit_rigid_to_bone_verts(nr, dst_arm, per_bone_mesh, bone,
                                               entry['shape'], pad=fit_pad)
                if res is not None:
                    old, new, n = res
                    if abs(old[0] - new[0]) > 0.002:
                        fit_stats.append((bone, round(old[0], 4), round(new[0], 4), n, per_bone_mesh.name))
            if fit_stats:
                print(f"[CTMMD clone] fit_to_mesh adjustments ({len(fit_stats)}):")
                for b, o, nw, n, mn in fit_stats:
                    arrow = '↓' if nw < o else '↑'
                    print(f"  {b:12} {o:.4f} {arrow} {nw:.4f}  ({n} verts from {mn})")

    return len(rigid_entry_idx_to_obj), n_joints, skipped


def _create_missing_target_bones(dst_arm, model, scale=0.08):
    """For every rigid in `model.rigids` whose bone isn't on `dst_arm`,
    create it as an Edit bone with target's head/tail/parent chain.

    Purpose: target-authored dangling accessory bones (pendants, chains,
    straps) never exist in XPS source — PMX authors add them by hand in
    PMXEditor to anchor rigid bodies on accessory meshes. Without this,
    Tier 1 clone silently drops those rigids.

    Process:
      1) scan rigids → needed target bone indices (normalized vs raw)
      2) walk parent chain from each needed bone, accumulate all missing
         bones (including parents-of-parents)
      3) topological order (parents before children)
      4) flip to EDIT mode on dst_arm, add bones with head/tail derived
         from target coords (.xzy * scale, mmd_tools' PMXImporter rule)
      5) parent either to a fellow new bone or to the existing converted
         armature bone (via name normalize)

    Bones added this way are anchors only — they carry no skin weights
    and won't affect mesh deform. They exist purely so the target rigid
    can attach via `mmd_rigid.bone`.

    Returns list of (raw_name, resolved_name) tuples for added bones.
    """
    from mathutils import Vector
    existing = set(dst_arm.data.bones.keys())

    def resolve(bone_idx):
        """Map a target bone index to the name it would have on dst_arm,
        handling the `左X ↔ X.L` normalization + raw-name fallback."""
        if bone_idx is None or bone_idx < 0 or bone_idx >= len(model.bones):
            return None
        raw = model.bones[bone_idx].name
        norm, _ = _normalize_pmx_bone_name(raw)
        if norm in existing:
            return norm
        if raw in existing:
            return raw
        return None  # missing

    needed = set()
    for r in model.rigids:
        bidx = r.bone
        if bidx is None or bidx < 0 or bidx >= len(model.bones):
            continue
        if resolve(bidx) is None:
            needed.add(bidx)
    if not needed:
        return []

    # Walk parent chain, accumulate every missing bone along the way.
    to_add = set()

    def walk(bidx):
        if bidx in to_add or bidx is None or bidx < 0:
            return
        b = model.bones[bidx]
        raw = b.name
        norm, _ = _normalize_pmx_bone_name(raw)
        if norm in existing or raw in existing:
            return  # already exists, stop walking
        to_add.add(bidx)
        walk(b.parent)

    for bidx in needed:
        walk(bidx)
    if not to_add:
        return []

    # Parent-first topological ordering — edit bones require parent to be
    # added first before setting `eb.parent`.
    ordered = []
    visited = set()

    def emit(bidx):
        if bidx in visited or bidx not in to_add:
            return
        visited.add(bidx)
        p = model.bones[bidx].parent
        if p in to_add:
            emit(p)
        ordered.append(bidx)

    for bidx in to_add:
        emit(bidx)

    # Edit-mode add. Save & restore active + mode so callers aren't
    # surprised.
    import bpy
    prev_active = bpy.context.view_layer.objects.active
    prev_mode = bpy.context.mode
    bpy.context.view_layer.objects.active = dst_arm
    bpy.ops.object.mode_set(mode='EDIT')
    try:
        ebones = dst_arm.data.edit_bones
        added = []
        for bidx in ordered:
            b = model.bones[bidx]
            name = b.name  # preserve target naming (e.g. Bone.L stays Bone.L)
            if name in ebones:
                continue
            # Head: target PMX coords → Blender via .xzy * scale
            head = Vector(b.location).xzy * scale
            # Tail: displayConnection is either offset tuple or tail bone idx
            dc = getattr(b, 'displayConnection', None)
            tail = None
            if isinstance(dc, (tuple, list)) and len(dc) == 3:
                tail = head + Vector(dc).xzy * scale
            elif isinstance(dc, int) and 0 <= dc < len(model.bones):
                tail = Vector(model.bones[dc].location).xzy * scale
            if tail is None or (tail - head).length < 1e-6:
                # Fall back to 1cm downward — Blender refuses zero-length
                tail = head + Vector((0.0, 0.0, -0.01))
            eb = ebones.new(name)
            eb.head = head
            eb.tail = tail
            # Resolve parent
            parent_idx = b.parent
            if parent_idx is not None and 0 <= parent_idx < len(model.bones):
                parent_raw = model.bones[parent_idx].name
                parent_norm, _ = _normalize_pmx_bone_name(parent_raw)
                if parent_norm in ebones:
                    eb.parent = ebones[parent_norm]
                elif parent_raw in ebones:
                    eb.parent = ebones[parent_raw]
            added.append((name, name))
    finally:
        bpy.ops.object.mode_set(mode='OBJECT')
        if prev_active is not None:
            bpy.context.view_layer.objects.active = prev_active

    print(f"[CTMMD clone] auto-added {len(added)} target-only bone(s): "
          f"{[n for n, _ in added[:8]]}" + (" …" if len(added) > 8 else ''))
    return added


def clone_physics_from_pmx(dst_root, pmx_path, *, fit_to_mesh=True, fit_pad=1.10,
                           scale=0.08, add_missing_bones=True):
    """Load a target PMX file and clone its rigid bodies + joints onto dst_root.

    - Bone names are normalized `左X` → `X.L`, `右X` → `X.R`; raw name used
      as fallback. Bones not found on dst_root are skipped and reported.
    - No global scale (target and converted model share scale=0.08 space).
    - Optional fit_to_mesh (shrink-only) reuses the Tier-2 helper.
    - `add_missing_bones` (default True): for rigids referencing bones
      that don't exist on dst_arm, auto-create the bone chain from
      target data. Anchors for dangling accessory rigids (pendants etc).

    Returns (n_rigids, n_joints, skipped_bones, total_target_rigids).
    """
    import mmd_tools.core.pmx as pmx_mod
    try:
        model = pmx_mod.load(pmx_path)
    except Exception as e:
        raise RuntimeError(f"读取 PMX 失败: {e}")

    if add_missing_bones:
        dst_model = _get_model(dst_root)
        dst_arm = dst_model.armature()
        _create_missing_target_bones(dst_arm, model, scale=scale)

    entries = []
    pmx_idx_to_entry_idx = {}
    for i, r in enumerate(model.rigids):
        entry = _pmx_rigid_to_entry(r, model, scale)
        if entry is None:
            continue
        pmx_idx_to_entry_idx[i] = len(entries)
        entries.append(entry)

    joint_entries = []
    for j in model.joints:
        je = _pmx_joint_to_entry(j, pmx_idx_to_entry_idx, scale)
        if je is not None:
            joint_entries.append(je)

    data = {'rigids': entries, 'joints': joint_entries}
    n_r, n_j, skipped = _apply_cloned_physics(dst_root, data,
                                              fit_to_mesh=fit_to_mesh,
                                              fit_pad=fit_pad)
    print(f"[CTMMD clone] target '{os.path.basename(pmx_path)}': "
          f"{n_r}/{len(model.rigids)} rigids, {n_j}/{len(model.joints)} joints, "
          f"{len(skipped)} bone(s) missing on target")
    return n_r, n_j, skipped, len(model.rigids)


class OBJECT_OT_clone_physics_from_pmx(bpy.types.Operator):
    """Clone rigid bodies and joints from a target .pmx file onto this model."""
    bl_idname = "object.clone_physics_from_pmx"
    bl_label = "🎯 从目标 PMX 克隆刚体"
    bl_description = ("读取 target PMX 文件, 把里面的 rigid body + joint 1:1 克隆到当前 MMD 模型. "
                      "骨名自动归一化 (左X ↔ X.L). 最适合给 Reika/DAZ 类模型补发型物理.")
    bl_options = {'REGISTER', 'UNDO'}

    filepath: StringProperty(subtype='FILE_PATH')  # type: ignore
    filter_glob: StringProperty(default='*.pmx;*.pmd', options={'HIDDEN'})  # type: ignore
    build_rig: BoolProperty(
        name="应用后 build_rig",
        description="生成物理后立即运行 mmd_tools.build_rig 激活模拟",
        default=True,
    )  # type: ignore
    clear_existing: BoolProperty(
        name="先清空已有物理",
        description="克隆前删除模型上已有的 rigid body 和 joint",
        default=True,
    )  # type: ignore
    fit_to_mesh: BoolProperty(
        name="贴合 mesh 实际粗细",
        description="克隆后根据骨骼权重的顶点分布, 自动收紧半径",
        default=True,
    )  # type: ignore
    add_missing_bones: BoolProperty(
        name="自动补 target 里缺失的骨",
        description="target PMX 里的刚体若绑的骨 converted 模型没有 (例如作者手加的挂饰骨), 自动从 target 读 head/tail/parent 创建. 关掉则这些刚体被 skip.",
        default=True,
    )  # type: ignore

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        active = context.active_object
        if active is None:
            self.report({'ERROR'}, "没有 active object")
            return {'CANCELLED'}
        root = _find_mmd_root(active)
        if root is None:
            self.report({'ERROR'}, "active 不在任何 mmd_root 下 (先跑 use_mmd_tools_convert)")
            return {'CANCELLED'}
        if not self.filepath or not os.path.isfile(self.filepath):
            self.report({'ERROR'}, f"PMX 文件不存在: {self.filepath}")
            return {'CANCELLED'}
        if not self.filepath.lower().endswith(('.pmx', '.pmd')):
            self.report({'ERROR'}, "只支持 .pmx / .pmd")
            return {'CANCELLED'}

        if self.clear_existing:
            model = _get_model(root)
            stale = list(model.rigidBodies()) + list(model.joints())
            for o in stale:
                bpy.data.objects.remove(o, do_unlink=True)

        try:
            n_r, n_j, skipped, n_total = clone_physics_from_pmx(
                root, self.filepath, fit_to_mesh=self.fit_to_mesh,
                add_missing_bones=self.add_missing_bones)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.report({'ERROR'}, f"克隆失败: {e}")
            return {'CANCELLED'}

        if skipped:
            # Show up to first 5 skipped names
            preview = ', '.join(skipped[:5])
            more = f" +{len(skipped)-5} more" if len(skipped) > 5 else ''
            print(f"[CTMMD clone] skipped bones: {preview}{more}")

        msg = (f"克隆完成: {n_r}/{n_total} rigids, {n_j} joints"
               + (f", skipped {len(skipped)} 骨" if skipped else ''))
        self.report({'INFO'}, msg)

        if self.build_rig:
            for o in bpy.data.objects: o.select_set(False)
            root.select_set(True)
            context.view_layer.objects.active = root
            try:
                bpy.ops.mmd_tools.build_rig()
            except Exception as e:
                self.report({'WARNING'}, f"build_rig 失败: {e}")
        return {'FINISHED'}


# ---------- /Tier 1 ----------


# ---------- Tier 3: auto-generate physics for dynamic bone chains ----------

def _bone_world_midpoint(arm, bone):
    """World-space midpoint of a bone (head + tail) / 2."""
    mw = arm.matrix_world
    head = mw @ bone.head_local
    tail = mw @ bone.tail_local
    return (head + tail) * 0.5


def _bone_world_rotation_yxz(arm, bone):
    """Bone's world-space rotation as YXZ Euler."""
    world_mat = arm.matrix_world @ bone.matrix_local
    return world_mat.to_euler('YXZ')


def _bone_weighted_vert_count(bone_name, meshes):
    """Sum of verts (across given meshes) with weight > 0.3 on this bone."""
    n = 0
    for m in meshes:
        vg = m.vertex_groups.get(bone_name)
        if vg is None:
            continue
        for v in m.data.vertices:
            for g in v.groups:
                if g.group == vg.index and g.weight > 0.3:
                    n += 1
                    break
    return n


# Default anchor bones Tier 3 walks from. 頭 (hair) is the overwhelmingly
# common case. Skirt (下半身) / sleeves (手首) / tails (下半身) can be opted
# in via the operator's `anchor_bones` arg.
DEFAULT_AUTO_ANCHORS = frozenset(['頭'])


def _detect_dynamic_chains(dst_root, arm, *, min_chain_length=2,
                             anchor_bones=None):
    """Walk armature, find bone subtrees that qualify as dynamic chains:

      1) root bone NOT in CANONICAL_BODY_BONES (includes MMD standard
         body + finger bones, both half-width and full-width digits)
      2) root name not `_dummy_*` / `_shadow_*` (mmd_tools internal helpers)
      3) parent IN `anchor_bones` (default {'頭'}, user-expandable to include
         下半身 for skirts / 手首 for sleeves / etc.)
      4) subtree size >= min_chain_length (default 2 — filters single-leaf
         bones like DAZ anatomical helpers / toe splits)

    Returns list of dicts:
      { 'root': Bone, 'chain': [Bone, ...] (all bones in subtree),
        'parent_body_bone': str, 'depth_by_name': {name: int} }
    """
    if anchor_bones is None:
        anchor_bones = DEFAULT_AUTO_ANCHORS
    chains = []
    for b in arm.data.bones:
        if b.name in CANONICAL_BODY_BONES:
            continue
        if _is_internal_helper_bone(b.name):
            continue
        parent = b.parent
        if parent is None or parent.name not in anchor_bones:
            continue

        # BFS collect subtree, skipping any descendant that lands back on a
        # canonical body bone or is an mmd_tools helper.
        subtree = []
        depth_by_name = {}
        stack = [(b, 0)]
        while stack:
            cur, d = stack.pop()
            if cur.name in CANONICAL_BODY_BONES:
                continue
            if _is_internal_helper_bone(cur.name):
                continue
            subtree.append(cur)
            depth_by_name[cur.name] = d
            for ch in cur.children:
                stack.append((ch, d + 1))
        if len(subtree) < min_chain_length:
            continue
        chains.append({
            'root': b,
            'chain': subtree,
            'parent_body_bone': parent.name,
            'depth_by_name': depth_by_name,
        })
    return chains


_HEAD_BONE_NAME = '頭'


def _is_hair_chain(chain_entry):
    """Chain anchored on 頭 → treat as hair for collision-group purposes."""
    return chain_entry.get('parent_body_bone') == _HEAD_BONE_NAME


def auto_generate_chain_physics(dst_root, *,
                                 anchor_bones=None,
                                 radius_ratio=0.15,
                                 root_angle_deg=10.0,
                                 leaf_angle_deg=30.0,
                                 hair_group=2,
                                 other_group=3,
                                 skip_if_exists=True,
                                 fit_to_mesh=True,
                                 fit_pad=1.10):
    """Generate rigid bodies + joints for every detected dynamic chain.

    PMXEditor-style heuristic (see doc/physics_generalization_plan_2026_04_19.md):
      - Bone has children → CAPSULE (len = bone.length, r = bone.length * radius_ratio)
      - Leaf bone → SPHERE (r = bone.length * radius_ratio, or 0.01m floor)
      - Position: bone midpoint (world head+tail)/2
      - Rotation: bone world matrix YXZ
      - dynamics_type: chain root = STATIC(0), everything else = DYNAMIC(1)
      - mass = 0.5 * 0.8^depth (decays along chain)
      - friction=0.5, damping=0.5, bounce=0
      - Hair (under 頭) → collision group `hair_group`, mask excludes body
        group 1; other chains (skirts, sleeves) → `other_group`.
      - Joints between parent-child rigids; angle limit eases from
        `root_angle_deg` at root to `leaf_angle_deg` at leaves.

    skip_if_exists: don't create a rigid body if one already exists for
        that bone (lets this operator run after setup_physics / target
        clone without duplicating body rigids).

    Returns (n_rigids, n_joints, chain_count).
    """
    import math
    from mmd_tools.core.rigid_body import MODE_STATIC, MODE_DYNAMIC

    dst_model = _get_model(dst_root)
    dst_arm = dst_model.armature()

    existing_by_bone = {}
    for o in bpy.data.objects:
        try:
            if o.mmd_type == 'RIGID_BODY':
                bn = o.mmd_rigid.bone
                if bn:
                    existing_by_bone[bn] = o
        except Exception:
            pass

    chains = _detect_dynamic_chains(dst_root, dst_arm, anchor_bones=anchor_bones)
    print(f"[CTMMD auto-chain] detected {len(chains)} dynamic chain(s) "
          f"from anchors {sorted(anchor_bones or DEFAULT_AUTO_ANCHORS)}")

    total_rigids = 0
    total_joints = 0
    bone_to_rigid_obj = dict(existing_by_bone)

    for entry in chains:
        is_hair = _is_hair_chain(entry)
        group = hair_group if is_hair else other_group
        # Collision mask: 16 bools, True = will NOT collide with that group.
        # We want: chain does NOT collide with body group (1), and does not
        # collide with itself (own group). All others collidable.
        mask = [False] * 16
        mask[0] = True           # body rigid group (1-indexed in UI, 0 here)
        mask[group - 1] = True   # own group

        for bone in entry['chain']:
            if skip_if_exists and bone.name in existing_by_bone:
                continue
            depth = entry['depth_by_name'].get(bone.name, 0)
            is_root = (bone == entry['root'])
            has_children = len(bone.children) > 0
            bone_length = max(bone.length, 0.01)
            radius = max(bone_length * radius_ratio, 0.005)

            if has_children:
                shape_name = 'CAPSULE'
                size = (radius, bone_length, 0.0)
            else:
                shape_name = 'SPHERE'
                size = (radius, 0.0, 0.0)

            loc = _bone_world_midpoint(dst_arm, bone)
            rot = _bone_world_rotation_yxz(dst_arm, bone)
            mass = 0.5 * (0.8 ** depth)

            nr = dst_model.createRigidBody(
                shape_type=SHAPE_IDX[shape_name],
                location=loc,
                rotation=rot,
                size=size,
                dynamics_type=MODE_STATIC if is_root else MODE_DYNAMIC,
                name=bone.name,
                name_e=bone.name,
                bone=bone.name,
                friction=0.5,
                mass=mass,
                angular_damping=0.5,
                linear_damping=0.5,
                bounce=0.0,
                collision_group_number=group,
                collision_group_mask=mask,
            )
            bone_to_rigid_obj[bone.name] = nr
            total_rigids += 1

        # Joints: one per (child-parent) edge within the chain subtree
        # (including chain_root ↔ chain_root.child).
        # max chain depth:
        max_d = max(entry['depth_by_name'].values()) if entry['depth_by_name'] else 0
        for bone in entry['chain']:
            parent = bone.parent
            if parent is None:
                continue
            # Only connect within this subtree OR to parent_body_bone
            pa_name = parent.name
            na = bone_to_rigid_obj.get(pa_name)
            nb = bone_to_rigid_obj.get(bone.name)
            if na is None or nb is None:
                continue
            # Joint location = bone head world (= parent tail)
            loc = dst_arm.matrix_world @ bone.head_local
            rot = _bone_world_rotation_yxz(dst_arm, bone)

            # Angle limit eases from root_angle at depth 0 to leaf_angle at max_d
            depth = entry['depth_by_name'].get(bone.name, 0)
            if max_d > 0:
                t = depth / max_d
            else:
                t = 1.0
            ang_deg = root_angle_deg + (leaf_angle_deg - root_angle_deg) * t
            ang_rad = math.radians(ang_deg)

            dst_model.createJoint(
                name=bone.name,
                name_e=bone.name,
                location=loc,
                rotation=rot,
                rigid_a=na,
                rigid_b=nb,
                maximum_location=(0.0, 0.0, 0.0),
                minimum_location=(0.0, 0.0, 0.0),
                maximum_rotation=(ang_rad, ang_rad, ang_rad),
                minimum_rotation=(-ang_rad, -ang_rad, -ang_rad),
                spring_angular=(0.0, 0.0, 0.0),
                spring_linear=(0.0, 0.0, 0.0),
            )
            total_joints += 1

    if fit_to_mesh and total_rigids > 0:
        fallback_mesh = _find_body_mesh(dst_root)
        if fallback_mesh is not None:
            for entry in chains:
                for bone in entry['chain']:
                    nr = bone_to_rigid_obj.get(bone.name)
                    if nr is None:
                        continue
                    # Don't touch pre-existing rigids (user/template authored)
                    if existing_by_bone.get(bone.name) is nr:
                        continue
                    shape = nr.mmd_rigid.shape
                    per_bone_mesh = _find_best_mesh_for_bone(dst_root, bone.name) or fallback_mesh
                    _fit_rigid_to_bone_verts(nr, dst_arm, per_bone_mesh, bone.name,
                                             shape, pad=fit_pad)

    return total_rigids, total_joints, len(chains)


class OBJECT_OT_auto_chain_physics(bpy.types.Operator):
    """Auto-generate rigid bodies + joints for dynamic bone chains (hair, skirt, etc.)."""
    bl_idname = "object.auto_chain_physics"
    bl_label = "💇 自动生成动态骨链刚体"
    bl_description = ("扫描 armature 找出非标准 body 骨的骨链 (发型/裙摆/尾巴等), "
                      "按 PMXEditor 经验公式 (CAPSULE r=骨长×0.15, 根 STATIC 其余 DYNAMIC, "
                      "angle limit 按深度从 ±10° 到 ±30°) 自动生成 rigid+joint. "
                      "可在 Tier 1 克隆 / Tier 2 模板之后追加, 已存在的 rigid 会跳过.")
    bl_options = {'REGISTER', 'UNDO'}

    anchor_bones: StringProperty(
        name="锚点骨 (逗号分隔)",
        description="只处理 parent 在此列表里的链 (默认 '頭' = 只生成发型物理; "
                    "可加 '下半身,手首.L,手首.R' 覆盖裙摆/袖口)",
        default='頭',
    )  # type: ignore
    radius_ratio: bpy.props.FloatProperty(
        name="半径/骨长比",
        description="CAPSULE/SPHERE 半径 = 骨长 × 该比例 (PMXEditor 经验值 0.1-0.2)",
        default=0.15, min=0.05, max=0.5,
    )  # type: ignore
    root_angle_deg: bpy.props.FloatProperty(
        name="根 joint 角度限制 (°)",
        description="链根关节的每轴角度限制 (紧贴根骨)",
        default=10.0, min=0.0, max=90.0,
    )  # type: ignore
    leaf_angle_deg: bpy.props.FloatProperty(
        name="梢 joint 角度限制 (°)",
        description="链梢关节的每轴角度限制 (越大越柔软)",
        default=30.0, min=0.0, max=180.0,
    )  # type: ignore
    skip_if_exists: BoolProperty(
        name="跳过已有 rigid 的骨",
        description="已有 rigid body 的骨不重复创建 — 允许在模板/克隆之后补骨链",
        default=True,
    )  # type: ignore
    fit_to_mesh: BoolProperty(
        name="贴合 mesh 实际粗细",
        default=True,
    )  # type: ignore
    build_rig: BoolProperty(
        name="应用后 build_rig",
        default=True,
    )  # type: ignore

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=320)

    def execute(self, context):
        active = context.active_object
        if active is None:
            self.report({'ERROR'}, "没有 active object")
            return {'CANCELLED'}
        root = _find_mmd_root(active)
        if root is None:
            self.report({'ERROR'}, "active 不在任何 mmd_root 下")
            return {'CANCELLED'}
        anchors = frozenset(n.strip() for n in self.anchor_bones.split(',') if n.strip())
        if not anchors:
            anchors = DEFAULT_AUTO_ANCHORS
        try:
            n_r, n_j, n_c = auto_generate_chain_physics(
                root,
                anchor_bones=anchors,
                radius_ratio=self.radius_ratio,
                root_angle_deg=self.root_angle_deg,
                leaf_angle_deg=self.leaf_angle_deg,
                skip_if_exists=self.skip_if_exists,
                fit_to_mesh=self.fit_to_mesh,
            )
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.report({'ERROR'}, f"自动生成失败: {e}")
            return {'CANCELLED'}
        self.report({'INFO'}, f"生成 {n_r} rigids, {n_j} joints, {n_c} 条骨链")

        if self.build_rig:
            for o in bpy.data.objects: o.select_set(False)
            root.select_set(True)
            context.view_layer.objects.active = root
            try:
                bpy.ops.mmd_tools.build_rig()
            except Exception as e:
                self.report({'WARNING'}, f"build_rig 失败: {e}")
        return {'FINISHED'}


# ---------- /Tier 3 ----------


class OBJECT_OT_setup_physics(bpy.types.Operator):
    """Apply a physics template (rigid bodies + joints) to the active MMD model."""
    bl_idname = "object.setup_physics"
    bl_label = "设置物理 (加载模板)"
    bl_description = "从 presets/physics/ 加载 JSON 模板, 给当前 MMD 模型生成 rigid body + joint"
    bl_options = {'REGISTER', 'UNDO'}

    template: EnumProperty(
        name="模板",
        description="选择 physics 模板 JSON",
        items=_list_physics_templates,
    )
    build_rig: BoolProperty(
        name="应用后 build_rig",
        description="生成物理后立即运行 mmd_tools.build_rig 激活模拟",
        default=True,
    )
    clear_existing: BoolProperty(
        name="先清空已有物理",
        description="应用前删除模型上已有的 rigid body 和 joint",
        default=True,
    )
    fit_to_mesh: BoolProperty(
        name="贴合 mesh 实际粗细",
        description="应用后根据骨骼权重的顶点分布, 自动收紧/放大每个 rigid 的 radius",
        default=True,
    )

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=320)

    def execute(self, context):
        if self.template == '__empty__':
            self.report({'ERROR'}, "presets/physics/ 下没有模板 JSON")
            return {'CANCELLED'}

        active = context.active_object
        if active is None:
            self.report({'ERROR'}, "没有 active object")
            return {'CANCELLED'}
        root = _find_mmd_root(active)
        if root is None:
            self.report({'ERROR'}, "active 不在任何 mmd_root 下 (先跑 use_mmd_tools_convert)")
            return {'CANCELLED'}

        template_path = os.path.join(_presets_physics_dir(), self.template + '.json')
        if not os.path.isfile(template_path):
            self.report({'ERROR'}, f"模板文件不存在: {template_path}")
            return {'CANCELLED'}

        try:
            with open(template_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            self.report({'ERROR'}, f"读取模板失败: {e}")
            return {'CANCELLED'}

        if self.clear_existing:
            model = _get_model(root)
            stale = list(model.rigidBodies()) + list(model.joints())
            for o in stale:
                bpy.data.objects.remove(o, do_unlink=True)

        try:
            n_r, n_j, skipped = apply_physics(root, data, fit_to_mesh=self.fit_to_mesh)
        except Exception as e:
            self.report({'ERROR'}, f"应用 physics 失败: {e}")
            return {'CANCELLED'}

        msg = f"Physics applied: {n_r} rigids, {n_j} joints"
        if skipped:
            msg += f", skipped {len(skipped)} (bones missing in target armature)"
            print(f"[CTMMD physics] skipped bones: {skipped}")
        self.report({'INFO'}, msg)

        if self.build_rig:
            for o in bpy.data.objects:
                o.select_set(False)
            root.select_set(True)
            context.view_layer.objects.active = root
            try:
                bpy.ops.mmd_tools.build_rig()
            except Exception as e:
                self.report({'WARNING'}, f"build_rig 失败: {e}")

        return {'FINISHED'}


class OBJECT_OT_toggle_rigid_visibility(bpy.types.Operator):
    """Toggle viewport visibility of all mmd rigid bodies & joints in the scene."""
    bl_idname = "object.toggle_rigid_visibility"
    bl_label = "显示/隐藏 全部刚体"
    bl_description = "一键切换场景里所有 mmd rigid body + joint 的视口可见性 (可用于对比两个模型)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        # mmd_tools 通过 mmd_root.show_rigid_bodies / show_joints 控制可见性,
        # 直接改对象的 hide_viewport 会被 mmd_tools 覆盖, 所以这里切 mmd_root flag.
        roots = [o for o in bpy.data.objects if getattr(o, 'mmd_type', '') == 'ROOT']
        if not roots:
            self.report({'INFO'}, "场景里没有 mmd_root")
            return {'CANCELLED'}
        # 方向: 看第一个 root, 任一 flag 为 True 就全关, 否则全开
        any_on = any(r.mmd_root.show_rigid_bodies or r.mmd_root.show_joints for r in roots)
        new_state = not any_on
        for r in roots:
            r.mmd_root.show_rigid_bodies = new_state
            r.mmd_root.show_joints = new_state
        state = "显示" if new_state else "隐藏"
        self.report({'INFO'}, f"{state} {len(roots)} 个 mmd 模型的 rigid/joint")
        return {'FINISHED'}


class OBJECT_OT_extract_physics_template(bpy.types.Operator):
    """Extract physics from the active MMD model to a JSON template under presets/physics/."""
    bl_idname = "object.extract_physics_template"
    bl_label = "抽取物理模板"
    bl_description = "把当前 MMD 模型的 rigid body + joint 配置导出为 JSON 模板, 日后复用"

    template_name: StringProperty(
        name="模板文件名 (不带 .json)",
        default="my_physics_template",
    )

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        active = context.active_object
        if active is None:
            self.report({'ERROR'}, "没有 active object")
            return {'CANCELLED'}
        root = _find_mmd_root(active)
        if root is None:
            self.report({'ERROR'}, "active 不在任何 mmd_root 下")
            return {'CANCELLED'}

        name = self.template_name.strip()
        if not name:
            self.report({'ERROR'}, "模板名不能为空")
            return {'CANCELLED'}
        if not name.endswith('.json'):
            name += '.json'

        try:
            data = extract_physics(root)
        except Exception as e:
            self.report({'ERROR'}, f"抽取失败: {e}")
            return {'CANCELLED'}

        out_dir = _presets_physics_dir()
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, name)
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        n_r = sum(1 for r in data['rigids'] if r is not None)
        self.report({'INFO'}, f"Extracted to {out_path}: {n_r} rigids, {len(data['joints'])} joints")
        return {'FINISHED'}
