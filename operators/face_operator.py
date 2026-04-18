"""Face bone cleanup + face-morph-bone cloning operators.

Two operators live here:

* ``cleanup_face_bones`` (step 7 in the main pipeline)
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


# Fallback prefix list — catches XPS face detail bones that somehow
# aren't parented under 頭 (rare but seen in older XPS rigs).
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
HEAD_BONE_CANDIDATES = ('頭', 'head neck upper', 'head')

# Bones under 頭 we NEVER merge/delete — standard MMD rig bones and
# physics/accessory bones the user probably wants to keep animating.
FACE_KEEP_EXACT = {'目.L', '目.R', '両目'}
FACE_KEEP_PREFIXES = ('ダミー', '舌', '顎')
FACE_KEEP_SUBSTRINGS_LOWER = ('hair',)  # case-insensitive
FACE_KEEP_SUBSTRINGS = ('耳', '飾り')    # CJK (no case folding needed)


def _find_head_bone_name(arm):
    for name in HEAD_BONE_CANDIDATES:
        if name in arm.data.bones:
            return name
    return None


def _should_keep_face_child(name: str) -> bool:
    if name in FACE_KEEP_EXACT:
        return True
    if any(name.startswith(p) for p in FACE_KEEP_PREFIXES):
        return True
    lower = name.lower()
    if any(kw in lower for kw in FACE_KEEP_SUBSTRINGS_LOWER):
        return True
    if any(kw in name for kw in FACE_KEEP_SUBSTRINGS):
        return True
    return False


def _walk_bone_subtree(arm, head_name):
    """Yield every descendant bone name of head_name (not including head itself)."""
    head = arm.data.bones.get(head_name)
    if head is None:
        return
    stack = list(head.children)
    while stack:
        b = stack.pop()
        yield b.name
        stack.extend(b.children)


def _find_face_bones(arm):
    head_name = _find_head_bone_name(arm)
    subtree_hits = set()
    if head_name is not None:
        for n in _walk_bone_subtree(arm, head_name):
            if not _should_keep_face_child(n):
                subtree_hits.add(n)
    # Fallback prefix scan (for rigs where face detail isn't under 頭)
    prefix_hits = {b.name for b in arm.data.bones
                   if any(b.name.startswith(p) for p in FACE_BONE_PREFIXES)}
    return sorted(subtree_hits | prefix_hits)


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
                print(f'[CTMMD 7] {mesh.name}: merged {n} verts into {head_name}')

        deleted = _delete_bones_edit_mode(arm, face_bones)

        msg = (f"Face cleanup: deleted {deleted} bones, merged {total_migrated} vert-weights"
               f" across {affected_meshes} meshes into {head_name}")
        print(f'[CTMMD 7] {msg}')
        self.report({'INFO'}, msg)
        return {'FINISHED'}

