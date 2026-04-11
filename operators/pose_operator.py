import bpy
import math
from mathutils import Matrix, Vector
from ..bone_utils import apply_armature_transforms
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


class OBJECT_OT_fix_forearm_bend(bpy.types.Operator):
    """可选修正: 把小手臂(ひじ→手首) 拉直到与上臂共线, 然后烘焙到 rest pose。
    用于 XPS 源模型 rest 姿态下前腕弯曲导致 VMD 播放时 腕.L.tail / 腕捩.L.tail /
    ひじ.L.head 三点漂移的情况。独立可选, 不影响主流程, 任何时候都可单独运行。"""
    bl_idname = "object.fix_forearm_bend"
    bl_label = "可选: 修正前腕弯曲"
    bl_description = "把小手臂拉直到与上臂共线, 烘焙为新的 rest pose (建议在流程最开始运行)"

    ANGLE_THRESHOLD_DEG = 2.0

    def _find_arm_chain(self, obj, side):
        xps_side = "left" if side == "L" else "right"
        candidates = [
            (f"arm {xps_side} shoulder 2", f"arm {xps_side} elbow", f"arm {xps_side} wrist"),
            (f"腕.{side}", f"ひじ.{side}", f"手首.{side}"),
        ]
        for u, e, w in candidates:
            if u in obj.pose.bones and e in obj.pose.bones and w in obj.pose.bones:
                return u, e, w
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

        # 1. 计算每侧需要的旋转 (世界空间, 绕肘关节 head)
        plans = []
        for side in ("L", "R"):
            chain = self._find_arm_chain(obj, side)
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
            pivot = e_head.copy()
            plans.append((e_name, pivot, axis, angle, side))
            print(f"[CTMMD fix-forearm] {side}: {e_name} 需旋转 {math.degrees(angle):.2f}° 拉直")

        if not plans:
            self.report({'INFO'}, "前腕已接近直线或未找到骨骼, 无需修正")
            return {'FINISHED'}

        # 2. 为所有绑定该骨架的无 shape-key 网格复制一份 armature modifier
        #    (与 convert_to_apose 同一套把 pose 烘焙到 mesh 的机制)
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
                self.report({'ERROR'}, f"创建临时网格失败: {e}")
                return {'CANCELLED'}

        for m in meshes_with_arm:
            for mod in list(m.modifiers):
                if mod.type == 'ARMATURE' and mod.object == obj and "_copy" not in mod.name:
                    new_mod = m.modifiers.new(name=mod.name + "_copy", type='ARMATURE')
                    new_mod.object = mod.object
                    new_mod.use_vertex_groups = mod.use_vertex_groups
                    new_mod.use_bone_envelopes = mod.use_bone_envelopes
                    break

        # 3. 切到 pose 模式并清除已有 pose
        context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode='POSE')
        bpy.ops.pose.select_all(action='SELECT')
        bpy.ops.pose.rot_clear()
        bpy.ops.pose.scale_clear()
        bpy.ops.pose.loc_clear()
        bpy.ops.pose.select_all(action='DESELECT')

        # 4. 对每个 elbow bone 应用 "绕肘关节 head 的旋转"
        for bone_name, pivot, axis, angle, side in plans:
            pb = obj.pose.bones[bone_name]
            rot_w = Matrix.Rotation(angle, 4, axis)
            to_origin = Matrix.Translation(-pivot)
            from_origin = Matrix.Translation(pivot)
            delta = from_origin @ rot_w @ to_origin
            pb.matrix = delta @ pb.matrix
            context.view_layer.update()

        # 5. 把复制的 modifier 烘焙到 mesh, 让 mesh 跟随 rest 变化
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
            self.report({'ERROR'}, f"应用 modifier 失败: {e}")
            return {'CANCELLED'}

        # 6. 回到骨架, 把当前 pose apply 为新的 rest pose
        context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode='POSE')
        bpy.ops.pose.select_all(action='SELECT')
        bpy.ops.pose.armature_apply()
        bpy.ops.object.mode_set(mode='OBJECT')

        # 7. 清理临时网格
        if created_temp:
            for m in meshes_with_arm:
                if m.get("is_temp_mesh"):
                    bpy.data.objects.remove(m, do_unlink=True)

        self.report({'INFO'}, f"前腕弯曲修正完成 ({len(plans)} 处已烘焙到 rest pose)")
        return {'FINISHED'}
