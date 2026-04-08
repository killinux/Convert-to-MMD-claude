from math import radians
import bpy
DEFAULT_ROLL_VALUES = {
    "全ての親": 0.0, "センター": 0.0, "グルーブ": 0.0, "腰": 0.0,
    "上半身": 0.0, "上半身2": 0.0, "首": 0.0, "頭": 0.0,
    "下半身": 0.0, "足.L": 0.0, "足.R": 0.0, "ひざ.L": 0.0, "ひざ.R": 0.0, "足首.L": 0.0, "足首.R": 0.0, "足先EX.L": 0.0, "足先EX.R": 0.0,
    "腕.L": 45.0, "ひじ.L": 45.0, "手首.L": 45.0,
    "腕.R": 135.0, "ひじ.R": 135.0, "手首.R": 135.0,
    "肩.L": 0.0, "肩.R": 180.0
}

def create_or_update_bone(edit_bones, name, head_position, tail_position, use_connect=False, parent_name=None, use_deform=True):
    bone = edit_bones.get(name)
    if bone:
        bone.head = head_position
        bone.tail = tail_position
        bone.use_connect = use_connect
        bone.parent = edit_bones.get(parent_name) if parent_name else None
        bone.use_deform = use_deform
    else:
        bone = edit_bones.new(name)
        bone.head = head_position
        bone.tail = tail_position
        bone.use_connect = use_connect
        bone.parent = edit_bones.get(parent_name) if parent_name else None
        bone.use_deform = use_deform
    return bone


def set_roll_values(edit_bones, bone_roll_mapping):
    for bone_name, roll_value in bone_roll_mapping.items():
        if bone_name in edit_bones:
            edit_bones[bone_name].roll = radians(roll_value)


def find_nearest_deform_bone(armature, target_bone, exclude_names=None):
    """找到与 target_bone 空间上最近的已有 deform 骨骼（排除 exclude_names 中的骨骼）"""
    if exclude_names is None:
        exclude_names = set()
    target_center = (target_bone.head_local + target_bone.tail_local) / 2
    nearest = None
    nearest_dist = float('inf')
    for bone in armature.data.bones:
        if bone.name in exclude_names:
            continue
        if not bone.use_deform:
            continue
        center = (bone.head_local + bone.tail_local) / 2
        dist = (center - target_center).length
        if dist < nearest_dist:
            nearest_dist = dist
            nearest = bone
    return nearest


def copy_vertex_group_weights(mesh_obj, src_name, dst_name):
    """把 src_name 顶点组的权重复制到 dst_name 顶点组，返回受影响的顶点数"""
    src_vg = mesh_obj.vertex_groups.get(src_name)
    if not src_vg:
        return 0
    dst_vg = mesh_obj.vertex_groups.get(dst_name) or mesh_obj.vertex_groups.new(name=dst_name)
    count = 0
    for v in mesh_obj.data.vertices:
        for g in v.groups:
            if g.group == src_vg.index and g.weight > 0:
                dst_vg.add([v.index], g.weight, 'REPLACE')
                count += 1
                break
    return count


def transfer_weights_for_new_bones(armature, mesh_objects, new_bone_names, existing_vgroup_names):
    """
    对 new_bone_names 中的每个新 deform 骨骼，从最近的已有骨骼复制权重。
    返回日志列表，每条格式：(新骨骼名, 源骨骼名或None, 网格数, 顶点数, 备注)
    """
    log = []
    for bone_name in new_bone_names:
        bone = armature.data.bones.get(bone_name)
        if not bone:
            log.append((bone_name, None, 0, 0, "骨骼不存在"))
            continue
        if not bone.use_deform:
            log.append((bone_name, None, 0, 0, "跳过 (use_deform=False)"))
            continue

        # 找最近的已有 deform 骨骼（排除自身）
        nearest = find_nearest_deform_bone(armature, bone, exclude_names={bone_name})
        if not nearest:
            log.append((bone_name, None, 0, 0, "未找到可用源骨骼"))
            continue

        # 检查源骨骼在任何 mesh 上是否有实际权重
        src_has_weight = any(
            mesh.vertex_groups.get(nearest.name) is not None
            for mesh in mesh_objects
        )
        if not src_has_weight:
            log.append((bone_name, nearest.name, 0, 0, "警告: 源权重为空"))
            continue

        # 逐 mesh 复制权重
        total_verts = 0
        mesh_count = 0
        for mesh in mesh_objects:
            n = copy_vertex_group_weights(mesh, nearest.name, bone_name)
            if n > 0:
                total_verts += n
                mesh_count += 1
        log.append((bone_name, nearest.name, mesh_count, total_verts, ""))

    return log


def apply_armature_transforms(context):
    """自动应用骨架的旋转和缩放变换"""
    try:
        # 确保在对象模式
        bpy.ops.object.mode_set(mode='OBJECT')
        
        # 应用变换
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
        return True
    except Exception as e:
        print(f"Failed to apply armature transforms: {str(e)}")
        return False
