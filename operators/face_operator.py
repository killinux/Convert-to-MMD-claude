"""Face bone cleanup + face-morph-bone cloning operators.

Two operators live here:

* ``cleanup_face_bones`` (step 6 in the main pipeline)
  Removes XPS face-detail bones (``head eyebrow/eyelid/.../jaw *``) after
  merging their weights into the head bone. After this step the converted
  model has a clean MMD-style head rig but no face driver bones.

* ``clone_face_bones_from_target``
  Inverse/companion: brings back the face driver bones *from the target
  PMX* (e.g. ``Jaw Bone`` / ``QQ*``) so that ``clone_morphs_from_target``
  can clone bone morphs that reference them. Morph data will export to
  PMX correctly; visual deformation still requires either weight transfer
  or vertex morphs (see TODO P3).
"""
import bpy
from bpy.props import StringProperty


FACE_BONE_PREFIXES = (
    'head eyebrow',
    'head eyelid',
    'head lip',
    'head mouth',
    'head nose',
    'head tongue',
    'head cheek',
    'head jaw',
)

# Head bone may or may not have been renamed to MMD at the time this runs.
HEAD_BONE_CANDIDATES = ('頭', 'head neck upper')


def _find_head_bone_name(arm):
    for name in HEAD_BONE_CANDIDATES:
        if name in arm.data.bones:
            return name
    return None


def _find_face_bones(arm):
    return [b.name for b in arm.data.bones
            if any(b.name.startswith(p) for p in FACE_BONE_PREFIXES)]


def _merge_weights_to_head(mesh, face_bone_names, head_bone_name):
    """For each vert, add any face-bone weight to the head vertex group and
    zero out the face-bone weight.  Creates the head vg if missing."""
    head_vg = mesh.vertex_groups.get(head_bone_name)
    if head_vg is None:
        head_vg = mesh.vertex_groups.new(name=head_bone_name)

    face_vg_indices = {}
    for name in face_bone_names:
        vg = mesh.vertex_groups.get(name)
        if vg is not None:
            face_vg_indices[vg.index] = name
    if not face_vg_indices:
        return 0

    migrated_verts = 0
    for v in mesh.data.vertices:
        extra = 0.0
        has_face_weight = False
        for g in v.groups:
            if g.group in face_vg_indices:
                extra += g.weight
                has_face_weight = True
        if not has_face_weight:
            continue
        if extra > 0.0:
            head_vg.add([v.index], extra, 'ADD')
            migrated_verts += 1

    # Remove the emptied vertex groups.
    for name in face_bone_names:
        vg = mesh.vertex_groups.get(name)
        if vg is not None:
            mesh.vertex_groups.remove(vg)

    return migrated_verts


def _delete_bones_edit_mode(arm, bone_names):
    prev_mode = arm.mode
    bpy.ops.object.mode_set(mode='EDIT')
    try:
        ebones = arm.data.edit_bones
        deleted = 0
        for name in bone_names:
            eb = ebones.get(name)
            if eb is not None:
                ebones.remove(eb)
                deleted += 1
        return deleted
    finally:
        bpy.ops.object.mode_set(mode=prev_mode)


class OBJECT_OT_cleanup_face_bones(bpy.types.Operator):
    """Merge XPS face-detail bone weights into the head bone and delete them.

    Run this after ``rename_to_mmd`` so the head bone is named ``頭``. It
    still works pre-rename (falls back to ``head neck upper``)."""
    bl_idname = "object.cleanup_face_bones"
    bl_label = "清理 XPS 面部细骨"
    bl_description = (
        "把 head eyebrow/eyelid/lip/mouth/nose/tongue/cheek/jaw 等 XPS 面部细骨的权重"
        " 合并到 頭 (或 head neck upper), 然后删除这些骨."
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "active object 不是 armature")
            return {'CANCELLED'}
        arm = obj

        face_bones = _find_face_bones(arm)
        if not face_bones:
            self.report({'INFO'}, "没有找到 XPS 面部细骨, 跳过")
            return {'CANCELLED'}

        head_name = _find_head_bone_name(arm)
        if head_name is None:
            self.report({'ERROR'}, f"找不到头骨 (尝试过: {', '.join(HEAD_BONE_CANDIDATES)})")
            return {'CANCELLED'}

        # Collect meshes parented to (or with armature-modifier on) this arm
        target_meshes = []
        for o in bpy.data.objects:
            if o.type != 'MESH':
                continue
            if o.parent is arm:
                target_meshes.append(o)
                continue
            for m in o.modifiers:
                if m.type == 'ARMATURE' and m.object is arm:
                    target_meshes.append(o)
                    break

        if not target_meshes:
            self.report({'WARNING'}, "没有找到和该 armature 关联的 mesh")

        total_migrated = 0
        affected_meshes = 0
        for mesh in target_meshes:
            n = _merge_weights_to_head(mesh, face_bones, head_name)
            if n > 0:
                total_migrated += n
                affected_meshes += 1
                print(f'[CTMMD 6] {mesh.name}: merged {n} verts into {head_name}')

        deleted = _delete_bones_edit_mode(arm, face_bones)

        msg = (f"Face cleanup: deleted {deleted} bones, merged {total_migrated} vert-weights"
               f" across {affected_meshes} meshes into {head_name}")
        print(f'[CTMMD 6] {msg}')
        self.report({'INFO'}, msg)
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Clone face bones from target (prerequisite for clone_morphs_from_target)
# ---------------------------------------------------------------------------


def _resolve_mmd_root(name):
    obj = bpy.data.objects.get(name)
    if obj is None:
        return None
    cur = obj
    while cur is not None:
        if getattr(cur, 'mmd_type', '') == 'ROOT':
            return cur
        cur = cur.parent
    return None


def _collect_morph_referenced_bones(tgt_root):
    names = set()
    for m in tgt_root.mmd_root.bone_morphs:
        for off in m.data:
            if off.bone:
                names.add(off.bone)
    return names


MMD_BONE_COPY_FIELDS = (
    'name_j', 'name_e', 'is_tip', 'transform_order', 'is_controllable',
    'enabled_local_axes', 'local_axis_x', 'local_axis_z',
    'enabled_fixed_axis', 'fixed_axis',
)


def _clone_missing_face_bones(src_root, tgt_root):
    """Create bones in src_root's armature for every bone referenced by
    target's bone_morphs that is missing from src. Parents are cloned
    first (topological order); head/tail positions are preserved as
    offsets from parent so they attach correctly under src's existing
    rig (typically under 頭)."""
    from mmd_tools.core.model import Model as MMDModel
    from mmd_tools.core.bone import FnBone

    src_model = MMDModel(src_root)
    tgt_model = MMDModel(tgt_root)
    src_arm = src_model.armature()
    tgt_arm = tgt_model.armature()
    if src_arm is None or tgt_arm is None:
        return [], [], 'missing armature'

    referenced = _collect_morph_referenced_bones(tgt_root)
    src_names = set(src_arm.data.bones.keys())
    missing = referenced - src_names
    if not missing:
        return [], [], None

    # DFS → topological order (parents first)
    ordered = []
    seen = set()
    unreachable = []

    def walk(bname):
        if bname in src_names or bname in seen:
            return bname
        tbone = tgt_arm.data.bones.get(bname)
        if tbone is None:
            unreachable.append(bname)
            return None
        if tbone.parent is not None:
            walk(tbone.parent.name)
        seen.add(bname)
        # parent in src or in seen — compute attach name
        if tbone.parent is None:
            pname = None
        elif tbone.parent.name in src_names or tbone.parent.name in seen:
            pname = tbone.parent.name
        else:
            pname = None
        ordered.append((bname, pname))
        return bname

    for bname in missing:
        walk(bname)

    if not ordered:
        return [], unreachable, None

    # Edit mode on src_arm to create bones
    prev_active = bpy.context.view_layer.objects.active
    if bpy.context.object is not None and bpy.context.object.mode != 'OBJECT':
        try:
            bpy.ops.object.mode_set(mode='OBJECT')
        except RuntimeError:
            pass
    for o in bpy.data.objects:
        o.select_set(False)
    src_arm.select_set(True)
    bpy.context.view_layer.objects.active = src_arm
    bpy.ops.object.mode_set(mode='EDIT')
    created = []
    try:
        ebones = src_arm.data.edit_bones
        for bname, pname in ordered:
            if bname in ebones:
                continue
            tbone = tgt_arm.data.bones[bname]
            eb = ebones.new(bname)
            # Position: offset from parent in target, applied to src parent head
            if tbone.parent is not None:
                t_parent_head = tbone.parent.head_local
                off_head = tbone.head_local - t_parent_head
                off_tail = tbone.tail_local - t_parent_head
                if pname and pname in ebones:
                    s_parent_head = ebones[pname].head.copy()
                else:
                    s_parent_head = tbone.parent.head_local.copy()
                eb.head = s_parent_head + off_head
                eb.tail = s_parent_head + off_tail
            else:
                eb.head = tbone.head_local.copy()
                eb.tail = tbone.tail_local.copy()
            target_z = tbone.matrix_local.to_3x3().col[2]
            try:
                eb.align_roll(target_z)
            except Exception:
                pass
            eb.use_deform = tbone.use_deform
            if pname and pname in ebones:
                eb.parent = ebones[pname]
            created.append(bname)
    finally:
        bpy.ops.object.mode_set(mode='OBJECT')
        if prev_active is not None:
            bpy.context.view_layer.objects.active = prev_active

    # Copy mmd_bone metadata + trigger bone_id assignment
    for bname in created:
        tpb = tgt_arm.pose.bones.get(bname)
        spb = src_arm.pose.bones.get(bname)
        if tpb is None or spb is None:
            continue
        _ = FnBone(spb).bone_id
        tmb, smb = tpb.mmd_bone, spb.mmd_bone
        for fld in MMD_BONE_COPY_FIELDS:
            if hasattr(tmb, fld) and hasattr(smb, fld):
                try:
                    setattr(smb, fld, getattr(tmb, fld))
                except Exception:
                    pass

    return created, unreachable, None


class OBJECT_OT_clone_face_bones_from_target(bpy.types.Operator):
    """从 target PMX 把被 bone_morph 引用但 source 缺失的面部驱动骨克隆过来。
    作为 clone_morphs_from_target 的前置步骤。"""
    bl_idname = "object.clone_face_bones_from_target"
    bl_label = "从 target 补面部驱动骨 (给 morph 用)"
    bl_description = (
        "把 target 里被 bone_morph 引用 (如 Jaw Bone / QQ*) 但 source 缺失的面部骨克隆过来,"
        " 自动处理父链; 之后 clone_morphs_from_target 就能成功克隆面部表情 morph"
    )
    bl_options = {'REGISTER', 'UNDO'}

    source_name: StringProperty(
        name="Source (目的地)",
        description="接收骨的转换后 mmd_root 对象名",
        default="",
    )
    target_name: StringProperty(
        name="Target (来源)",
        description="提供骨的参考 PMX mmd_root 对象名",
        default="",
    )

    def invoke(self, context, event):
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
        layout.label(text="会把 target 里 bone_morph 引用但 source 缺的骨补进来", icon='INFO')

    def execute(self, context):
        src_root = _resolve_mmd_root(self.source_name)
        tgt_root = _resolve_mmd_root(self.target_name)
        if src_root is None or tgt_root is None or src_root == tgt_root:
            self.report({'ERROR'}, "source/target 必须是两个不同的 mmd_root")
            return {'CANCELLED'}

        created, unreachable, err = _clone_missing_face_bones(src_root, tgt_root)
        if err:
            self.report({'ERROR'}, err)
            return {'CANCELLED'}
        print(f'[CTMMD 14] Cloned {len(created)} face bones from target: '
              f'{created[:10]}{"..." if len(created) > 10 else ""}')
        if unreachable:
            print(f'[CTMMD 14] Could not resolve in target: {unreachable[:10]}'
                  f'{"..." if len(unreachable) > 10 else ""}')
        self.report({'INFO'}, f"补了 {len(created)} 根面部驱动骨")
        return {'FINISHED'}
