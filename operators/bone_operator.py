import bpy
from mathutils import Vector
from .. import bone_map_and_group
from .. import bone_utils
from .. import preset_operator

class OBJECT_OT_rename_to_mmd(bpy.types.Operator):
    """将选定的骨骼重命名为 MMD 格式"""
    bl_idname = "object.rename_to_mmd"
    bl_label = "Rename to MMD"

    mmd_bone_map = bone_map_and_group.mmd_bone_map  # 使用导入的bone_map模块

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "No armature object selected")
            return {'CANCELLED'}

        scene = context.scene
        # 检查选择框里是否有骨骼设置
        has_bone_set = False
        for prop_name in preset_operator.get_bones_list():
            if getattr(scene, prop_name, None):
                has_bone_set = True
                break
        if not has_bone_set:
            self.report({'WARNING'}, "No mapped bones were set in the UI")
            return {'CANCELLED'}

        print("[CTMMD 1] ===== Step 1: Rename Bones =====")
        renamed = []
        already = []
        missing = []
        for prop_name, new_name in self.mmd_bone_map.items():
            bone_name = getattr(scene, prop_name, None)
            if not bone_name:
                continue
            bone = obj.pose.bones.get(bone_name)
            if bone:
                if bone.name != new_name:
                    bone.name = new_name
                    setattr(scene, prop_name, new_name)
                    renamed.append(f"{bone_name} -> {new_name}")
                else:
                    already.append(new_name)
            else:
                missing.append(f"{bone_name} -> {new_name}")

        for r in renamed:
            print(f"[CTMMD 1]   Renamed: {r}")
        for a in already:
            print(f"[CTMMD 1]   Already MMD: {a}")
        for m in missing:
            print(f"[CTMMD 1]   [WARN] Missing bone: {m}")
        print(f"[CTMMD 1] Done: renamed {len(renamed)}, already MMD {len(already)}, missing {len(missing)}")

        # 打开骨骼名称显示
        bpy.context.object.data.show_names = True

        return {'FINISHED'}

    def rename_finger_bone(self, context, obj, scene, base_finger_name, segment):
        for side in ["left", "right"]:
            prop_name = f"{side}_{base_finger_name}_{segment}"
            if prop_name in self.mmd_bone_map:
                new_name = self.mmd_bone_map.get(prop_name)
                bone_name = getattr(scene, prop_name, None)
                if bone_name:
                    bone = obj.pose.bones.get(bone_name)
                    if bone:
                        # Check if the bone has already been renamed to the MMD format name
                        if bone.name != new_name:
                            bone.name = new_name
                            # Update the bone property value in the scene
                            setattr(scene, prop_name, new_name)
                        else:
                            self.report({'INFO'}, f"Bone '{bone_name}' is already renamed to {new_name}")
                    else:
                        self.report({'WARNING'}, f"Bone '{bone_name}' not found for renaming to {new_name}")

class OBJECT_OT_complete_missing_bones(bpy.types.Operator):
    """补充缺失的 MMD 格式骨骼"""
    bl_idname = "object.complete_missing_bones"
    bl_label = "Complete Missing Bones"

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "No armature selected")
            return {'CANCELLED'}

        # 记录现有顶点组（用于后续判断哪些骨骼是新建的）
        mesh_objects = [
            o for o in bpy.data.objects
            if o.type == 'MESH' and any(
                m.type == 'ARMATURE' and m.object == obj
                for m in o.modifiers
            )
        ]
        existing_vgroups = {
            o: {vg.name for vg in o.vertex_groups}
            for o in mesh_objects
        }

        # 确保当前处于编辑模式 (EDIT mode)
        if context.mode != 'EDIT_ARMATURE':
            bpy.ops.object.mode_set(mode='EDIT')
        
        edit_bones = obj.data.edit_bones
        # 获取需要修改的骨骼
        left_foot_bone = edit_bones.get("足.L")
        right_foot_bone = edit_bones.get("足.R")
        upper_body_bone = edit_bones.get("上半身")
        lower_body_bone = edit_bones.get("下半身")
        # 清除 足.L 和 足.R 骨骼的父级
        if left_foot_bone:
            left_foot_bone.use_connect = False
            left_foot_bone.parent = None
        if right_foot_bone:
            right_foot_bone.use_connect = False
            right_foot_bone.parent = None
        # 清除 上半身 骨骼的父级
        if upper_body_bone and upper_body_bone.parent:
            upper_body_bone.use_connect = False
            upper_body_bone.parent = None
        # 清除 下半身 骨骼的父级
        if lower_body_bone and lower_body_bone.parent:
            lower_body_bone.use_connect = False
            lower_body_bone.parent = None
        # 确认上半身骨骼存在
        if not upper_body_bone:
            self.report({'ERROR'}, "Upper body bone not found")
            return {'CANCELLED'}
        # 获取 上半身 骨骼的坐标
        upper_body_head = upper_body_bone.head.copy()
        upper_body_tail = upper_body_bone.tail.copy()

        # 提前读取上半身链各骨骼（edit模式下读取原始位置）
        upper1_bone = edit_bones.get("上半身1")
        upper2_bone = edit_bones.get("上半身2")
        neck_bone = edit_bones.get("首")
        head_bone = edit_bones.get("頭")

        # 上半身 tail 指向上半身1的原始 head（保持 XPS 原始关节位置不变）
        upper_tail_z = upper1_bone.head.z if upper1_bone else upper_body_head.z + 0.15

        # 计算上半身3的位置：
        # head 对齐到上半身2的 tail，tail 对齐到首的 head，保持骨骼链连续
        if upper2_bone and neck_bone:
            upper3_head = Vector((0, upper2_bone.tail.y, upper2_bone.tail.z))  # head → 上半身2 tail
            upper3_tail = Vector((0, neck_bone.head.y, neck_bone.head.z))       # tail → 首 head
        else:
            upper3_head = Vector((0, upper_body_head.y, upper_body_head.z + 0.30))
            upper3_tail = Vector((0, upper_body_head.y, upper_body_head.z + 0.45))

        # 首1 位置：插入首和頭之间，确保非零长度
        if neck_bone and head_bone:
            neck_head_pos = neck_bone.head.copy()
            head_head_pos = head_bone.head.copy()
            # 首1: head=首と頭の中間, tail=頭.head
            # 首: tail 缩短到中间点
            neck1_head = (neck_head_pos + head_head_pos) / 2
            neck1_tail = head_head_pos.copy()
            # 如果中间点和頭.head太近（<0.01），手动偏移
            if (neck1_tail - neck1_head).length < 0.01:
                neck1_head = Vector((0, head_head_pos.y, head_head_pos.z - 0.05))
                neck1_tail = head_head_pos.copy()
        elif neck_bone:
            neck1_head = neck_bone.tail.copy()
            neck1_tail = Vector((0, neck_bone.tail.y, neck_bone.tail.z + 0.08))
        else:
            neck1_head = Vector((0, upper_body_head.y, upper_body_head.z + 0.50))
            neck1_tail = Vector((0, upper_body_head.y, upper_body_head.z + 0.58))

        # 定义基本骨骼的属性
        bone_properties = {
            "操作中心": {"head": Vector((0, 0, 0)), "tail": Vector((0, 0, 0.15)), "parent": None, "use_deform": False, "use_connect": False},
            "全ての親": {"head": Vector((0, 0, 0)), "tail": Vector((0, 0, 0.3)), "parent": None, "use_deform": False, "use_connect": False},
            "センター": {"head": Vector((0, 0, 0.3)), "tail": Vector((0, 0, 0.6)), "parent": "全ての親", "use_deform": False, "use_connect": False},
            "グルーブ": {"head": Vector((0, 0, 0.8)), "tail": Vector((0, 0, 0.7)), "parent": "センター", "use_deform": False, "use_connect": False},
            "腰": {"head": Vector((0, upper_body_head.y + 0.1, upper_body_head.z - 0.12)), "tail": Vector((0, upper_body_head.y, upper_body_head.z)),
                "parent": "グルーブ", "use_deform": False, "use_connect": False},
            "上半身": {"head": Vector((0, upper_body_head.y, upper_body_head.z)),
                "tail": Vector((0, upper_body_head.y, upper_tail_z)),
                "parent": "腰", "use_connect": False},
            "上半身1": {
                "head": Vector((0, upper1_bone.head.y, upper1_bone.head.z)) if upper1_bone else Vector((0, upper_body_head.y, upper_body_head.z + 0.15)),
                "tail": Vector((0, upper2_bone.head.y, upper2_bone.head.z)) if upper2_bone else Vector((0, upper_body_head.y, upper_body_head.z + 0.20)),
                "parent": "上半身", "use_connect": False},
            "上半身2": {"head": Vector((0, upper2_bone.head.y, upper2_bone.head.z)) if upper2_bone else Vector((0, upper_body_head.y, upper_body_head.z+0.20)),
                "tail": Vector((0, upper2_bone.head.y, upper2_bone.head.z+0.15)) if upper2_bone else Vector((0, upper_body_head.y, upper_body_head.z+0.35)),
                "parent": "上半身1", "use_connect": False},
            "上半身3": {"head": upper3_head, "tail": upper3_tail, "parent": "上半身2", "use_connect": False, "use_deform": True},
            "首": {
                "head": edit_bones["首"].head.copy() if edit_bones.get("首") else Vector((0, upper_body_head.y, upper_body_head.z + 0.45)),
                "tail": neck1_head,
                "parent": "上半身3", "use_connect": False, "use_deform": True
            },
            # 上肢骨骼链（安全访问，缺失时跳过）
            "下半身": {"head": Vector((0, upper_body_head.y, upper_body_head.z)), "tail": Vector((0, upper_body_head.y, upper_body_head.z - 0.15)), "parent": "腰", "use_connect": False}
        }

        # 动态添加上肢骨骼（安全访问，缺失时跳过）
        limb_defs = [
            # 肩P.L/R: 肩的父骨骼，位置与肩相同，parent=上半身3
            ("肩P.L", ["肩.L"], lambda: {"head": edit_bones["肩.L"].head, "tail": edit_bones["肩.L"].head + Vector((0.03, 0, 0)), "parent": "上半身3", "use_deform": False, "use_connect": False}),
            ("肩P.R", ["肩.R"], lambda: {"head": edit_bones["肩.R"].head, "tail": edit_bones["肩.R"].head + Vector((-0.03, 0, 0)), "parent": "上半身3", "use_deform": False, "use_connect": False}),
            # 肩.L/R: parent 改为肩P
            ("肩.L",  ["肩.L", "腕.L"],  lambda: {"head": edit_bones["肩.L"].head, "tail": edit_bones["腕.L"].head, "parent": "肩P.L", "use_connect": False}),
            ("肩.R",  ["肩.R", "腕.R"],  lambda: {"head": edit_bones["肩.R"].head, "tail": edit_bones["腕.R"].head, "parent": "肩P.R", "use_connect": False}),
            # 肩C.L/R: 肩のキャンセル骨，位于肩tail=腕head
            ("肩C.L", ["肩.L", "腕.L"], lambda: {"head": edit_bones["腕.L"].head, "tail": edit_bones["腕.L"].head + (edit_bones["腕.L"].head - edit_bones["肩.L"].head).normalized() * 0.03, "parent": "肩.L", "use_deform": False, "use_connect": False}),
            ("肩C.R", ["肩.R", "腕.R"], lambda: {"head": edit_bones["腕.R"].head, "tail": edit_bones["腕.R"].head + (edit_bones["腕.R"].head - edit_bones["肩.R"].head).normalized() * 0.03, "parent": "肩.R", "use_deform": False, "use_connect": False}),
            # 腕: parent 改为肩C
            ("腕.L",  ["腕.L", "ひじ.L"], lambda: {"head": edit_bones["腕.L"].head, "tail": edit_bones["ひじ.L"].head, "parent": "肩C.L", "use_connect": True}),
            ("腕.R",  ["腕.R", "ひじ.R"], lambda: {"head": edit_bones["腕.R"].head, "tail": edit_bones["ひじ.R"].head, "parent": "肩C.R", "use_connect": True}),
            ("ひじ.L", ["ひじ.L"],         lambda: {"head": edit_bones["ひじ.L"].head, "tail": edit_bones.get("手首.L").head if edit_bones.get("手首.L") else edit_bones["ひじ.L"].tail, "parent": "腕.L", "use_connect": True}),
            ("ひじ.R", ["ひじ.R"],         lambda: {"head": edit_bones["ひじ.R"].head, "tail": edit_bones.get("手首.R").head if edit_bones.get("手首.R") else edit_bones["ひじ.R"].tail, "parent": "腕.R", "use_connect": True}),
            # 腰キャンセル骨：抵消下半身旋转，腿部骨骼挂在这下面
            ("腰キャンセル.L", ["足.L"], lambda: {"head": edit_bones["足.L"].head, "tail": Vector((edit_bones["足.L"].head.x, edit_bones["足.L"].head.y, edit_bones["足.L"].head.z + 0.05)), "parent": "下半身", "use_connect": False, "use_deform": False}),
            ("腰キャンセル.R", ["足.R"], lambda: {"head": edit_bones["足.R"].head, "tail": Vector((edit_bones["足.R"].head.x, edit_bones["足.R"].head.y, edit_bones["足.R"].head.z + 0.05)), "parent": "下半身", "use_connect": False, "use_deform": False}),
            # 腿部骨骼：parent 挂到腰キャンセル
            ("足.L",  ["足.L", "ひざ.L"],  lambda: {"head": edit_bones["足.L"].head, "tail": edit_bones["ひざ.L"].head, "parent": "腰キャンセル.L", "use_connect": False}),
            ("足.R",  ["足.R", "ひざ.R"],  lambda: {"head": edit_bones["足.R"].head, "tail": edit_bones["ひざ.R"].head, "parent": "腰キャンセル.R", "use_connect": False}),
            ("ひざ.L", ["ひざ.L", "足首.L"], lambda: {"head": edit_bones["ひざ.L"].head, "tail": edit_bones["足首.L"].head, "parent": "足.L", "use_connect": False}),
            ("ひざ.R", ["ひざ.R", "足首.R"], lambda: {"head": edit_bones["ひざ.R"].head, "tail": edit_bones["足首.R"].head, "parent": "足.R", "use_connect": False}),
            ("足首.L", ["足首.L"],           lambda: {"head": edit_bones["足首.L"].head, "tail": Vector((edit_bones["足首.L"].head.x, edit_bones["足首.L"].head.y - 0.1, 0)), "parent": "ひざ.L", "use_connect": False}),
            ("足首.R", ["足首.R"],           lambda: {"head": edit_bones["足首.R"].head, "tail": Vector((edit_bones["足首.R"].head.x, edit_bones["足首.R"].head.y - 0.1, 0)), "parent": "ひざ.R", "use_connect": False}),
        ]
        for bone_name, required, prop_fn in limb_defs:
            if all(edit_bones.get(r) for r in required):
                bone_properties[bone_name] = prop_fn()
            else:
                missing = [r for r in required if not edit_bones.get(r)]
                print(f"[CTMMD 2]   Skipped {bone_name}: missing {missing}")

        # 按顺序检查并创建或更新骨骼
        print("[CTMMD 2] ===== Step 2: Complete Missing Bones =====")
        created_bones = []
        updated_bones = []
        for bone_name, properties in bone_properties.items():
            existed = edit_bones.get(bone_name) is not None
            bone_utils.create_or_update_bone(
                edit_bones, bone_name,
                properties["head"], properties["tail"],
                properties.get("use_connect", False),
                properties["parent"],
                properties.get("use_deform", True)
            )
            eb = edit_bones.get(bone_name)
            parent_str = f"parent={properties['parent']}" if properties["parent"] else "no parent"
            deform_str = "deform" if properties.get("use_deform", True) else "control"
            head_str = f"({eb.head.x:.3f},{eb.head.y:.3f},{eb.head.z:.3f})" if eb else "?"
            if existed:
                updated_bones.append(bone_name)
                print(f"[CTMMD 2]   Updated: {bone_name:<12} head={head_str}  {parent_str}  [{deform_str}]")
            else:
                created_bones.append(bone_name)
                print(f"[CTMMD 2]   Created: {bone_name:<12} head={head_str}  {parent_str}  [{deform_str}]")

        # 首1 / 頭 re-parent: 首→首1→頭
        neck_eb = edit_bones.get("首")
        head_eb = edit_bones.get("頭")
        if neck_eb:
            neck1_existed = edit_bones.get("首1") is not None
            # 创建首1，直接不设 parent
            if not neck1_existed:
                neck1_eb = edit_bones.new("首1")
            else:
                neck1_eb = edit_bones["首1"]
            neck1_eb.head = neck1_head
            neck1_eb.tail = neck1_tail
            neck1_eb.use_deform = True
            neck1_eb.use_connect = False
            neck1_eb.parent = neck_eb
            actual_parent = neck1_eb.parent.name if neck1_eb.parent else "None"
            tag = "Updated" if neck1_existed else "Created"
            (updated_bones if neck1_existed else created_bones).append("首1")
            print(f"[CTMMD 2]   {tag}: {'首1':<12} head=({neck1_head.x:.3f},{neck1_head.y:.3f},{neck1_head.z:.3f})  parent={actual_parent}  [deform]")
            if head_eb:
                head_eb.use_connect = False
                head_eb.parent = neck1_eb
                actual_parent2 = head_eb.parent.name if head_eb.parent else "None"
                print(f"[CTMMD 2]   Reparent: 頭 -> {actual_parent2}")

        # 调用函数设置 roll 値
        bone_utils.set_roll_values(edit_bones, bone_utils.DEFAULT_ROLL_VALUES)
        print(f"[CTMMD 2] Done: created {len(created_bones)}, updated {len(updated_bones)}")
        print(f"[CTMMD 2]   Created bones: {', '.join(created_bones) if created_bones else 'none'}")

        # 切回 OBJECT 模式（权重分配由步骤2.5统一完成）
        bpy.ops.object.mode_set(mode='OBJECT')
        self.report({'INFO'}, f"Bone completion finished: created {len(created_bones)}, updated {len(updated_bones)}")

        return {'FINISHED'}
