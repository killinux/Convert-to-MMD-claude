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
from mathutils import Matrix

SHAPE_IDX = {'SPHERE': 0, 'BOX': 1, 'CAPSULE': 2}


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
    best = None
    best_n = 0
    for c in mmd_root.children_recursive:
        if c.type == 'MESH' and getattr(c, 'mmd_type', '') != 'RIGID_BODY':
            n = len(c.data.vertices)
            if n > best_n:
                best_n = n
                best = c
    return best


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
    fit_stats = []
    if fit_to_mesh:
        body_mesh = _find_body_mesh(dst_root)
        if body_mesh is not None:
            for entry in data['rigids']:
                if entry is None:
                    continue
                if entry['idx'] not in rigid_idx_to_obj:
                    continue
                nr = rigid_idx_to_obj[entry['idx']]
                res = _fit_rigid_to_bone_verts(nr, dst_arm, body_mesh, entry['bone'],
                                               entry['shape'], pad=fit_pad)
                if res is not None:
                    old, new, n = res
                    # Only log if there was a meaningful change
                    if abs(old[0] - new[0]) > 0.005:
                        fit_stats.append((entry['bone'], round(old[0], 4), round(new[0], 4), n))
            if fit_stats:
                print(f"[CTMMD 12] fit_to_mesh adjustments ({len(fit_stats)}):")
                for b, o, nw, n in fit_stats:
                    arrow = '↓' if nw < o else '↑'
                    print(f"  {b:12} {o:.4f} {arrow} {nw:.4f}  ({n} verts)")

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
        body_mesh = _find_body_mesh(dst_root)
        if body_mesh is not None:
            for entry in data['rigids']:
                if entry is None or not _is_breast(entry['bone']):
                    continue
                if entry['idx'] not in rigid_idx_to_obj:
                    continue
                nr = rigid_idx_to_obj[entry['idx']]
                # skip if it's a reused existing rigid (don't mutate user's rigid)
                if existing_by_bone.get(entry['bone']) is nr:
                    continue
                _fit_rigid_to_bone_verts(nr, dst_arm, body_mesh, entry['bone'],
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
        print(f"[CTMMD 12] {msg}")
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
            print(f"[CTMMD 12] skipped bones: {skipped}")
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
        rigids = [o for o in bpy.data.objects if getattr(o, 'mmd_type', '') in ('RIGID_BODY', 'JOINT')]
        if not rigids:
            self.report({'INFO'}, "场景里没有 mmd rigid/joint")
            return {'CANCELLED'}
        # Decide direction: if any visible, hide all; else show all
        any_visible = any(not o.hide_viewport for o in rigids)
        new_hidden = any_visible
        for o in rigids:
            o.hide_viewport = new_hidden
        state = "隐藏" if new_hidden else "显示"
        self.report({'INFO'}, f"{state} {len(rigids)} 个 rigid/joint")
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
