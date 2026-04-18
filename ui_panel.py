import bpy
import os
import json
from datetime import datetime

LOAD_TIME = datetime.now().strftime("%m/%d %H:%M:%S")
CODE_VERSION = "04/06 phase6-en"  # 每次代码更新后由Claude 修改此行

class OBJECT_OT_load_preset(bpy.types.Operator):
    bl_idname = "object.load_preset"
    bl_label = "Load Preset"
    
    preset_name: bpy.props.StringProperty()
    
    def execute(self, context):
        script_dir = os.path.dirname(os.path.realpath(__file__))
        presets_dir = os.path.join(script_dir, "presets")
        preset_path = os.path.join(presets_dir, f"{self.preset_name}.json")
        
        if os.path.exists(preset_path):
            with open(preset_path, 'r', encoding='utf-8') as f:
                preset_data = json.load(f)
                
            for prop_name, bone_name in preset_data.items():
                if hasattr(context.scene, prop_name):
                    setattr(context.scene, prop_name, bone_name)
        
        return {'FINISHED'}

class OBJECT_PT_skeleton_hierarchy(bpy.types.Panel):
    bl_label = "Convert to MMD"
    bl_idname = "OBJECT_PT_convert_to_mmd"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Convert to MMD"

    def draw(self, context):
        layout = self.layout
        scene = context.scene


        # 检查活动对象是否为骨架
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            layout.menu("TOPBAR_MT_file_import", text="Import", icon='IMPORT')
            return

        # 添加带有标签、prop_search用于骨骼和填充按钮的行的函数
        def add_bone_row_with_button(layout, label_text, prop_name):
            row = layout.row(align=True)
            split_name = row.split(factor=0.1, align=True)
            # 左侧部分：骨骼名称
            split_name.label(text=label_text)
            # action部分占用剩余的0.8
            split_action = split_name.split(factor=1)
            sub_split = split_action.split(factor=(0.49*0.1), align=True)
            # 按钮部分
            sub_split.operator(
                "object.fill_from_selection_specific",
                text="",
                icon='ZOOM_SELECTED'
            ).bone_property = prop_name
            # 选择框部分
            sub_split.prop_search(
                scene,
                prop_name,
                obj.data,
                "bones",
                text=""
            )
        def add_symmetric_bones_with_buttons(layout, label_text, left_prop, right_prop):
            # 第一层划分：将行分为 0.2 和 0.8 两部分
            row = layout.row(align=True)
            # 骨骼名字（Name）使用0.2
            split_name = row.split(factor=0.1, align=True)
            split_name.label(text=label_text)  # 显示骨骼名字
            # split() 的比例是基于当前容器的剩余空间
            # action部分使用name剩下的0.8
            split_action = split_name.split(factor=1, align=True)

            # 左侧操作部分 使用action的0.49
            split_left_action = split_action.split(factor=0.49, align=True)  # 使用相对比例
            col_left_action = split_left_action.column(align=True)
            row_left_action = col_left_action.row(align=True)

            # 在左侧操作部分进一步划分为 Button 和 Search Box
            sub_split_left_button = row_left_action.split(factor=0.1, align=True)
            sub_split_left_button.operator(
                "object.fill_from_selection_specific",
                text="",
                icon='ZOOM_SELECTED'
            ).bone_property = left_prop  # 左侧按钮（Button）
            sub_split_left_button.prop_search(
                scene,
                left_prop,
                obj.data,
                "bones",
                text=""  # 左侧选择框（Search Box）
            )

            # 中间部分使用left_action剩下的0.51划分0.02/(0.02+0.49)给中间分割符
            split_divider = split_left_action.split(factor=(0.02/(0.02+0.49)), align=True)  # 动态计算剩余比例
            split_divider.label(text="|")  # 使用 "|" 模拟分割线

            # 右侧操作部分使用剩下的0.49
            split_right_action = split_divider.split(factor=1,align=True)
            col_right_action = split_right_action.column(align=True)
            row_right_action = col_right_action.row(align=True)

            # 在右侧操作部分进一步划分为 Button 和 Search Box
            sub_split_right_button = row_right_action.split(factor=0.1, align=True)
            sub_split_right_button.operator(
                "object.fill_from_selection_specific",
                text="",
                icon='ZOOM_SELECTED'
            ).bone_property = right_prop  # 右侧按钮（Button）
            sub_split_right_button.prop_search(
                scene,
                right_prop,
                obj.data,
                "bones",
                text=""  # 右侧选择框（Search Box）
            )
        def add_finger_bones_with_buttons(layout, label_text, first_prop, second_prop, third_prop):
            
            divider_ratio = 0.02
            split_ratio = (1-2*divider_ratio)/3
            # 第一层划分：将行分为 0.2 和 0.8 两部分
            row = layout.row(align=True)
            # 骨骼名字（Name）使用0.2
            split_name = row.split(factor=0.1, align=True)
            split_name.label(text=label_text)  # 显示骨骼名字
            # split() 的比例是基于当前容器的剩余空间
            # action部分使用name剩下的0.8
            split_action = split_name.split(factor=1, align=True)

            # 右侧操作区域划分为三列：split_ratio divider_ratio split_ratio divider_ratio split_ratio
            # 第一个操作区域（0.32）
            split_first_action = split_action.split(factor=split_ratio, align=True)
            col_first_action = split_first_action.column(align=True)
            row_first_action = col_first_action.row(align=True)
            # 在右侧操作部分进一步划分为 Button 和 Search Box
            sub_split_first_button = row_first_action.split(factor=0.1, align=True)
            sub_split_first_button.operator(
                "object.fill_from_selection_specific",
                text="",
                icon='ZOOM_SELECTED'
            ).bone_property = first_prop  # 右側按钮（Button）
            sub_split_first_button.prop_search(
                scene,
                first_prop,
                obj.data,
                "bones",
                text=""  # 右側选择框（Search Box）
            )
            # 中间分割线（{divider_ratio}）
            split_divider1 = split_first_action.split(factor=divider_ratio/(1-split_ratio), align=True)
            split_divider1.label(text="|")  # 分割线
            # 第二个操作区域（0.32）
            split_second_bone = split_divider1.split(factor=split_ratio/(1-split_ratio-divider_ratio), align=True)
            col_second_bone = split_second_bone.column(align=True)
            row_second_bone = col_second_bone.row(align=True)
            # 在右侧操作部分进一步划分为 Button 和 Search Box
            sub_split_second_button = row_second_bone.split(factor=0.1, align=True)
            sub_split_second_button.operator(
                "object.fill_from_selection_specific",
                text="",
                icon='ZOOM_SELECTED'
            ).bone_property = second_prop  # 右側按钮（Button）
            sub_split_second_button.prop_search(
                scene,
                second_prop,
                obj.data,
                "bones",
                text=""  # 右側选择框（Search Box）
            )
            # 中间分割线（{divider_ratio}）
            split_divider2 = split_second_bone.split(factor=divider_ratio/(1-split_ratio*2-divider_ratio), align=True)
            split_divider2.label(text="|")
            
            # 第三个操作区
            split_third_bone = split_divider2.split(factor=1, align=True)
            col_third_bone = split_third_bone.column(align=True)
            row_third_bone = col_third_bone.row(align=True)
            # 在右侧操作部分进一步划分为 Button 和 Search Box
            sub_split_third_button = row_third_bone.split(factor=0.1, align=True)
            sub_split_third_button.operator(
                "object.fill_from_selection_specific",
                text="",
                icon='ZOOM_SELECTED'
            ).bone_property = third_prop  # 右側按钮（Button）
            sub_split_third_button.prop_search(
                scene,
                third_prop,
                obj.data,
                "bones",
                text=""  # 右側选择框（Search Box）
            )
        layout.label(text=f"v{CODE_VERSION}  loaded {LOAD_TIME}", icon='TIME')

        # 添加选项卡按钮 - 移动到条件判断外部，使其始终可见
        row = layout.row()
        row.prop(scene, "my_enum", expand=True)
        if scene.my_enum == 'option1':

            # 新增 EnumProperty 下拉菜单
            row = layout.row()
            row.prop(scene, "preset_enum", text="")
        
            main_col = layout.column(align=True)
            # 全ての親到腰部分
            full_body_box = main_col.box()
            col = full_body_box.column()
            add_bone_row_with_button(col, "操作中心:", "control_center_bone")
            add_bone_row_with_button(col, "全ての親", "all_parents_bone")
            add_bone_row_with_button(col, "センター", "center_bone")
            add_bone_row_with_button(col, "グルーブ", "groove_bone")
            add_bone_row_with_button(col, "腰", "hip_bone")

            # 上半身到頭部分
            upper_body_box = main_col.box()
            col = upper_body_box.column()
            add_bone_row_with_button(col, "上半身", "upper_body_bone")
            add_bone_row_with_button(col, "上半身1", "upper_body1_bone")
            add_bone_row_with_button(col, "上半身2", "upper_body2_bone")
            add_bone_row_with_button(col, "上半身3", "upper_body3_bone")
            add_bone_row_with_button(col, "首", "neck_bone")
            add_bone_row_with_button(col, "頭", "head_bone")
            add_symmetric_bones_with_buttons(col, "目:", "left_eye_bone", "right_eye_bone")
            add_symmetric_bones_with_buttons(col, "肩:", "left_shoulder_bone", "right_shoulder_bone")
            add_symmetric_bones_with_buttons(col, "腕:", "left_upper_arm_bone", "right_upper_arm_bone")
            add_symmetric_bones_with_buttons(col, "ひじ:", "left_lower_arm_bone", "right_lower_arm_bone")
            add_symmetric_bones_with_buttons(col, "手首:", "left_hand_bone", "right_hand_bone")

            # 下半身到足首部分
            lower_body_box = main_col.box()
            col = lower_body_box.column()
            add_bone_row_with_button(col, "下半身", "lower_body_bone")
            add_symmetric_bones_with_buttons(col, "足:", "left_thigh_bone", "right_thigh_bone")
            add_symmetric_bones_with_buttons(col, "ひざ:", "left_calf_bone", "right_calf_bone")
            add_symmetric_bones_with_buttons(col, "足首:", "left_foot_bone", "right_foot_bone")
            add_symmetric_bones_with_buttons(col, "足先EX:", "left_toe_bone", "right_toe_bone")

            fingers_box = main_col.box()
            col = fingers_box.column()
            add_finger_bones_with_buttons(col, "左親指:", "left_thumb_0", "left_thumb_1", "left_thumb_2")
            add_finger_bones_with_buttons(col, "左人指:", "left_index_1", "left_index_2", "left_index_3")
            add_finger_bones_with_buttons(col, "左中指:", "left_middle_1", "left_middle_2", "left_middle_3")
            add_finger_bones_with_buttons(col, "左薬指:", "left_ring_1", "left_ring_2", "left_ring_3")
            add_finger_bones_with_buttons(col, "左小指:", "left_pinky_1", "left_pinky_2", "left_pinky_3")

            add_finger_bones_with_buttons(col, "右親指:", "right_thumb_0", "right_thumb_1", "right_thumb_2")
            add_finger_bones_with_buttons(col, "右人指:", "right_index_1", "right_index_2", "right_index_3")
            add_finger_bones_with_buttons(col, "右中指:", "right_middle_1", "right_middle_2", "right_middle_3")
            add_finger_bones_with_buttons(col, "右薬指:", "right_ring_1", "right_ring_2", "right_ring_3")
            add_finger_bones_with_buttons(col, "右小指:", "right_pinky_1", "right_pinky_2", "right_pinky_3")    
                
            # 添加导入/导出预设按钮
            row = layout.row()
            row.operator("object.import_preset", text="导入预设")
            row.operator("object.export_preset", text="导出预设")

            # 一键转换 (跑完 step 1→11)
            row = layout.row()
            row.scale_y = 1.4
            row.operator("object.one_click_convert", text="🚀 一键转换 (1→11)", icon='PLAY')

            # 可选预处理 (折叠, 默认收起)
            pre_box = layout.box()
            row = pre_box.row()
            row.prop(scene, "ctmmd_show_preprocessing", text="",
                     icon='TRIA_DOWN' if scene.ctmmd_show_preprocessing else 'TRIA_RIGHT',
                     emboss=False)
            row.label(text="可选预处理 (rest pose 烘焙)", icon='MODIFIER')
            if scene.ctmmd_show_preprocessing:
                pre_box.operator("object.align_arms_to_reference", text="对齐手臂 (→参考或canonical)")
                pre_box.operator("object.align_fingers_to_reference", text="对齐手指 (→参考或canonical)")
                pre_box.operator("object.fix_forearm_bend", text="修正前腕弯曲")

            # 阶段 ①: 骨骼结构
            struct_box = layout.box()
            struct_box.label(text="① 骨骼结构", icon='ARMATURE_DATA')
            struct_box.operator("object.rename_to_mmd", text="1. 重命名为MMD")
            struct_box.operator("object.complete_missing_bones", text="2. 补全缺失骨骼")
            struct_box.operator("object.complete_twist_bones", text="3. 补全扭转骨")
            struct_box.operator("object.complete_d_bones", text="4. 补全D骨")
            struct_box.operator("object.complete_hip_cancel_bones", text="5. 补全腰キャンセル")

            # 阶段 ②: 清理 + 权重
            weight_box = layout.box()
            weight_box.label(text="② 清理+权重", icon='MOD_VERTEX_WEIGHT')
            weight_box.operator("object.cleanup_face_bones", text="6. 清理面部细骨", icon='MESH_MONKEY')
            weight_box.operator("object.assign_weights", text="7. 分配权重 (一键)")

            # 阶段 ③: IK + 属性
            attr_box = layout.box()
            attr_box.label(text="③ IK+属性", icon='CON_KINEMATIC')
            attr_box.operator("object.add_mmd_ik", text="8. 添加MMD IK")
            attr_box.operator("object.create_bone_group", text="9. 创建骨骼集合")
            attr_box.operator("object.setup_pmx_attributes", text="10. 设置PMX属性")

            # 阶段 ④: 转换 + 物理
            final_box = layout.box()
            final_box.label(text="④ 转换+物理", icon='EXPORT')
            final_box.operator("object.use_mmd_tools_convert", text="11. 使用mmd_tools转换")
            row = final_box.row(align=True)
            row.operator("object.setup_physics", text="12. 加载物理模板", icon='PHYSICS')
            row.operator("object.extract_physics_template", text="", icon='EXPORT')

            # 高级 / 调试 (折叠, 默认收起)
            adv_box = layout.box()
            row = adv_box.row()
            row.prop(scene, "ctmmd_show_advanced", text="",
                     icon='TRIA_DOWN' if scene.ctmmd_show_advanced else 'TRIA_RIGHT',
                     emboss=False)
            row.label(text="高级 / 调试", icon='TOOL_SETTINGS')
            if scene.ctmmd_show_advanced:
                adv_box.label(text="步骤 7 (分配权重) 内部阶段 — 调试重跑:")
                grid = adv_box.grid_flow(row_major=True, columns=3, even_columns=True)
                grid.operator("object.assign_weights_phase2", text="Unused→主骨")
                grid.operator("object.assign_weights_phase1", text="主骨→D骨")
                grid.operator("object.assign_weights_phase3", text="腰キャン清空")
                grid.operator("object.assign_weights_phase4", text="迷路修复")
                grid.operator("object.assign_weights_phase5", text="下半身清理")
                grid.operator("object.assign_weights_phase6", text="未处理诊断")
                row = adv_box.row(align=True)
                row.operator("object.split_upper_arm_twist_weights", text="上臂 twist 渐变")
                row.operator("object.split_forearm_twist_weights", text="前腕 twist 渐变")
                adv_box.separator()
                adv_box.label(text="骨骼命名互转:")
                row = adv_box.row(align=True)
                row.operator("object.convert_names_to_jp", text=".L/.R → 左/右", icon='ARROW_LEFTRIGHT')
                row.operator("object.convert_names_to_lr", text="左/右 → .L/.R", icon='ARROW_LEFTRIGHT')
                adv_box.operator("object.convert_to_apose", text="T-Pose → A-Pose")
        # 物理 + 表情 选项卡
        elif scene.my_enum == 'option2':
            # 胸部物理
            breast_box = layout.box()
            breast_box.label(text="胸部物理", icon='MOD_SOFT')
            breast_box.operator("object.apply_breast_physics", text="应用胸部 rigid (乳奶.L/R)")
            breast_box.label(text="需先跑过 12. 加载物理模板 (获得锚点 上半身2)",
                             icon='INFO')

            # 刚体编辑
            rigid_box = layout.box()
            rigid_box.label(text="刚体编辑", icon='PHYSICS')
            rigid_box.operator("object.toggle_rigid_visibility", text="显示/隐藏所有刚体", icon='HIDE_OFF')
            rigid_box.label(text="单个 rigid 属性: 选中刚体后", icon='INFO')
            rigid_box.label(text="   N面板 → MMD → Rigid Body")

            # 表情 Morph
            morph_box = layout.box()
            morph_box.label(text="表情 Morph (顺序①→②→④)", icon='SHAPEKEY_DATA')
            morph_box.operator("object.clone_face_bones_from_target",
                               text="① 补面部驱动骨 (Jaw Bone / QQ*)",
                               icon='BONE_DATA')
            morph_box.operator("object.clone_morphs_from_target",
                               text="② 克隆 bone/material/group morph (topology 安全)",
                               icon='DUPLICATE')
            morph_box.operator("object.synth_vertex_morphs",
                               text="④ 程序化合成 19 条 vertex morph (Path D, 推荐)",
                               icon='SHAPEKEY_DATA')
            morph_box.label(text="然后: N面板 → MMD → Morph Tools 查看/编辑",
                            icon='INFO')

            # 表情验证 (Tools A/B/C)
            verify_box = layout.box()
            verify_box.label(text="表情 Morph 验证", icon='VIEWZOOM')
            verify_box.operator("morph.run_spec_check",
                                text="自动 Spec 校验 (数据)",
                                icon='CHECKMARK')
            verify_box.operator("morph.run_batch_screenshot",
                                text="批量截图 + HTML 对比",
                                icon='RENDER_STILL')
            verify_box.operator("morph.start_verify_modal",
                                text="交互式逐条过 (O/X/N 键盘)",
                                icon='PLAY')

            # 已弃用旧方案 (折叠, 默认收起)
            adv_box = layout.box()
            row = adv_box.row()
            row.prop(scene, "ctmmd_show_advanced", text="",
                     icon='TRIA_DOWN' if scene.ctmmd_show_advanced else 'TRIA_RIGHT',
                     emboss=False)
            row.label(text="高级 / 旧方案", icon='TOOL_SETTINGS')
            if scene.ctmmd_show_advanced:
                adv_box.label(text="旧方案 (视觉质量差, 保留仅作对比)", icon='ERROR')
                adv_box.operator("object.bake_and_transfer_morphs",
                                 text="③ [旧] KDTree 近邻传 vertex morph",
                                 icon='SHAPEKEY_DATA')
                adv_box.label(text="跨 mesh KDTree/TPS/SurfaceDeform 传 offset")
                adv_box.label(text="视觉会稀释 (撅嘴/翻唇), 已由 ④ 替代")