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
        print(f"[CTMMD 10] Set name_j for {name_j_count} bones (.L/.R → 左/右)")

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
            print(f"[CTMMD 10] Twist system: {twist_main} main (fixed_axis from bone Y.xzy), {twist_sub} sub (付与親)")

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
        print(f"[CTMMD 10] Set is_tip for {tip_count} bones")

        # transform_order: D 骨设为 1（在付与親源骨之后计算）
        D_ORDER_BONES = ["足D", "ひざD", "足首D", "足先EX"]
        order_count = 0
        for base in D_ORDER_BONES:
            for suffix in (".L", ".R"):
                pb = obj.pose.bones.get(base + suffix)
                if pb:
                    pb.mmd_bone.transform_order = 1
                    order_count += 1
        print(f"[CTMMD 10] Set transform_order=1 for {order_count} D-bones")

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
        print(f"[CTMMD 10] Set lock_location for {lock_count} bones")

        print(f"[CTMMD 10] Set additional_transform for {at_count} bones")

        # 设置 name_e (英文名): 完整映射表，含 .L/.R 的全名直接映射
        # 身体骨用 l/r 前缀 (XPS 风格), 控制骨用 _L/_R 后缀
        # 目标 PMX 中 name_e 为空的骨不设置 (グルーブ, センター, 両目, 肩C, 腰キャンセル, twist 子骨, IK 骨等)
        NAME_E_FULL = {
            # 中心骨
            "全ての親": "root", "操作中心": "view cnt", "腰": "waist",
            "上半身": "abdomenLower", "上半身1": "abdomenUpper",
            "上半身2": "chestLower", "上半身3": "chestUpper",
            "下半身": "hip", "首": "neckLower", "首1": "neckUpper", "頭": "head",
            # 肩/腕 (l/r 前缀)
            "肩.L": "lCollar", "肩.R": "rCollar",
            "肩P.L": "shoulderP_L", "肩P.R": "shoulderP_R",
            "腕.L": "lShldrBend", "腕.R": "rShldrBend",
            "腕捩.L": "arm twist_L", "腕捩.R": "arm twist_R",
            "ひじ.L": "lForearmBend", "ひじ.R": "rForearmBend",
            "手捩.L": "wrist twist_L", "手捩.R": "wrist twist_R",
            "手首.L": "lHand", "手首.R": "rHand",
            "ダミー.L": "dummy_L", "ダミー.R": "dummy_R",
            # 目
            "目.L": "lEye", "目.R": "rEye",
            # 指 (l/r 前缀)
            "親指０.L": "lThumb1", "親指０.R": "rThumb1",
            "親指１.L": "lThumb2", "親指１.R": "rThumb2",
            "親指２.L": "lThumb3", "親指２.R": "rThumb3",
            "人指０.L": "lCarpal1", "人指０.R": "rCarpal1",
            "人指１.L": "lIndex1", "人指１.R": "rIndex1",
            "人指２.L": "lIndex2", "人指２.R": "rIndex2",
            "人指３.L": "lIndex3", "人指３.R": "rIndex3",
            "中指０.L": "lCarpal2", "中指０.R": "rCarpal2",
            "中指１.L": "lMid1", "中指１.R": "rMid1",
            "中指２.L": "lMid2", "中指２.R": "rMid2",
            "中指３.L": "lMid3", "中指３.R": "rMid3",
            "薬指０.L": "lCarpal3", "薬指０.R": "rCarpal3",
            "薬指１.L": "lRing1", "薬指１.R": "rRing1",
            "薬指２.L": "lRing2", "薬指２.R": "rRing2",
            "薬指３.L": "lRing3", "薬指３.R": "rRing3",
            "小指０.L": "lCarpal4", "小指０.R": "rCarpal4",
            "小指１.L": "lPinky1", "小指１.R": "rPinky1",
            "小指２.L": "lPinky2", "小指２.R": "rPinky2",
            "小指３.L": "lPinky3", "小指３.R": "rPinky3",
            # 足 (l/r 前缀)
            "足.L": "lThighBend", "足.R": "rThighBend",
            "ひざ.L": "lShin", "ひざ.R": "rShin",
            "足首.L": "lFoot", "足首.R": "rFoot",
            "つま先.L": "lToe", "つま先.R": "rToe",
            # D 骨
            "足D.L": "lThighBendD", "足D.R": "rThighBendD",
            "ひざD.L": "lShinD", "ひざD.R": "rShinD",
            "足首D.L": "lFootD", "足首D.R": "rFootD",
            "足先EX.L": "toe2_L", "足先EX.R": "toe2_R",
            # IK 親
            "足IK親.L": "leg IKP_L", "足IK親.R": "leg IKP_R",
            # 乳
            "乳奶.L": "lPectoral", "乳奶.R": "rPectoral",
        }
        name_e_count = 0
        for pb in obj.pose.bones:
            if pb.name.startswith('_dummy_') or pb.name.startswith('_shadow_'):
                continue
            name_e = NAME_E_FULL.get(pb.name, "")
            if name_e and pb.mmd_bone.name_e != name_e:
                pb.mmd_bone.name_e = name_e
                name_e_count += 1
        print(f"[CTMMD 10] Set name_e for {name_e_count} bones")

        # 已知未修复差异 log（供调试参考）
        print("[CTMMD 10] Known remaining diffs vs target PMX:")
        print("[CTMMD 10]   - 位置/长度/方向: 两模型体型不同, 非 pipeline bug")
        print("[CTMMD 10]   - 腕捩 fixed_axis Z 轴差 ~0.003: 手臂对齐浮点误差, 不影响效果")
        print("[CTMMD 10]   - 脚趾细分骨 (BigToe/SmallToe): XPS 源无此骨, TODO")
        print("[CTMMD 10]   - name_e 未映射的骨骼保持为空 (hair/unused 等非标准骨)")

        self.report({'INFO'}, f"PMX attributes set: {name_j_count} name_j, {name_e_count} name_e, {at_count} additional_transform, twist {twist_main}+{twist_sub}")
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
            print(f"[CTMMD 11] Re-applied hide flags: {v} visible, {h} hidden")

        # convert 会清掉 lock_rotation, 重新设置 twist main 骨的旋转锁定
        for base in ("腕捩", "手捩"):
            for suffix in (".L", ".R"):
                name = base + suffix
                pb = obj.pose.bones.get(name)
                if pb and pb.mmd_bone.enabled_fixed_axis:
                    pb.lock_rotation[0] = True
                    pb.lock_rotation[2] = True
        print("[CTMMD 11] Re-applied lock_rotation on twist bones")

        # 把 mmd_bone 元数据 (additional_transform / fixed_axis) 物化为 Blender
        # constraint 链。涵盖所有设了 additional_transform_bone 的骨:
        #   - D骨 (足D/ひざD/足首D): shadow/dummy + TRANSFORM (influence=1.0)
        #   - 腰キャンセル: shadow/dummy + TRANSFORM (influence=-1.0, 反转)
        #   - 肩C: shadow/dummy + TRANSFORM (influence=-1.0)
        #   - twist 子骨 (腕捩1-3/手捩1-3): shadow/dummy + TRANSFORM
        # 对齐良好的骨对 (如 D骨与源骨同位), mmd_tools 会跳过 shadow/dummy
        # 直接用 TRANSFORM constraint 指向源骨 (优化路径)。
        try:
            bpy.ops.mmd_tools.apply_additional_transform()
            print("[CTMMD 11] Applied additional_transform constraints")
        except Exception as e:
            print(f"[CTMMD 11] apply_additional_transform 失败: {e}")

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


class OBJECT_OT_one_click_convert(bpy.types.Operator):
    """一键运行主转换流程 (step 1→11). 前提: 已选中 XPS armature 并加载 preset."""
    bl_idname = "object.one_click_convert"
    bl_label = "一键转换 (1→11)"
    bl_description = "按顺序跑主流程: 预处理/重命名/补骨/权重/IK/PMX属性/mmd_tools转换"
    bl_options = {'REGISTER', 'UNDO'}

    run_preprocessing: bpy.props.BoolProperty(
        name="运行预处理",
        description="先跑对齐手臂/手指/修正前腕 (rest pose 烘焙)",
        default=True,
    )

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=320)

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "请先选中 XPS armature")
            return {'CANCELLED'}

        pipeline = []
        if self.run_preprocessing:
            pipeline += [
                ('align_arms_to_reference', False),
                ('align_fingers_to_reference', False),
                ('fix_forearm_bend', False),
            ]
        pipeline += [
            ('rename_to_mmd', True),
            ('complete_missing_bones', True),
            ('complete_twist_bones', True),
            ('complete_d_bones', True),
            ('complete_hip_cancel_bones', True),
            ('cleanup_face_bones', False),  # may CANCEL for DAZ (no XPS face bones)
            ('assign_weights', True),
            ('add_mmd_ik', True),
            ('create_bone_group', True),
            ('setup_pmx_attributes', True),
            ('use_mmd_tools_convert', True),
        ]

        for step_name, required in pipeline:
            op = getattr(bpy.ops.object, step_name, None)
            if op is None:
                self.report({'ERROR'}, f"operator 不存在: object.{step_name}")
                return {'CANCELLED'}
            print(f'[CTMMD one-click] -> {step_name}')
            try:
                ret = op()
            except Exception as e:
                msg = f'step {step_name} 抛异常: {e}'
                print(f'[CTMMD one-click] {msg}')
                self.report({'ERROR'}, msg)
                return {'CANCELLED'}
            if 'FINISHED' not in ret:
                if required:
                    msg = f'step {step_name} 返回 {ret} (必需步骤, 中止)'
                    print(f'[CTMMD one-click] {msg}')
                    self.report({'ERROR'}, msg)
                    return {'CANCELLED'}
                print(f'[CTMMD one-click] {step_name}: {ret} (可选, 继续)')

        self.report({'INFO'}, "一键转换完成 (step 1→11)")
        return {'FINISHED'}
