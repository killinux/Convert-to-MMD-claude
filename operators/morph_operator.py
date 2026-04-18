"""Clone topology-safe morphs from a target MMD model.

Target PMX imports (e.g. Purifier Inase 18, Reika Shimohira 2) ship with the
standard MMD expression set (あ/い/う/え/お/まばたき/笑い/ウィンク …). This
operator copies the bone / material / group morphs from the target root onto
the converted model.

Only topology-safe morph types are cloned:
  - bone_morphs — references bone names, safe
  - material_morphs — references material names, safe if names match
  - group_morphs — references other morph names, safe once bone/material are cloned

vertex_morphs and uv_morphs are keyed by vertex index and are NOT cloned
(different mesh topology between source and target). See TODO.md P3.
"""
import bpy
from bpy.props import StringProperty, BoolProperty


BONE_MORPH_COPY_FIELDS = ('location', 'rotation')
MATERIAL_MORPH_COPY_FIELDS = (
    'offset_type',
    'diffuse_color', 'specular_color', 'shininess',
    'ambient_color', 'edge_color', 'edge_weight',
    'texture_factor', 'sphere_texture_factor', 'toon_texture_factor',
)
GROUP_MORPH_FIELDS = ('name', 'morph_type', 'factor')
MORPH_META_FIELDS = ('name', 'name_e', 'category')


def _copy_fields(src, dst, fields, log_errors=False):
    for f in fields:
        if not hasattr(src, f) or not hasattr(dst, f):
            continue
        val = getattr(src, f)
        # FloatVectorProperty / bpy_prop_array — copy as list to avoid reference issues
        try:
            val = list(val)  # works for vectors, iterable strings stay iterable
            # preserve strings as-is (don't list-ify a str into chars)
            if isinstance(getattr(src, f), str):
                val = getattr(src, f)
        except TypeError:
            pass
        try:
            setattr(dst, f, val)
        except Exception as e:
            if log_errors:
                print(f'[CTMMD 13] _copy_fields skip {f}: {e}')


def _get_model(root_obj):
    from mmd_tools.core.model import Model as MMDModel
    return MMDModel(root_obj)


def _resolve_mmd_root(name):
    obj = bpy.data.objects.get(name)
    if obj is None:
        return None
    if getattr(obj, 'mmd_type', '') == 'ROOT':
        return obj
    cur = obj
    while cur is not None:
        if getattr(cur, 'mmd_type', '') == 'ROOT':
            return cur
        cur = cur.parent
    return None


def _clone_bone_morphs(src_root, dst_root, dst_arm):
    # mmd_tools BoneMorphData.bone is a virtual StringProperty backed by
    # bone_id — its setter looks up FnModel(prop.id_data).armature() which
    # can fail silently when the PropertyGroup is freshly .add()'d inside
    # an operator. Resolve bone_id up-front via FnBone and write it
    # directly, bypassing the setter.
    from mmd_tools.core.bone import FnBone
    cloned = 0
    skipped_bones = set()
    dropped = 0
    bone_id_cache = {}
    def _get_bone_id(name):
        if name in bone_id_cache:
            return bone_id_cache[name]
        pb = dst_arm.pose.bones.get(name)
        if pb is None:
            bone_id_cache[name] = -1
            return -1
        bid = FnBone(pb).bone_id
        bone_id_cache[name] = bid
        return bid

    dst_bones = set(dst_arm.pose.bones.keys())
    for src_m in src_root.mmd_root.bone_morphs:
        dst_m = dst_root.mmd_root.bone_morphs.add()
        _copy_fields(src_m, dst_m, MORPH_META_FIELDS)
        kept = 0
        for src_off in src_m.data:
            name = src_off.bone
            if name not in dst_bones:
                skipped_bones.add(name)
                continue
            bid = _get_bone_id(name)
            if bid < 0:
                skipped_bones.add(name)
                continue
            dst_off = dst_m.data.add()
            _copy_fields(src_off, dst_off, BONE_MORPH_COPY_FIELDS)
            dst_off["bone_id"] = bid
            kept += 1
        if kept == 0:
            dst_root.mmd_root.bone_morphs.remove(len(dst_root.mmd_root.bone_morphs) - 1)
            dropped += 1
        else:
            cloned += 1
    return cloned, dropped, skipped_bones


def _clone_material_morphs(src_root, dst_root, dst_meshes):
    # MaterialMorphData.material is a virtual StringProperty backed by
    # material_id. Same bypass pattern as bone: pre-resolve material_id and
    # write it directly rather than going through the RNA setter.
    from mmd_tools.core.material import FnMaterial
    mat_id_cache = {}
    def _get_material_id(name):
        if name in mat_id_cache:
            return mat_id_cache[name]
        mat = bpy.data.materials.get(name)
        if mat is None:
            mat_id_cache[name] = -1
            return -1
        fm = FnMaterial(mat)
        bid = fm.material_id
        mat_id_cache[name] = bid
        return bid

    dst_mesh_names = {m.name for m in dst_meshes}
    dst_mat_names = set()
    for m in dst_meshes:
        for slot in m.data.materials:
            if slot is not None:
                dst_mat_names.add(slot.name)

    cloned = 0
    skipped_materials = set()
    dropped = 0
    for src_m in src_root.mmd_root.material_morphs:
        dst_m = dst_root.mmd_root.material_morphs.add()
        _copy_fields(src_m, dst_m, MORPH_META_FIELDS)
        kept = 0
        for src_off in src_m.data:
            mat_name = getattr(src_off, 'material', '')
            # Empty material name = "applies to all materials", keep as-is.
            if mat_name:
                if mat_name not in dst_mat_names:
                    skipped_materials.add(mat_name)
                    continue
                bid = _get_material_id(mat_name)
                if bid < 0:
                    skipped_materials.add(mat_name)
                    continue
            else:
                bid = -1
            dst_off = dst_m.data.add()
            _copy_fields(src_off, dst_off, MATERIAL_MORPH_COPY_FIELDS)
            dst_off["material_id"] = bid
            related = getattr(src_off, 'related_mesh', '')
            if related and related in dst_mesh_names:
                dst_off["related_mesh"] = related
            kept += 1
        if kept == 0:
            dst_root.mmd_root.material_morphs.remove(len(dst_root.mmd_root.material_morphs) - 1)
            dropped += 1
        else:
            cloned += 1
    return cloned, dropped, skipped_materials


def _clone_group_morphs(src_root, dst_root):
    dst_names = {m.name for m in dst_root.mmd_root.bone_morphs}
    dst_names |= {m.name for m in dst_root.mmd_root.material_morphs}
    dst_names |= {m.name for m in dst_root.mmd_root.vertex_morphs}
    dst_names |= {m.name for m in dst_root.mmd_root.uv_morphs}

    cloned = 0
    skipped_refs = set()
    dropped = 0
    for src_m in src_root.mmd_root.group_morphs:
        dst_m = dst_root.mmd_root.group_morphs.add()
        _copy_fields(src_m, dst_m, MORPH_META_FIELDS)
        kept = 0
        for src_off in src_m.data:
            ref_name = getattr(src_off, 'name', '')
            if ref_name and ref_name not in dst_names:
                skipped_refs.add(ref_name)
                continue
            dst_off = dst_m.data.add()
            _copy_fields(src_off, dst_off, GROUP_MORPH_FIELDS)
            kept += 1
        if kept == 0:
            dst_root.mmd_root.group_morphs.remove(len(dst_root.mmd_root.group_morphs) - 1)
            dropped += 1
        else:
            cloned += 1
    return cloned, dropped, skipped_refs


class OBJECT_OT_clone_morphs_from_target(bpy.types.Operator):
    """从 target PMX 克隆 bone/material/group morph 到 source 转换模型。
    vertex_morph 和 uv_morph 因 topology 不同不克隆。"""
    bl_idname = "object.clone_morphs_from_target"
    bl_label = "从 target 克隆表情 morph"
    bl_description = "克隆 target 的 bone/material/group morph 到 source 模型 (vertex/uv morph 因 topology 不同跳过)"
    bl_options = {'REGISTER', 'UNDO'}

    source_name: StringProperty(
        name="Source (目的地)",
        description="接收 morph 的转换后 mmd_root 对象名 (mmd_type=='ROOT')",
        default="",
    )
    target_name: StringProperty(
        name="Target (来源)",
        description="提供 morph 的参考 PMX mmd_root 对象名",
        default="",
    )
    clear_existing: BoolProperty(
        name="先清空 source 现有 morph",
        description="克隆前清空 source 的 bone/material/group morph，避免重复运行累积",
        default=True,
    )

    def invoke(self, context, event):
        # Default source to active's mmd_root if unset
        if not self.source_name:
            active = context.active_object
            root = _resolve_mmd_root(active.name) if active else None
            if root:
                self.source_name = root.name
        return context.window_manager.invoke_props_dialog(self, width=380)

    def draw(self, context):
        layout = self.layout
        layout.prop_search(self, 'source_name', bpy.data, 'objects', text='Source')
        layout.prop_search(self, 'target_name', bpy.data, 'objects', text='Target')
        layout.prop(self, 'clear_existing')

    def execute(self, context):
        src_root = _resolve_mmd_root(self.source_name)
        tgt_root = _resolve_mmd_root(self.target_name)
        if src_root is None:
            self.report({'ERROR'}, f"source_name {self.source_name!r} 不是 mmd_root")
            return {'CANCELLED'}
        if tgt_root is None:
            self.report({'ERROR'}, f"target_name {self.target_name!r} 不是 mmd_root")
            return {'CANCELLED'}
        if src_root == tgt_root:
            self.report({'ERROR'}, "source 和 target 必须是不同的 mmd_root")
            return {'CANCELLED'}

        src_model = _get_model(src_root)
        src_arm = src_model.armature()
        if src_arm is None:
            self.report({'ERROR'}, "source 模型没有 armature")
            return {'CANCELLED'}

        if self.clear_existing:
            src_root.mmd_root.bone_morphs.clear()
            src_root.mmd_root.material_morphs.clear()
            src_root.mmd_root.group_morphs.clear()

        dst_meshes = list(src_model.meshes())

        n_bone_src = len(tgt_root.mmd_root.bone_morphs)
        n_mat_src = len(tgt_root.mmd_root.material_morphs)
        n_grp_src = len(tgt_root.mmd_root.group_morphs)
        n_vert_src = len(tgt_root.mmd_root.vertex_morphs)
        n_uv_src = len(tgt_root.mmd_root.uv_morphs)

        n_bone, drop_bone, skip_bones = _clone_bone_morphs(tgt_root, src_root, src_arm)
        n_mat, drop_mat, skip_mats = _clone_material_morphs(tgt_root, src_root, dst_meshes)
        n_grp, drop_grp, skip_refs = _clone_group_morphs(tgt_root, src_root)

        def _short(s, n=6):
            if not s:
                return '[]'
            items = sorted(s)
            if len(items) <= n:
                return '[' + ', '.join(items) + ']'
            return '[' + ', '.join(items[:n]) + f', ...+{len(items) - n}]'

        summary = (
            f"bone={n_bone}/{n_bone_src} (dropped {drop_bone}), "
            f"material={n_mat}/{n_mat_src} (dropped {drop_mat}), "
            f"group={n_grp}/{n_grp_src} (dropped {drop_grp}); "
            f"SKIP {n_vert_src} vertex_morphs, {n_uv_src} uv_morphs (topology unsafe — TODO P2)"
        )
        print(f"[CTMMD 13] Cloned morphs: {summary}")
        if skip_bones:
            print(f"[CTMMD 13] skipped missing bones: {_short(skip_bones)}")
        if skip_mats:
            print(f"[CTMMD 13] skipped missing materials: {_short(skip_mats)}")
        if skip_refs:
            print(f"[CTMMD 13] skipped missing morph refs in groups: {_short(skip_refs)}")

        self.report({'INFO'}, f"Cloned bone={n_bone}, material={n_mat}, group={n_grp}")
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Vertex morph bake-and-transfer (方案 B)
# ---------------------------------------------------------------------------
#
# When the target's facial expressions are bone morphs (common for anime
# PMX models), cloning them onto the converted model is not enough to get
# visible expressions — our cleanup_face_bones step removed the XPS face
# bones and merged their weights into 頭, so the newly cloned driver
# bones have no mesh weights to deform.
#
# This operator simulates each target bone_morph on the target mesh
# (temporarily rotating the referenced bones, reading the evaluated mesh
# to get deformed vertex positions), then transfers the per-vertex
# offsets to the source mesh via head-local KDTree proximity. The
# result is a real vertex_morph on source that visibly deforms the mesh
# when the slider moves.


HEAD_BONE_CANDIDATES = ('頭', 'head neck upper')
FOOT_REF_BONE_CANDIDATES = ('足首.L', '左足首', '足首_L', 'leg left ankle')


def _find_head_bone(arm):
    for name in HEAD_BONE_CANDIDATES:
        if name in arm.pose.bones:
            return arm.pose.bones[name]
    return None


def _compute_body_height(arm, head_pb):
    """World-space distance from head bone head to ankle (fallback to bone length * 8)."""
    head_world = (arm.matrix_world @ head_pb.bone.matrix_local).to_translation()
    for name in FOOT_REF_BONE_CANDIDATES:
        pb = arm.pose.bones.get(name)
        if pb is not None:
            foot_world = (arm.matrix_world @ pb.bone.matrix_local).to_translation()
            return (head_world - foot_world).length
    # Fallback: use head bone length * 8 as body-height estimate
    return head_pb.bone.length * 8.0


def _bake_target_morph_offsets(tgt_arm, tgt_meshes, tgt_morph, min_magnitude=1e-4):
    """Pose the target armature to apply tgt_morph, then read evaluated
    mesh vertex positions. Returns {mesh_obj: [(basis_co, offset_vec, vert_idx), ...]}.

    Offsets are in each mesh's LOCAL mesh space (i.e. mesh.data coords),
    NOT world. Caller transforms as needed."""
    # Save original pose transforms
    stash = []
    for pb in tgt_arm.pose.bones:
        stash.append((pb.name,
                      pb.location.copy(),
                      pb.rotation_quaternion.copy(),
                      pb.rotation_mode))
        pb.rotation_mode = 'QUATERNION'

    # Reset all to rest
    for pb in tgt_arm.pose.bones:
        pb.location = (0, 0, 0)
        pb.rotation_quaternion = (1, 0, 0, 0)

    # Capture basis vertex positions (at rest pose, fully evaluated)
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    basis_coords = {}
    for m in tgt_meshes:
        em = m.evaluated_get(depsgraph)
        basis_coords[m.name] = [v.co.copy() for v in em.data.vertices]

    # Apply the morph
    for off in tgt_morph.data:
        pb = tgt_arm.pose.bones.get(off.bone)
        if pb is not None:
            pb.location = tuple(off.location)
            pb.rotation_quaternion = tuple(off.rotation)

    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()

    # Collect offsets per mesh
    result = {}
    total_morphed = 0
    for m in tgt_meshes:
        em = m.evaluated_get(depsgraph)
        basis = basis_coords[m.name]
        entries = []
        for i, v in enumerate(em.data.vertices):
            if i >= len(basis):
                continue
            offset = v.co - basis[i]
            if offset.length < min_magnitude:
                continue
            entries.append((basis[i].copy(), offset.copy(), i))
        if entries:
            result[m] = entries
            total_morphed += len(entries)

    # Restore pose
    for name, loc, rq, mode in stash:
        pb = tgt_arm.pose.bones.get(name)
        if pb is not None:
            pb.location = loc
            pb.rotation_quaternion = rq
            pb.rotation_mode = mode
    bpy.context.view_layer.update()

    return result, total_morphed


def _build_kdtree_for_morph(baked, tgt_head_world_pos, tgt_to_src_scale):
    """Build a KDTree in source-body-scaled head-relative world space.
    Each entry position is (target_world_pos - tgt_head_world_pos) * scale.
    Offsets are also scaled to source body units so they apply correctly.
    """
    from mathutils import kdtree
    entries = []  # list of (src_scaled_pos, src_scaled_offset)
    for tgt_mesh, verts in baked.items():
        mw = tgt_mesh.matrix_world
        for basis_co, offset, _idx in verts:
            world_basis = mw @ basis_co
            # Offset rotated by world linear part only (no translation)
            world_tip = mw @ (basis_co + offset)
            world_offset = world_tip - world_basis
            # Convert to source-scaled head-relative space
            src_scaled_pos = (world_basis - tgt_head_world_pos) * tgt_to_src_scale
            src_scaled_offset = world_offset * tgt_to_src_scale
            entries.append((src_scaled_pos, src_scaled_offset))

    if not entries:
        return None, entries
    kd = kdtree.KDTree(len(entries))
    for i, (pos, _offset) in enumerate(entries):
        kd.insert(pos, i)
    kd.balance()
    return kd, entries


def _apply_morph_to_source(src_meshes, src_head_world_pos,
                           kd, entries, morph_name,
                           distance_threshold, k_neighbors):
    """For each source mesh vertex, find nearest morphed target verts in
    shared head-relative source-scale space. Apply inverse-distance-
    weighted offset to a new shape key."""
    from mathutils import Vector
    total_applied = 0
    for src_mesh in src_meshes:
        mesh_data = src_mesh.data
        if mesh_data.shape_keys is None:
            src_mesh.shape_key_add(name='Basis', from_mix=False)
        sk_coll = mesh_data.shape_keys.key_blocks
        basis_key = mesh_data.shape_keys.reference_key
        sk = sk_coll.get(morph_name)
        if sk is None:
            sk = src_mesh.shape_key_add(name=morph_name, from_mix=False)
        else:
            for i, bv in enumerate(basis_key.data):
                sk.data[i].co = bv.co.copy()
        sk.value = 0.0

        mw = src_mesh.matrix_world
        mw_inv = mw.inverted()
        mw_inv_3x3 = mw_inv.to_3x3()
        applied = 0
        for i, bv in enumerate(basis_key.data):
            world_basis = mw @ bv.co
            query_pos = world_basis - src_head_world_pos
            neighbors = kd.find_n(query_pos, k_neighbors)
            if not neighbors:
                continue
            valid = [(pos, idx, d) for pos, idx, d in neighbors if d <= distance_threshold]
            if not valid:
                continue
            total_w = 0.0
            weighted = Vector((0.0, 0.0, 0.0))
            for _pos, idx, d in valid:
                w = 1.0 / max(d, 1e-4)
                weighted += entries[idx][1] * w
                total_w += w
            if total_w <= 0.0:
                continue
            avg_world_offset = weighted / total_w  # already in source-scale world
            local_offset = mw_inv_3x3 @ avg_world_offset
            sk.data[i].co = bv.co + local_offset
            applied += 1
        total_applied += applied
        print(f'[CTMMD 15]   {morph_name} -> {src_mesh.name}: applied {applied}/{len(basis_key.data)} verts')
    return total_applied


class OBJECT_OT_bake_and_transfer_morphs(bpy.types.Operator):
    """Bake each target bone_morph into vertex offsets on target mesh, then
    transfer those offsets to source mesh via head-local KDTree proximity.
    Produces real vertex_morphs on source that visibly deform the mesh.
    方案 B: 最终达到视觉表情效果的方案。"""
    bl_idname = "object.bake_and_transfer_morphs"
    bl_label = "③ bake + 按近邻传 vertex morph"
    bl_description = (
        "对 target 的每条 bone_morph 临时 pose 后评估 mesh 变形, 用 head-local KDTree 把 offset"
        " 按近邻加权传到 source, 生成真正能驱动顶点变形的 vertex_morph"
    )
    bl_options = {'REGISTER', 'UNDO'}

    source_name: StringProperty(
        name="Source (目的地)",
        default="",
    )
    target_name: StringProperty(
        name="Target (来源)",
        default="",
    )
    distance_threshold: bpy.props.FloatProperty(
        name="距离阈值 (head-local, 米)",
        description="source 顶点到最近 target morph 顶点距离超过此值则不应用 (越小越局部化)",
        default=0.02,
        min=0.001,
        max=0.2,
    )
    k_neighbors: bpy.props.IntProperty(
        name="K 近邻",
        description="每个 source 顶点用几个最近 target 顶点加权",
        default=3,
        min=1,
        max=10,
    )
    clear_existing: BoolProperty(
        name="先清空 source vertex_morphs",
        default=True,
    )
    min_offset_magnitude: bpy.props.FloatProperty(
        name="最小偏移过滤 (米)",
        description="target 顶点偏移小于此值视为未变形, 不参与 KDTree",
        default=1e-4,
        min=1e-6,
        max=0.01,
        precision=5,
    )

    def invoke(self, context, event):
        if not self.source_name:
            active = context.active_object
            root = _resolve_mmd_root(active.name) if active else None
            if root:
                self.source_name = root.name
        return context.window_manager.invoke_props_dialog(self, width=420)

    def draw(self, context):
        layout = self.layout
        layout.prop_search(self, 'source_name', bpy.data, 'objects', text='Source')
        layout.prop_search(self, 'target_name', bpy.data, 'objects', text='Target')
        layout.prop(self, 'distance_threshold')
        layout.prop(self, 'k_neighbors')
        layout.prop(self, 'clear_existing')
        layout.prop(self, 'min_offset_magnitude')

    def execute(self, context):
        src_root = _resolve_mmd_root(self.source_name)
        tgt_root = _resolve_mmd_root(self.target_name)
        if src_root is None or tgt_root is None or src_root == tgt_root:
            self.report({'ERROR'}, "source/target 必须是两个不同的 mmd_root")
            return {'CANCELLED'}

        src_model = _get_model(src_root)
        tgt_model = _get_model(tgt_root)
        src_arm = src_model.armature()
        tgt_arm = tgt_model.armature()
        if src_arm is None or tgt_arm is None:
            self.report({'ERROR'}, "source 或 target 缺 armature")
            return {'CANCELLED'}
        src_head_pb = _find_head_bone(src_arm)
        tgt_head_pb = _find_head_bone(tgt_arm)
        if src_head_pb is None or tgt_head_pb is None:
            self.report({'ERROR'}, "找不到头骨 (頭 / head neck upper)")
            return {'CANCELLED'}

        tgt_meshes = list(tgt_model.meshes())
        src_meshes = list(src_model.meshes())
        if not tgt_meshes or not src_meshes:
            self.report({'ERROR'}, "source 或 target 没 mesh")
            return {'CANCELLED'}

        # Head world positions
        src_head_world_pos = (src_arm.matrix_world @ src_head_pb.bone.matrix_local).to_translation()
        tgt_head_world_pos = (tgt_arm.matrix_world @ tgt_head_pb.bone.matrix_local).to_translation()
        # Body heights (head-to-ankle) to normalize scale across models
        src_h = _compute_body_height(src_arm, src_head_pb)
        tgt_h = _compute_body_height(tgt_arm, tgt_head_pb)
        tgt_to_src_scale = src_h / tgt_h if tgt_h > 1e-6 else 1.0
        print(f'[CTMMD 15] body height: src={src_h:.4f} tgt={tgt_h:.4f} '
              f'tgt→src scale={tgt_to_src_scale:.4f}')

        if self.clear_existing:
            src_root.mmd_root.vertex_morphs.clear()
            # Also remove pre-existing shape keys on source meshes that match any target morph name
            target_names = {m.name for m in tgt_root.mmd_root.bone_morphs}
            for src_mesh in src_meshes:
                if src_mesh.data.shape_keys is None:
                    continue
                for name in list(src_mesh.data.shape_keys.key_blocks.keys()):
                    if name in target_names:
                        sk = src_mesh.data.shape_keys.key_blocks[name]
                        src_mesh.shape_key_remove(sk)

        n_morphs = len(tgt_root.mmd_root.bone_morphs)
        n_transferred = 0
        per_morph_stats = []
        for i, tgt_morph in enumerate(tgt_root.mmd_root.bone_morphs):
            baked, n_morphed = _bake_target_morph_offsets(
                tgt_arm, tgt_meshes, tgt_morph,
                min_magnitude=self.min_offset_magnitude,
            )
            if not baked:
                print(f'[CTMMD 15] [{i+1}/{n_morphs}] {tgt_morph.name!r}: 0 morphed verts on target (skipped)')
                continue
            kd, entries = _build_kdtree_for_morph(baked, tgt_head_world_pos, tgt_to_src_scale)
            if kd is None:
                continue
            applied = _apply_morph_to_source(
                src_meshes, src_head_world_pos,
                kd, entries, tgt_morph.name,
                self.distance_threshold, self.k_neighbors,
            )
            # Register as mmd vertex_morph if not yet
            existing = {vm.name for vm in src_root.mmd_root.vertex_morphs}
            if tgt_morph.name not in existing and applied > 0:
                vm = src_root.mmd_root.vertex_morphs.add()
                vm.name = tgt_morph.name
                for fld in ('name_e', 'category'):
                    if hasattr(tgt_morph, fld) and hasattr(vm, fld):
                        try:
                            setattr(vm, fld, getattr(tgt_morph, fld))
                        except Exception:
                            pass
            per_morph_stats.append((tgt_morph.name, n_morphed, applied))
            if applied > 0:
                n_transferred += 1
            print(f'[CTMMD 15] [{i+1}/{n_morphs}] {tgt_morph.name!r}: {n_morphed} target verts → {applied} source verts')

        summary = f"transferred {n_transferred}/{n_morphs} morphs"
        print(f'[CTMMD 15] Bake+transfer done: {summary}')
        self.report({'INFO'}, summary)
        return {'FINISHED'}
