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

        # 将第一个选定的骨骼填充到指定属性中
        setattr(scene, self.bone_property, selected_bones[0])

        return {'FINISHED'}

class OBJECT_OT_export_preset(bpy.types.Operator):
    """导出当前骨骼配置为预设"""
    bl_idname = "object.export_preset"
    bl_label = "Export Preset"
    filepath : bpy.props.StringProperty(subtype="FILE_PATH")# type: ignore

    def execute(self, context):
        scene = context.scene
        preset = {}
        for prop_name in get_bones_list():  # 确保 get_bones_list 在当前作用域中
            preset[prop_name] = getattr(scene, prop_name, "")

        with open(self.filepath, 'w') as file:
            json.dump(preset, file, indent=4)

        self.report({'INFO'}, f"Preset exported to {self.filepath}")
        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        # 设置默认文件名为 CTMMD.json
        self.filepath = bpy.path.ensure_ext("CTMMD", ".json")
        return {'RUNNING_MODAL'}

class OBJECT_OT_import_preset(bpy.types.Operator):
    """导入骨骼配置预设"""
    bl_idname = "object.import_preset"
    bl_label = "Import Preset"
    filepath : bpy.props.StringProperty(subtype="FILE_PATH")# type: ignore

    def execute(self, context):
        scene = context.scene
        try:
            with open(self.filepath, 'r') as file:
                preset = json.load(file)
        except Exception as e:
            self.report({'ERROR'}, f"Failed to load preset: {str(e)}")
            return {'CANCELLED'}

        for prop_name, value in preset.items():
            if prop_name in get_bones_list():
                setattr(scene, prop_name, value)

        self.report({'INFO'}, f"Preset imported from {self.filepath}")
        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        # 设置文件过滤器仅显示 JSON 文件
        self.filter_glob = "*.json"
        return {'RUNNING_MODAL'}

def get_bones_list():
    """生成骨骼属性名称列表"""
    from ..bone_map_and_group import mmd_bone_map
    bone_list = {k: "" for k in mmd_bone_map.keys()}
    return bone_list

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

        # 设置 mmd_bone.name_j: .L/.R → 左/右 前缀格式（VMD 匹配用）
        if hasattr(bpy.types.PoseBone, 'mmd_bone'):
            for pb in obj.pose.bones:
                name = pb.name
                name_j = name
                if name.endswith('.L'):
                    base = name[:-2]
                    if base == '腰キャンセル':
                        name_j = base + '左'
                    else:
                        name_j = '左' + base
                elif name.endswith('.R'):
                    base = name[:-2]
                    if base == '腰キャンセル':
                        name_j = base + '右'
                    else:
                        name_j = '右' + base
                elif name.startswith('_dummy_') or name.startswith('_shadow_'):
                    name_j = ''
                pb.mmd_bone.name_j = name_j
            print("[CTMMD] Set mmd_bone.name_j for all bones (.L/.R → 左/右)")

            # 设置 D骨/腰キャンセル 的付与親（additional transform）
            # D骨跟随对应主骨旋转，腰キャンセル跟随腰（反转）
            ADDITIONAL_TRANSFORM_MAP = {
                "足D": ("足", 1.0),
                "ひざD": ("ひざ", 1.0),
                "足首D": ("足首", 1.0),
            }
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

            # 腰キャンセル: 付与親=下半身, 反転(-1.0)
            for suffix in [".L", ".R"]:
                cancel_name = "腰キャンセル" + suffix
                cancel_pb = obj.pose.bones.get(cancel_name)
                if cancel_pb and obj.pose.bones.get("下半身"):
                    cancel_pb.mmd_bone.additional_transform_bone = "下半身"
                    cancel_pb.mmd_bone.has_additional_rotation = True
                    cancel_pb.mmd_bone.has_additional_location = False
                    cancel_pb.mmd_bone.additional_transform_influence = -1.0

            print("[CTMMD] Set additional_transform for D-bones and 腰キャンセル")

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
