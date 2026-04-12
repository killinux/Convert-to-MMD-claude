import bpy
import json

class OBJECT_OT_fill_from_selection_specific(bpy.types.Operator):
    """从当前选定的骨骼填充特定的骨骼属性"""
    bl_idname = "object.fill_from_selection_specific"
    bl_label = "Fill from Selection Specific"

    bone_property : bpy.props.StringProperty(name="Bone Property")# type: ignore

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "No armature object selected")
            return {'CANCELLED'}

        scene = context.scene
        mode = context.mode

        if mode == 'POSE':
            selected_bones = [bone.name for bone in obj.pose.bones if bone.bone.select]
        elif mode == 'EDIT_ARMATURE':
            selected_bones = [bone.name for bone in obj.data.edit_bones if bone.select]
        else:
            self.report({'ERROR'}, "Select bones in Pose Mode or Edit Mode")
            return {'CANCELLED'}

        if not selected_bones:
            self.report({'ERROR'}, "No bones selected")
            return {'CANCELLED'}

        # 使用第一个选定的骨骼
        setattr(scene, self.bone_property, selected_bones[0])
        return {'FINISHED'}


def get_bones_list():
    from .. import bone_map_and_group
    return {key: "" for key in bone_map_and_group.mmd_bone_map.keys()}


class OBJECT_OT_export_preset(bpy.types.Operator):
    bl_idname = "object.export_preset"
    bl_label = "Export Preset"
    filepath: bpy.props.StringProperty(subtype='FILE_PATH')

    def execute(self, context):
        scene = context.scene
        preset_data = {}
        for prop_name in get_bones_list():
            value = getattr(scene, prop_name, "")
            if value:
                preset_data[prop_name] = value
        with open(self.filepath, 'w', encoding='utf-8') as f:
            json.dump(preset_data, f, indent=4, ensure_ascii=False)
        self.report({'INFO'}, f"Preset exported to {self.filepath}")
        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class OBJECT_OT_import_preset(bpy.types.Operator):
    bl_idname = "object.import_preset"
    bl_label = "Import Preset"
    filepath: bpy.props.StringProperty(subtype='FILE_PATH')

    def execute(self, context):
        scene = context.scene
        with open(self.filepath, 'r', encoding='utf-8') as f:
            preset_data = json.load(f)
        for prop_name, bone_name in preset_data.items():
            if hasattr(scene, prop_name):
                setattr(scene, prop_name, bone_name)
        self.report({'INFO'}, f"Preset imported from {self.filepath}")
        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class OBJECT_OT_setup_pmx_attributes(bpy.types.Operator):
    """设置PMX导出所需的属性（name_j、付与親等）"""
    bl_idname = "object.setup_pmx_attributes"
    bl_label = "Setup PMX Attributes"
    bl_description = "设置name_j(.L/.R→左/右)和D骨付与親，确保PMX导出和VMD匹配正确"

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "No armature selected")
            return {'CANCELLED'}

        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        if not hasattr(bpy.types.PoseBone, 'mmd_bone'):
            self.report({'ERROR'}, "mmd_tools not installed (no mmd_bone attribute)")
            return {'CANCELLED'}

        # 设置 mmd_bone.name_j: .L/.R → 左/右 前缀格式（VMD 匹配用）
        name_j_count = 0
        for pb in obj.pose.bones:
            name = pb.name
            name_j = name
            if name.endswith('.L'):
                base = name[:-2]
                name_j = (base + '左') if base == '腰キャンセル' else ('左' + base)
            elif name.endswith('.R'):
                base = name[:-2]
                name_j = (base + '右') if base == '腰キャンセル' else ('右' + base)
            elif name.startswith('_dummy_') or name.startswith('_shadow_'):
                name_j = ''
            if pb.mmd_bone.name_j != name_j:
                pb.mmd_bone.name_j = name_j
                name_j_count += 1
        print(f"[CTMMD 8] Set name_j for {name_j_count} bones (.L/.R → 左/右)")

        # 设置 D骨/腰キャンセル 的付与親（additional transform）
        ADDITIONAL_TRANSFORM_MAP = {
            "足D": ("足", 1.0),
            "ひざD": ("ひざ", 1.0),
            "足首D": ("足首", 1.0),
        }
        at_count = 0
        for d_base, (main_base, influence) in ADDITIONAL_TRANSFORM_MAP.items():
            for suffix in [".L", ".R"]:
                d_name = d_base + suffix
                main_name = main_base + suffix
                d_pb = obj.pose.bones.get(d_name)
                if d_pb and obj.pose.bones.get(main_name):
                    d_pb.mmd_bone.additional_transform_bone = main_name
                    d_pb.mmd_bone.has_additional_rotation = True
                    d_pb.mmd_bone.has_additional_location = False
                    d_pb.mmd_bone.additional_transform_influence = influence
                    at_count += 1

        # 肩キャンセル: 付与親=肩P, 反転(-1.0)。目的: 抵消 肩P 对 腕 的旋转传递,
        # 让 VMD 里 肩P 动作只影响肩部而不二次叠加到手臂上。
        for suffix in (".L", ".R"):
            c_name = "肩C" + suffix
            p_name = "肩P" + suffix
            c_pb = obj.pose.bones.get(c_name)
            if c_pb and obj.pose.bones.get(p_name):
                c_pb.mmd_bone.additional_transform_bone = p_name
                c_pb.mmd_bone.has_additional_rotation = True
                c_pb.mmd_bone.has_additional_location = False
                c_pb.mmd_bone.additional_transform_influence = -1.0
                at_count += 1

        # 腰キャンセル: 付与親=腰, 反転(-1.0)
        # 注意: 付与親目标必须是"腰"(祖父)而不是"下半身"(父)。因为 腰キャンセル 的 parent 已经是
        # 下半身, 如果付与親再指 下半身, mmd_tools 导入 PMX 时会把 dummy bone parent 错误地设为
        # 下半身, 导致 下半身 的大旋转被叠加到 腰キャンセル 上, 腿部 IK 剧烈抖动。
        # 目标 c2 PMX 的做法: 腰キャンセル parent=下半身, 付与親=腰(-1.0)。
        for suffix in [".L", ".R"]:
            cancel_name = "腰キャンセル" + suffix
            cancel_pb = obj.pose.bones.get(cancel_name)
            if cancel_pb and obj.pose.bones.get("腰"):
                cancel_pb.mmd_bone.additional_transform_bone = "腰"
                cancel_pb.mmd_bone.has_additional_rotation = True
                cancel_pb.mmd_bone.has_additional_location = False
                cancel_pb.mmd_bone.additional_transform_influence = -1.0
                at_count += 1

        # 扭转骨系统 PMX 属性
        # 主骨 (腕捩 / 手捩): 启用 fixed_axis, 用 mmd_tools 原生约定从骨的 matrix_local
        #   Y 轴 (骨自身方向) 加 .xzy 交换获得 — 这是 mmd_tools FnBone.load_bone_fixed_axis
        #   使用的公式 (core/bone.py:84)。直接用 Blender 世界方向会导致 reimport 时
        #   bone.tail 被 mmd_tools 用 fixed_axis.xzy 还原, 出现 Y/Z 互换的错误方向。
        #   前提: 主 twist 骨的 rest 方向必须沿段方向 (在 twist_operator 已保证)。
        # 子骨 (腕捩1/2/3 / 手捩1/2/3): 付与親 指向主骨, 影响值 0.25/0.50/0.75
        TWIST_BASES = ("腕捩", "手捩")
        TWIST_INFLUENCE = {1: 0.25, 2: 0.50, 3: 0.75}
        twist_main = 0
        twist_sub = 0
        for base in TWIST_BASES:
            for suffix in (".L", ".R"):
                main_name = base + suffix
                main_pb = obj.pose.bones.get(main_name)
                if main_pb:
                    # bone.matrix_local.to_3x3().transposed()[1] = 骨自身 Y 轴 (方向)
                    # .xzy 是 mmd_tools 的坐标系交换约定
                    axes = main_pb.bone.matrix_local.to_3x3().transposed()
                    main_pb.mmd_bone.enabled_fixed_axis = True
                    main_pb.mmd_bone.fixed_axis = axes[1].xzy
                    # 锁定 X/Z 旋转，只允许绕 Y 轴 twist（与 mmd_tools build_rig 行为一致）
                    main_pb.lock_rotation[0] = True
                    main_pb.lock_rotation[2] = True
                    twist_main += 1
                for i, inf in TWIST_INFLUENCE.items():
                    sub_name = f"{base}{i}{suffix}"
                    sub_pb = obj.pose.bones.get(sub_name)
                    if sub_pb and main_pb:
                        sub_pb.mmd_bone.additional_transform_bone = main_name
                        sub_pb.mmd_bone.has_additional_rotation = True
                        sub_pb.mmd_bone.has_additional_location = False
                        sub_pb.mmd_bone.additional_transform_influence = inf
                        twist_sub += 1
        if twist_main or twist_sub:
            print(f"[CTMMD 8] Twist system: {twist_main} main (fixed_axis from bone Y.xzy), {twist_sub} sub (付与親)")

        # is_tip 标志: PMX 显示为"末端点"而非箭头骨。
        # is_tip: 显示为末端点。main twist 也设 is_tip (和目标一致),
        # tail 位置丢失对 twist 骨无影响 (它们用 fixed_axis 决定旋转轴)。
        # 且 mmd_tools importer 需要 is_tip + fixed_axis 组合才会自动设 lock_rotation。
        TIP_BONES = set()
        for base in ("腕捩", "手捩"):
            for suffix in (".L", ".R"):
                TIP_BONES.add(f"{base}{suffix}")  # main
                for i in (1, 2, 3):
                    TIP_BONES.add(f"{base}{i}{suffix}")  # sub
        TIP_BONES.update({"肩P.L", "肩P.R", "肩C.L", "肩C.R"})
        tip_count = 0
        for name in TIP_BONES:
            pb = obj.pose.bones.get(name)
            if pb:
                pb.mmd_bone.is_tip = True
                tip_count += 1
        print(f"[CTMMD 8] Set is_tip for {tip_count} bones")

        # transform_order: D 骨设为 1（在付与親源骨之后计算）
        D_ORDER_BONES = ["足D", "ひざD", "足首D", "足先EX"]
        order_count = 0
        for base in D_ORDER_BONES:
            for suffix in (".L", ".R"):
                pb = obj.pose.bones.get(base + suffix)
                if pb:
                    pb.mmd_bone.transform_order = 1
                    order_count += 1
        print(f"[CTMMD 8] Set transform_order=1 for {order_count} D-bones")

        # lock_location: 控制骨 + twist 骨 + 辅助骨锁定位移
        LOCK_LOC_BASES_LR = [
            "肩P", "肩C", "腰キャンセル",
            "腕捩", "腕捩1", "腕捩2", "腕捩3",
            "手捩", "手捩1", "手捩2", "手捩3",
            "足先EX", "乳奶",
        ]
        lock_count = 0
        for name in ("腰", "両目", "目.L", "目.R"):
            pb = obj.pose.bones.get(name)
            if pb:
                pb.lock_location = [True, True, True]
                lock_count += 1
        # hair 骨: 按名前缀匹配 (目标 PMX 的 hair 骨全部 lock_location)
        for pb in obj.pose.bones:
            if pb.name.startswith("hair ") or pb.name.startswith("head hair"):
                pb.lock_location = [True, True, True]
                lock_count += 1
        for base in LOCK_LOC_BASES_LR:
            for suffix in (".L", ".R"):
                pb = obj.pose.bones.get(base + suffix)
                if pb:
                    pb.lock_location = [True, True, True]
                    lock_count += 1
        print(f"[CTMMD 8] Set lock_location for {lock_count} bones")

        print(f"[CTMMD 8] Set additional_transform for {at_count} bones")
        self.report({'INFO'}, f"PMX attributes set: {name_j_count} name_j, {at_count} additional_transform, twist {twist_main}+{twist_sub}")
        return {'FINISHED'}


class OBJECT_OT_use_mmd_tools_convert(bpy.types.Operator):
    """调用mmdtools进行格式转换"""
    bl_idname = "object.use_mmd_tools_convert"
    bl_label = "Convert to MMD Model"
    bl_description = "使用mmd_tools插件转换模型格式（需要先安装mmd_tools插件）"

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "No armature object selected")
            return {'CANCELLED'}

        # 保存当前模式并切换到OBJECT模式
        current_mode = context.mode
        if current_mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        # 先执行 PMX 属性设置
        bpy.ops.object.setup_pmx_attributes()

        try:
            # 调用mmd_tools的转换功能
            bpy.ops.mmd_tools.convert_to_mmd_model()
        except AttributeError as e:
            # 弹出错误提示窗口
            self.report({'ERROR'}, "mmd_tools is not installed")
            bpy.context.window_manager.popup_menu(
                self.draw_error_menu,
                title="MMD Tools Not Installed",
                icon='ERROR'
            )
            return {'CANCELLED'}

        # mmd_tools convert_to_mmd_model 会把部分 bone.hide 标志重置, 在此重新应用:
        #   main twist (腕捩/手捩): hide=False (用户可见)
        #   sub twist + 肩C: hide=True (隐藏, 编辑模式可见)
        MAIN_TWIST_VISIBLE = {"腕捩.L","腕捩.R","手捩.L","手捩.R"}
        HIDDEN_BONES = {"肩C.L","肩C.R"} | {
            f"{base}{i}{side}"
            for base in ("腕捩","手捩") for i in (1,2,3) for side in (".L",".R")
        }
        if obj and obj.type == 'ARMATURE':
            v = h = 0
            for name in MAIN_TWIST_VISIBLE:
                b = obj.data.bones.get(name)
                if b:
                    b.hide = False
                    v += 1
            for name in HIDDEN_BONES:
                b = obj.data.bones.get(name)
                if b:
                    b.hide = True
                    h += 1
            print(f"[CTMMD convert] Re-applied hide flags: {v} visible, {h} hidden")

        # convert 会清掉 lock_rotation, 重新设置 twist main 骨的旋转锁定
        for base in ("腕捩", "手捩"):
            for suffix in (".L", ".R"):
                name = base + suffix
                pb = obj.pose.bones.get(name)
                if pb and pb.mmd_bone.enabled_fixed_axis:
                    pb.lock_rotation[0] = True
                    pb.lock_rotation[2] = True
        print("[CTMMD convert] Re-applied lock_rotation on twist bones")

        # 把 mmd_bone 元数据 (additional_transform / fixed_axis) 物化为 Blender bone
        # constraint 链。convert_to_mmd_model() 只设属性, 不创建 viewport constraint;
        # 没有这一步, 腕捩1/2/3 等 sub twist 子骨在 Blender 视口里完全是死的, 挂在它们
        # 上面的 vert 永远停在 rest pose, VMD 播放时上臂没有 twist 渐变。
        # mmd_tools.import_model 会自动跑这一步, convert_to_mmd_model 不会, 所以 XPS 转
        # 路径必须显式追加。会创建 _shadow_腕捩X / _dummy_腕捩X + TRANSFORM constraint。
        try:
            bpy.ops.mmd_tools.apply_additional_transform()
            print("[CTMMD convert] Applied additional_transform constraints")
        except Exception as e:
            print(f"[CTMMD convert] apply_additional_transform 失败: {e}")

        # 恢复原始选择状态
        context.view_layer.objects.active = obj
        obj.select_set(True)
        return {'FINISHED'}

    def draw_error_menu(self, menu, context):
        layout = menu.layout
        layout.label(text="mmd_tools is not installed", icon='ERROR')
        layout.separator()
        layout.operator(
            "wm.url_open",
            text="Open Download Page",
            icon='URL'
        ).url = "https://extensions.blender.org/add-ons/mmd-tools/"
        layout.operator(
            "wm.url_open",
            text="Open Documentation",
            icon='HELP'
        ).url = "https://mmd-blender.fandom.com/wiki/MMD_Tools_Documentation"
