print("[Convert-to-MMD] ====== Module loading ======")

bl_info = {
    "name": "Convert to MMD",
    "author": "haha(hehe)",
    "version": (2, 2),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar",
    "description": "Plugin to automatically rename and complete missing bones for MMD format",
    "warning": "",
    "wiki_url": "",
    "category": "Animation"
}

import bpy
import os  # 新增：导入os模块

from .operators import preset_operator
from .operators import bone_operator
from .operators import collection_operator
from .operators import ik_operator
from .operators import pose_operator
from .operators import leg_operator
from .operators import twist_operator
from .operators import physics_operator
from .operators import face_operator
from . import ui_panel
from . import bone_map_and_group
from . import bone_utils
def register_properties(properties_dict):
    """Registers properties dynamically using a dictionary."""
    for prop_name, prop_value in properties_dict.items():
        setattr(bpy.types.Scene, prop_name, bpy.props.StringProperty(default=prop_value))


def unregister_properties(properties_list):
    """Unregisters properties dynamically using a list of property names."""
    for prop_name in properties_list:
        if hasattr(bpy.types.Scene, prop_name):
            delattr(bpy.types.Scene, prop_name)

def _safe_register(cls):
    try:
        bpy.utils.unregister_class(cls)
    except RuntimeError:
        pass
    bpy.utils.register_class(cls)

def register():
    print("[Convert-to-MMD] ====== Plugin register() called ======")
    # 注册所有类
    _safe_register(ui_panel.OBJECT_PT_skeleton_hierarchy)
    _safe_register(ui_panel.OBJECT_OT_load_preset)
    _safe_register(bone_operator.OBJECT_OT_rename_to_mmd)
    _safe_register(bone_operator.OBJECT_OT_complete_missing_bones)
    _safe_register(bone_operator.OBJECT_OT_convert_names_to_lr)
    _safe_register(bone_operator.OBJECT_OT_convert_names_to_jp)
    _safe_register(preset_operator.OBJECT_OT_fill_from_selection_specific)
    _safe_register(preset_operator.OBJECT_OT_export_preset)
    _safe_register(preset_operator.OBJECT_OT_import_preset)
    _safe_register(preset_operator.OBJECT_OT_setup_pmx_attributes)
    _safe_register(preset_operator.OBJECT_OT_use_mmd_tools_convert)
    _safe_register(preset_operator.OBJECT_OT_one_click_convert)
    _safe_register(pose_operator.OBJECT_OT_convert_to_apose)
    _safe_register(pose_operator.OBJECT_OT_fix_forearm_bend)
    _safe_register(pose_operator.OBJECT_OT_align_arms_to_reference)
    _safe_register(pose_operator.OBJECT_OT_align_fingers_to_reference)
    _safe_register(ik_operator.OBJECT_OT_add_ik)
    _safe_register(collection_operator.OBJECT_OT_create_bone_group)
    _safe_register(twist_operator.OBJECT_OT_complete_twist_bones)
    _safe_register(twist_operator.OBJECT_OT_split_upper_arm_twist_weights)
    _safe_register(twist_operator.OBJECT_OT_split_forearm_twist_weights)
    _safe_register(physics_operator.OBJECT_OT_setup_physics)
    _safe_register(physics_operator.OBJECT_OT_extract_physics_template)
    _safe_register(physics_operator.OBJECT_OT_toggle_rigid_visibility)
    _safe_register(physics_operator.OBJECT_OT_apply_breast_physics)
    _safe_register(face_operator.OBJECT_OT_cleanup_face_bones)
    _safe_register(leg_operator.OBJECT_OT_complete_d_bones)
    _safe_register(leg_operator.OBJECT_OT_complete_hip_cancel_bones)
    _safe_register(leg_operator.OBJECT_OT_assign_weights)
    _safe_register(leg_operator.OBJECT_OT_assign_weights_phase1)
    _safe_register(leg_operator.OBJECT_OT_assign_weights_phase2)
    _safe_register(leg_operator.OBJECT_OT_assign_weights_phase3)
    _safe_register(leg_operator.OBJECT_OT_assign_weights_phase4)
    _safe_register(leg_operator.OBJECT_OT_assign_weights_phase5)
    _safe_register(leg_operator.OBJECT_OT_assign_weights_phase6)
    _safe_register(leg_operator.OBJECT_OT_assign_upper3_weights)
    # 注册动态属性
    bones = preset_operator.get_bones_list()
    register_properties(bones)

    # 注册 EnumProperty
    bpy.types.Scene.preset_enum = bpy.props.EnumProperty(
        name="预设",
        description="选择一个预设",
        items=get_preset_enum,
        update=preset_enum_update  # 使用显式函数替代 lambda
    )
    bpy.types.Scene.my_enum = bpy.props.EnumProperty(
        name="模式",
        description="选择操作模式",
        items=[
            ('option1', "骨骼映射", "主转换流程 (骨骼重命名/权重/IK/导出)"),
            ('option2', "物理+表情", "刚体/胸部物理、表情 morph 编辑")
        ],
        default='option1'
    )
    bpy.types.Scene.ctmmd_show_preprocessing = bpy.props.BoolProperty(
        name="显示预处理", default=False
    )
    bpy.types.Scene.ctmmd_show_advanced = bpy.props.BoolProperty(
        name="显示高级/调试", default=False
    )

def _safe_unregister(cls):
    try:
        bpy.utils.unregister_class(cls)
    except RuntimeError:
        pass

def unregister():
    # 注销所有类
    _safe_unregister(ui_panel.OBJECT_PT_skeleton_hierarchy)
    _safe_unregister(ui_panel.OBJECT_OT_load_preset)
    _safe_unregister(bone_operator.OBJECT_OT_rename_to_mmd)
    _safe_unregister(bone_operator.OBJECT_OT_complete_missing_bones)
    _safe_unregister(preset_operator.OBJECT_OT_fill_from_selection_specific)
    _safe_unregister(preset_operator.OBJECT_OT_export_preset)
    _safe_unregister(preset_operator.OBJECT_OT_import_preset)
    _safe_unregister(preset_operator.OBJECT_OT_use_mmd_tools_convert)
    _safe_unregister(preset_operator.OBJECT_OT_one_click_convert)
    _safe_unregister(pose_operator.OBJECT_OT_convert_to_apose)
    _safe_unregister(pose_operator.OBJECT_OT_fix_forearm_bend)
    _safe_unregister(pose_operator.OBJECT_OT_align_arms_to_reference)
    _safe_unregister(pose_operator.OBJECT_OT_align_fingers_to_reference)
    _safe_unregister(ik_operator.OBJECT_OT_add_ik)
    _safe_unregister(collection_operator.OBJECT_OT_create_bone_group)
    _safe_unregister(leg_operator.OBJECT_OT_complete_d_bones)
    _safe_unregister(leg_operator.OBJECT_OT_complete_hip_cancel_bones)
    _safe_unregister(leg_operator.OBJECT_OT_assign_weights)
    _safe_unregister(leg_operator.OBJECT_OT_assign_weights_phase1)
    _safe_unregister(leg_operator.OBJECT_OT_assign_weights_phase2)
    _safe_unregister(leg_operator.OBJECT_OT_assign_weights_phase3)
    _safe_unregister(leg_operator.OBJECT_OT_assign_weights_phase4)
    _safe_unregister(leg_operator.OBJECT_OT_assign_weights_phase5)
    _safe_unregister(leg_operator.OBJECT_OT_assign_weights_phase6)
    _safe_unregister(leg_operator.OBJECT_OT_assign_upper3_weights)
    _safe_unregister(twist_operator.OBJECT_OT_complete_twist_bones)
    _safe_unregister(twist_operator.OBJECT_OT_split_upper_arm_twist_weights)
    _safe_unregister(twist_operator.OBJECT_OT_split_forearm_twist_weights)
    _safe_unregister(physics_operator.OBJECT_OT_setup_physics)
    _safe_unregister(physics_operator.OBJECT_OT_extract_physics_template)
    _safe_unregister(physics_operator.OBJECT_OT_toggle_rigid_visibility)
    _safe_unregister(physics_operator.OBJECT_OT_apply_breast_physics)
    _safe_unregister(face_operator.OBJECT_OT_cleanup_face_bones)
    del bpy.types.Scene.my_enum
    if hasattr(bpy.types.Scene, "ctmmd_show_preprocessing"):
        del bpy.types.Scene.ctmmd_show_preprocessing
    if hasattr(bpy.types.Scene, "ctmmd_show_advanced"):
        del bpy.types.Scene.ctmmd_show_advanced
    # 注销动态属性
    bones = preset_operator.get_bones_list()
    unregister_properties(bones)

    # 注销 EnumProperty
    if hasattr(bpy.types.Scene, "preset_enum"):
        delattr(bpy.types.Scene, "preset_enum")

# 新增 EnumProperty 定义
def get_preset_enum(self, context):
    # 修改: 确保路径解析正确，使用bpy.utils.script_path_user()获取用户脚本目录
    script_dir = os.path.dirname(os.path.realpath(__file__))
    presets_dir = os.path.join(script_dir, "presets")
    preset_items = []
    if os.path.exists(presets_dir):
        for preset_file in os.listdir(presets_dir):
            if preset_file.endswith('.json'):
                # 修改: 使用文件名作为选项的标识符
                preset_name = os.path.splitext(preset_file)[0]
                preset_items.append((preset_name, preset_name, ""))
    return preset_items

# 修改: 将 update 回调函数改为显式函数定义
def preset_enum_update(self, context):
    # 调用加载预设的操作符
    bpy.ops.object.load_preset(preset_name=self.preset_enum)
    return None  # 确保返回值为 None

if __name__ == "__main__":
    register()