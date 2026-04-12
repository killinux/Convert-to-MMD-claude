import bpy
import json
import math
import os
from mathutils import Matrix, Vector
from ..bone_utils import apply_armature_transforms


_CANONICAL_CACHE = None


def _load_canonical_arm_dirs():
    """Read bundled presets/canonical_arm_dirs.json and return {side: (upper, fore)}
    with unit Vectors in armature-local space. Cached on first access."""
    global _CANONICAL_CACHE
    if _CANONICAL_CACHE is not None:
        return _CANONICAL_CACHE
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(here, "presets", "canonical_arm_dirs.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        result = {}
        for side in ("L", "R"):
            arm = data["arms"][side]
            result[side] = (
                Vector(arm["upper_dir"]).normalized(),
                Vector(arm["fore_dir"]).normalized(),
            )
        _CANONICAL_CACHE = result
        return result
    except Exception as e:
        print(f"[CTMMD canonical] 读取 {path} 失败: {e}")
        return None
# 新增的T-Pose到A-Pose转换操作符
class OBJECT_OT_convert_to_apose(bpy.types.Operator):
    """将骨架转换为 A-Pose 并应用为新的静置姿态"""
    bl_idname = "object.convert_to_apose" 
    bl_label = "Convert to A-Pose"

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "No armature object selected")
            return {'CANCELLED'}
        if not apply_armature_transforms(context):
            self.report({'ERROR'}, "Failed to apply armature transforms")
            return {'CANCELLED'}
        scene = context.scene
        
        # 获取骨骼名称
        arm_bones = {
            "left_upper_arm": getattr(scene, "left_upper_arm_bone", ""),
            "right_upper_arm": getattr(scene, "right_upper_arm_bone", ""),
        }

        # 检查是否有设置骨骼
        if not any(arm_bones.values()):
            self.report({'ERROR'}, "Configure the target bones in the UI first")
            return {'CANCELLED'}

        # 1. 确保在对象模式
        bpy.ops.object.mode_set(mode='OBJECT')

        # 2. 找到所有使用这个骨骼的网格对象，并检查形态键
        meshes_with_armature = []
        for mesh_obj in bpy.data.objects:
            if mesh_obj.type == 'MESH':
                for modifier in mesh_obj.modifiers:
                    if modifier.type == 'ARMATURE' and modifier.object == obj:
                        # 检查是否有形态键
                        if not mesh_obj.data.shape_keys:
                            meshes_with_armature.append(mesh_obj)
                        break

        # 检查是否找到可用的网格
        if not meshes_with_armature:
            # 创建临时测试网格
            try:
                bpy.ops.mesh.primitive_cube_add(size=0.5)
                temp_mesh = context.active_object
                temp_mesh.name = "CTMMD_TEMP_MESH"
                
                # 添加骨架修改器
                modifier = temp_mesh.modifiers.new(name="Armature", type='ARMATURE')
                modifier.object = obj
                
                # 添加到可用网格列表
                meshes_with_armature.append(temp_mesh)
                
                # 标记为临时网格
                temp_mesh["is_temp_mesh"] = True
                
            except Exception as e:
                self.report({'ERROR'}, f"Failed to create temporary mesh: {str(e)}")
                return {'CANCELLED'}

        # 3. 为每个网格复制骨骼修改器，但保留原始修改器
        for mesh_obj in meshes_with_armature:
            for modifier in mesh_obj.modifiers:
                if modifier.type == 'ARMATURE' and modifier.object == obj:
                    # 复制修改器
                    new_modifier = mesh_obj.modifiers.new(name=modifier.name + "_copy", type='ARMATURE')
                    new_modifier.object = modifier.object
                    new_modifier.use_vertex_groups = modifier.use_vertex_groups
                    new_modifier.use_bone_envelopes = modifier.use_bone_envelopes
                    break

        # 4. 切换到姿态模式设置A-Pose
        context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode='POSE')

        # 5. 清除所有现有姿态
        bpy.ops.pose.select_all(action='SELECT')
        bpy.ops.pose.rot_clear()
        bpy.ops.pose.scale_clear()
        bpy.ops.pose.loc_clear()
        bpy.ops.pose.select_all(action='DESELECT')

        # 6. 为骨骼设置A-Pose旋转
        pose_bones = obj.pose.bones
        converted_bones = []

        for bone_type, bone_name in arm_bones.items():
            if bone_name and bone_name in pose_bones:
                bone = pose_bones[bone_name]
                bone.rotation_mode = 'XYZ'
                
                # 根据骨骼类型设置不同的旋转角度
                if bone_type == "left_upper_arm":
                    rotation_matrix = Matrix.Rotation(math.radians(37), 4, 'Y')
                elif bone_type == "right_upper_arm":
                    rotation_matrix = Matrix.Rotation(math.radians(-37), 4, 'Y')
                
                # 应用旋转矩阵
                bone.matrix = rotation_matrix @ bone.matrix
                
                converted_bones.append(bone_name)

        if not converted_bones:
            self.report({'WARNING'}, "No matching bones found for conversion")
            return {'CANCELLED'}

        # 7. 更新视图以确保姿态已应用
        context.view_layer.update()

        # 8. 应用第二个修改器（复制的修改器）来调整网格姿态
        try:
            for mesh_obj in meshes_with_armature:
                context.view_layer.objects.active = mesh_obj
                for modifier in mesh_obj.modifiers:
                    if modifier.type == 'ARMATURE' and modifier.object == obj and "_copy" in modifier.name:
                        bpy.ops.object.modifier_apply(modifier=modifier.name)
                        break
        except RuntimeError as e:
            # 清理残留的 _copy 修改器
            for mesh_obj in meshes_with_armature:
                for modifier in list(mesh_obj.modifiers):
                    if "_copy" in modifier.name:
                        mesh_obj.modifiers.remove(modifier)
            self.report({'ERROR'}, f"Error while applying modifier: {str(e)}")
            return {'CANCELLED'}

        # 9. 切换回骨骼对象
        context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode='POSE')

        # 10. 应用当前姿态为新的静置姿态
        bpy.ops.pose.armature_apply()

        # 11. 清理临时创建的网格
        for mesh_obj in meshes_with_armature:
            if mesh_obj.get("is_temp_mesh"):
                bpy.data.objects.remove(mesh_obj, do_unlink=True)

        self.report({'INFO'}, "A-pose conversion finished and was applied as the new rest pose")
        return {'FINISHED'}


def _find_arm_chain(obj, side):
    """Return (shoulder_bone, elbow_bone, wrist_bone) name tuple by trying
    XPS ('arm left/right shoulder 2/elbow/wrist') then MMD (腕/ひじ/手首 .L/.R).
    Returns None if not found."""
    xps_side = "left" if side == "L" else "right"
    candidates = [
        (f"arm {xps_side} shoulder 2", f"arm {xps_side} elbow", f"arm {xps_side} wrist"),
        (f"腕.{side}", f"ひじ.{side}", f"手首.{side}"),
    ]
    for u, e, w in candidates:
        if u in obj.pose.bones and e in obj.pose.bones and w in obj.pose.bones:
            return u, e, w
    return None


def _get_wrist_dir(obj, side):
    """Return wrist bone direction (head→tail) as armature-local unit Vector,
    or None if wrist bone not found."""
    for name in (f"手首.{side}", f"arm {'left' if side == 'L' else 'right'} wrist"):
        b = obj.data.bones.get(name)
        if b:
            d = b.tail_local - b.head_local
            if d.length > 1e-6:
                return d.normalized()
    return None


def _bake_pose_delta_to_rest(context, obj, plans, log_tag):
    """Apply a list of (bone_name, pivot_world, axis_world, angle_rad) rotations
    to obj in pose mode and bake as new rest pose (mesh follows via duplicated
    armature modifier). Returns 'FINISHED' or 'CANCELLED'."""
    if not plans:
        return 'FINISHED'

    meshes_with_arm = []
    for m in bpy.data.objects:
        if m.type != 'MESH' or m.data.shape_keys:
            continue
        for mod in m.modifiers:
            if mod.type == 'ARMATURE' and mod.object == obj:
                meshes_with_arm.append(m)
                break

    created_temp = False
    if not meshes_with_arm:
        try:
            bpy.ops.mesh.primitive_cube_add(size=0.5)
            tmp = context.active_object
            tmp.name = "CTMMD_TEMP_MESH_FIX"
            mod = tmp.modifiers.new(name="Armature", type='ARMATURE')
            mod.object = obj
            tmp["is_temp_mesh"] = True
            meshes_with_arm.append(tmp)
            created_temp = True
        except Exception as e:
            print(f"[{log_tag}] 创建临时网格失败: {e}")
            return 'CANCELLED'

    for m in meshes_with_arm:
        for mod in list(m.modifiers):
            if mod.type == 'ARMATURE' and mod.object == obj and "_copy" not in mod.name:
                new_mod = m.modifiers.new(name=mod.name + "_copy", type='ARMATURE')
                new_mod.object = mod.object
                new_mod.use_vertex_groups = mod.use_vertex_groups
                new_mod.use_bone_envelopes = mod.use_bone_envelopes
                break

    context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode='POSE')
    bpy.ops.pose.select_all(action='SELECT')
    bpy.ops.pose.rot_clear()
    bpy.ops.pose.scale_clear()
    bpy.ops.pose.loc_clear()
    bpy.ops.pose.select_all(action='DESELECT')

    for bone_name, pivot, axis, angle in plans:
        pb = obj.pose.bones[bone_name]
        rot_w = Matrix.Rotation(angle, 4, axis)
        delta = Matrix.Translation(pivot) @ rot_w @ Matrix.Translation(-pivot)
        pb.matrix = delta @ pb.matrix
        context.view_layer.update()

    try:
        for m in meshes_with_arm:
            context.view_layer.objects.active = m
            for mod in list(m.modifiers):
                if mod.type == 'ARMATURE' and mod.object == obj and "_copy" in mod.name:
                    bpy.ops.object.modifier_apply(modifier=mod.name)
                    break
    except RuntimeError as e:
        for m in meshes_with_arm:
            for mod in list(m.modifiers):
                if "_copy" in mod.name:
                    m.modifiers.remove(mod)
        print(f"[{log_tag}] 应用 modifier 失败: {e}")
        return 'CANCELLED'

    context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode='POSE')
    bpy.ops.pose.select_all(action='SELECT')
    bpy.ops.pose.armature_apply()
    bpy.ops.object.mode_set(mode='OBJECT')

    if created_temp:
        for m in meshes_with_arm:
            if m.get("is_temp_mesh"):
                bpy.data.objects.remove(m, do_unlink=True)

    return 'FINISHED'


class OBJECT_OT_fix_forearm_bend(bpy.types.Operator):
    """可选修正: 把小手臂(ひじ→手首) 拉直到与上臂共线, 然后烘焙到 rest pose。
    用于 XPS 源模型 rest 姿态下前腕弯曲导致 VMD 播放时 腕.L.tail / 腕捩.L.tail /
    ひじ.L.head 三点漂移的情况。独立可选, 不影响主流程, 任何时候都可单独运行。"""
    bl_idname = "object.fix_forearm_bend"
    bl_label = "可选: 修正前腕弯曲"
    bl_description = "把小手臂拉直到与上臂共线, 烘焙为新的 rest pose (建议在流程最开始运行)"

    ANGLE_THRESHOLD_DEG = 2.0

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "请先选中骨架")
            return {'CANCELLED'}
        if not apply_armature_transforms(context):
            self.report({'ERROR'}, "apply_armature_transforms 失败")
            return {'CANCELLED'}
        bpy.ops.object.mode_set(mode='OBJECT')

        plans = []
        for side in ("L", "R"):
            chain = _find_arm_chain(obj, side)
            if not chain:
                continue
            u_name, e_name, w_name = chain
            u_head = obj.matrix_world @ obj.pose.bones[u_name].head
            e_head = obj.matrix_world @ obj.pose.bones[e_name].head
            w_head = obj.matrix_world @ obj.pose.bones[w_name].head
            upper_dir = (e_head - u_head).normalized()
            fore_dir = (w_head - e_head).normalized()
            if upper_dir.length == 0 or fore_dir.length == 0:
                continue
            angle = upper_dir.angle(fore_dir)
            if angle < math.radians(self.ANGLE_THRESHOLD_DEG):
                print(f"[CTMMD fix-forearm] {side}: 已接近共线 ({math.degrees(angle):.2f}°), 跳过")
                continue
            axis = fore_dir.cross(upper_dir)
            if axis.length < 1e-6:
                continue
            axis.normalize()
            plans.append((e_name, e_head.copy(), axis, angle))
            print(f"[CTMMD fix-forearm] {side}: {e_name} 需旋转 {math.degrees(angle):.2f}° 拉直")

        if not plans:
            self.report({'INFO'}, "前腕已接近直线或未找到骨骼, 无需修正")
            return {'FINISHED'}

        result = _bake_pose_delta_to_rest(context, obj, plans, "CTMMD fix-forearm")
        if result != 'FINISHED':
            self.report({'ERROR'}, "烘焙到 rest pose 失败")
            return {'CANCELLED'}
        self.report({'INFO'}, f"前腕弯曲修正完成 ({len(plans)} 处已烘焙到 rest pose)")
        return {'FINISHED'}


class OBJECT_OT_align_arms_to_reference(bpy.types.Operator):
    """可选修正: 把 active 骨架的上臂 + 前腕方向对齐到参考方向, 消除因 rest 臂方向
    与 target 差异导致的 VMD 回放偏移。优先使用 scene 中另一个含 腕.L/R 的 armature
    (比如导入的 target PMX) 作为参考; 找不到则 fallback 到 bundled 的 canonical
    rest 方向 (presets/canonical_arm_dirs.json, 来自 Purifier Inase 18)。
    执行后烘焙到 active 骨架的 rest pose。"""
    bl_idname = "object.align_arms_to_reference"
    bl_label = "可选: 对齐手臂到参考骨架"
    bl_description = "把 active 骨架上臂/前腕方向对齐到参考 (scene 中其他 armature 或内置 canonical), 烘焙为新 rest pose"

    ANGLE_THRESHOLD_DEG = 0.5

    def _find_reference(self, active):
        """Return (name, {side: (upper_dir, fore_dir, wrist_dir_or_None)}) or None."""
        for o in bpy.data.objects:
            if o.type != 'ARMATURE' or o is active:
                continue
            if _find_arm_chain(o, "L") and _find_arm_chain(o, "R"):
                dirs = {}
                ok = True
                for side in ("L", "R"):
                    u, e, w = _find_arm_chain(o, side)
                    uh = o.data.bones[u].head_local
                    eh = o.data.bones[e].head_local
                    wh = o.data.bones[w].head_local
                    upper = (eh - uh)
                    fore = (wh - eh)
                    if upper.length < 1e-6 or fore.length < 1e-6:
                        ok = False
                        break
                    wrist_dir = _get_wrist_dir(o, side)
                    dirs[side] = (upper.normalized(), fore.normalized(), wrist_dir)
                if ok:
                    return (f"scene:{o.name}", dirs)
        # fallback: canonical preset
        canon = _load_canonical_arm_dirs()
        if canon:
            # canonical doesn't have wrist_dir, pad with None
            padded = {s: (u, f, None) for s, (u, f) in canon.items()}
            return ("canonical:MMD standard A-pose", padded)
        return None

    def _build_plan(self, obj, side, ref_upper_dir, ref_fore_dir, ref_wrist_dir=None):
        """Returns list of (bone_name, pivot_world, axis_world, angle_rad)
        aligning conv upper arm to ref_upper_dir, then forearm to ref_fore_dir,
        then optionally wrist to ref_wrist_dir.
        ref_*_dir are unit Vectors in armature-local space; we compare against
        conv's armature-local directions (works because active armature has
        transforms applied → matrix_world ≈ identity)."""
        plans = []
        u, e, w = _find_arm_chain(obj, side)
        conv_u = obj.data.bones[u].head_local.copy()
        conv_e = obj.data.bones[e].head_local.copy()
        conv_w = obj.data.bones[w].head_local.copy()

        dir_conv_upper = (conv_e - conv_u).normalized()
        upper_angle = dir_conv_upper.angle(ref_upper_dir)
        upper_axis = None
        upper_angle_valid = upper_angle >= math.radians(self.ANGLE_THRESHOLD_DEG)
        if upper_angle_valid:
            upper_axis = dir_conv_upper.cross(ref_upper_dir)
            if upper_axis.length < 1e-6:
                upper_angle_valid = False
            else:
                upper_axis.normalize()
                plans.append((u, conv_u.copy(), upper_axis, upper_angle))
                print(f"[CTMMD align-ref] {side}: upper arm {u} 旋转 {math.degrees(upper_angle):.2f}°")

        # predict conv_e / conv_w after upper rotation
        if upper_angle_valid:
            R = Matrix.Rotation(upper_angle, 3, upper_axis)
            conv_e_new = conv_u + R @ (conv_e - conv_u)
            conv_w_new = conv_u + R @ (conv_w - conv_u)
        else:
            conv_e_new = conv_e
            conv_w_new = conv_w

        dir_conv_fore = (conv_w_new - conv_e_new).normalized()
        fore_angle = dir_conv_fore.angle(ref_fore_dir)
        fore_axis = None
        fore_angle_valid = fore_angle >= math.radians(self.ANGLE_THRESHOLD_DEG)
        if fore_angle_valid:
            fore_axis = dir_conv_fore.cross(ref_fore_dir)
            if fore_axis.length > 1e-6:
                fore_axis.normalize()
                plans.append((e, conv_e_new.copy(), fore_axis, fore_angle))
                print(f"[CTMMD align-ref] {side}: forearm {e} 旋转 {math.degrees(fore_angle):.2f}°")
            else:
                fore_angle_valid = False

        # wrist direction alignment (hand orientation)
        if ref_wrist_dir is not None:
            conv_wrist_dir = _get_wrist_dir(obj, side)
            if conv_wrist_dir is not None:
                # predict wrist dir after previous rotations
                if fore_angle_valid:
                    R2 = Matrix.Rotation(fore_angle, 3, fore_axis)
                    conv_wrist_dir = (R2 @ conv_wrist_dir).normalized()
                if upper_angle_valid:
                    R1 = Matrix.Rotation(upper_angle, 3, upper_axis)
                    conv_wrist_dir = (R1 @ conv_wrist_dir).normalized()
                # predict conv_w after both rotations
                if fore_angle_valid:
                    R2 = Matrix.Rotation(fore_angle, 3, fore_axis)
                    conv_w_final = conv_e_new + R2 @ (conv_w_new - conv_e_new)
                else:
                    conv_w_final = conv_w_new

                wrist_angle = conv_wrist_dir.angle(ref_wrist_dir)
                if wrist_angle >= math.radians(self.ANGLE_THRESHOLD_DEG):
                    wrist_axis = conv_wrist_dir.cross(ref_wrist_dir)
                    if wrist_axis.length > 1e-6:
                        wrist_axis.normalize()
                        plans.append((w, conv_w_final.copy(), wrist_axis, wrist_angle))
                        print(f"[CTMMD align-ref] {side}: wrist {w} 旋转 {math.degrees(wrist_angle):.2f}°")

        return plans

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "请先选中要修正的骨架(active)")
            return {'CANCELLED'}
        if not apply_armature_transforms(context):
            self.report({'ERROR'}, "apply_armature_transforms 失败")
            return {'CANCELLED'}
        bpy.ops.object.mode_set(mode='OBJECT')

        ref_info = self._find_reference(obj)
        if not ref_info:
            self.report({'ERROR'}, "未找到参考骨架, 且 bundled canonical 预设读取失败")
            return {'CANCELLED'}
        ref_name, ref_dirs = ref_info
        print(f"[CTMMD align-ref] active={obj.name}  reference={ref_name}")

        all_plans = []
        for side in ("L", "R"):
            if not _find_arm_chain(obj, side):
                continue
            if side not in ref_dirs:
                continue
            ref_upper, ref_fore, ref_wrist = ref_dirs[side]
            all_plans.extend(self._build_plan(obj, side, ref_upper, ref_fore, ref_wrist))

        if not all_plans:
            self.report({'INFO'}, f"已接近参考 (<{self.ANGLE_THRESHOLD_DEG}°), 无需修正")
            return {'FINISHED'}

        result = _bake_pose_delta_to_rest(context, obj, all_plans, "CTMMD align-ref")
        if result != 'FINISHED':
            self.report({'ERROR'}, "烘焙到 rest pose 失败")
            return {'CANCELLED'}
        self.report({'INFO'}, f"手臂对齐完成 ({len(all_plans)} 处), 参考: {ref_name}")
        return {'FINISHED'}


# MMD 手指骨名: (根骨, 第1節, 第2節, 第3節)
_FINGER_CHAINS = [
    ("親指０", "親指１", "親指２"),
    ("人指１", "人指２", "人指３"),
    ("中指１", "中指２", "中指３"),
    ("薬指１", "薬指２", "薬指３"),
    ("小指１", "小指２", "小指３"),
]


class OBJECT_OT_align_fingers_to_reference(bpy.types.Operator):
    """可選修正: 把 active 骨架的手指方向対齐到 scene 中的参考骨架。
    每根手指的第一段 (指１) 方向対齐到参考, 烘焙到 rest pose。"""
    bl_idname = "object.align_fingers_to_reference"
    bl_label = "可選: 対齐手指到参考骨架"
    bl_description = "把手指方向対齐到参考骨架, 烘焙为新 rest pose"

    ANGLE_THRESHOLD_DEG = 1.0

    def _find_ref_armature(self, active):
        """Find another armature in scene that has MMD finger bones."""
        for o in bpy.data.objects:
            if o.type != 'ARMATURE' or o is active:
                continue
            if o.data.bones.get("人指１.L") and o.data.bones.get("人指１.R"):
                return o
        return None

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "请先选中骨架")
            return {'CANCELLED'}
        if not apply_armature_transforms(context):
            self.report({'ERROR'}, "apply_armature_transforms 失败")
            return {'CANCELLED'}
        bpy.ops.object.mode_set(mode='OBJECT')

        ref = self._find_ref_armature(obj)
        if not ref:
            self.report({'ERROR'}, "未找到含手指骨的参考骨架")
            return {'CANCELLED'}
        print(f"[CTMMD align-fingers] active={obj.name}  reference={ref.name}")

        plans = []
        for side in ("L", "R"):
            for chain in _FINGER_CHAINS:
                # 只对齐第一段方向 (根 → 第1節)
                root_name = f"{chain[0]}.{side}"
                tip_name = f"{chain[1]}.{side}"

                conv_root = obj.data.bones.get(root_name)
                conv_tip = obj.data.bones.get(tip_name)
                ref_root = ref.data.bones.get(root_name)
                ref_tip = ref.data.bones.get(tip_name)

                if not all([conv_root, conv_tip, ref_root, ref_tip]):
                    continue

                conv_dir = (conv_tip.head_local - conv_root.head_local)
                ref_dir = (ref_tip.head_local - ref_root.head_local)
                if conv_dir.length < 1e-6 or ref_dir.length < 1e-6:
                    continue
                conv_dir = conv_dir.normalized()
                ref_dir = ref_dir.normalized()

                angle = conv_dir.angle(ref_dir)
                if angle < math.radians(self.ANGLE_THRESHOLD_DEG):
                    continue

                axis = conv_dir.cross(ref_dir)
                if axis.length < 1e-6:
                    continue
                axis.normalize()

                pivot = conv_root.head_local.copy()
                plans.append((root_name, pivot, axis, angle))
                print(f"[CTMMD align-fingers] {side}: {root_name} 旋转 {math.degrees(angle):.2f}°")

        if not plans:
            self.report({'INFO'}, "手指方向已接近参考, 无需修正")
            return {'FINISHED'}

        result = _bake_pose_delta_to_rest(context, obj, plans, "CTMMD align-fingers")
        if result != 'FINISHED':
            self.report({'ERROR'}, "烘焙到 rest pose 失败")
            return {'CANCELLED'}
        self.report({'INFO'}, f"手指对齐完成 ({len(plans)} 处)")
        return {'FINISHED'}
