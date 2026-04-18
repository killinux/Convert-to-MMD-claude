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
