import bpy
from mathutils import Vector
from math import radians
from .. import bone_utils

# IK约束相关函数
def add_ik_constraint(bone, target, subtarget, chain_count, iterations, ik_min_x=None, ik_max_x=None, use_ik_limit_x=False, ik_min_y=0, ik_max_y=0, use_ik_limit_y=False, ik_min_z=0, ik_max_z=0, use_ik_limit_z=False):
    ik_constraint = bone.constraints.new(type='IK')
    ik_constraint.name = "IK"
    ik_constraint.target = target
    ik_constraint.subtarget = subtarget
    ik_constraint.chain_count = chain_count
    ik_constraint.iterations = iterations
    
    # 设置X轴限制
    if ik_min_x is not None:
        bone.ik_min_x = ik_min_x
    if ik_max_x is not None:
        bone.ik_max_x = ik_max_x
    bone.use_ik_limit_x = use_ik_limit_x
    
    # 设置Y轴限制
    if ik_min_y is not None:
        bone.ik_min_y = ik_min_y
    if ik_max_y is not None:
        bone.ik_max_y = ik_max_y
    bone.use_ik_limit_y = use_ik_limit_y
    
    # 设置Z轴限制
    if ik_min_z is not None:
        bone.ik_min_z = ik_min_z
    if ik_max_z is not None:
        bone.ik_max_z = ik_max_z
    bone.use_ik_limit_z = use_ik_limit_z

def add_limit_rotation_constraint(bone, influence=1, use_limit_x=False, min_x=None, max_x=None, owner_space='LOCAL'):
    limit_constraint = bone.constraints.new(type='LIMIT_ROTATION')
    limit_constraint.name = "mmd_ik_limit_override"
    limit_constraint.influence = influence
    limit_constraint.use_limit_x = use_limit_x
    limit_constraint.owner_space = owner_space
    
    if min_x is not None:
        limit_constraint.min_x = min_x
    if max_x is not None:
        limit_constraint.max_x = max_x

def add_damped_track_constraint(bone, target, subtarget, influence=0):
    damped_track_constraint = bone.constraints.new(type='DAMPED_TRACK')
    damped_track_constraint.name = "mmd_ik_target_override"
    damped_track_constraint.target = target
    damped_track_constraint.subtarget = subtarget
    damped_track_constraint.influence = influence

# IK操作类
class OBJECT_OT_add_ik(bpy.types.Operator):
    """为骨架添加MMD IK"""
    bl_idname = "object.add_mmd_ik"
    bl_label = "Add MMD IK"

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "No armature object selected")
            return {'CANCELLED'}

        if context.mode != 'EDIT_ARMATURE':
            bpy.ops.object.mode_set(mode='EDIT')

        edit_bones = obj.data.edit_bones
        required_bones = ['ひざ.L', 'ひざ.R', '足首.L', '足首.R', '全ての親']
        missing_bones = [name for name in required_bones if name not in edit_bones]
        if missing_bones:
            self.report({'ERROR'}, f"Missing required bones: {', '.join(missing_bones)}. Run Step 2 first.")
            return {'CANCELLED'}

        # IK骨骼属性定义
        IKbone_properties = {
            "足IK親.L": {"head": Vector((edit_bones["ひざ.L"].tail.x, edit_bones["ひざ.L"].tail.y, 0)),
                       "tail": edit_bones["ひざ.L"].tail, "parent": "全ての親", "use_connect": False},
            "足ＩＫ.L": {"head": edit_bones["ひざ.L"].tail,
                      "tail": edit_bones["ひざ.L"].tail + Vector((0, 0.1, 0)), "parent": "足IK親.L", "use_connect": False},
            "つま先ＩＫ.L": {"head": edit_bones["足首.L"].tail,
                         "tail": edit_bones["足首.L"].tail + Vector((0, 0, -0.05)), "parent": "足ＩＫ.L", "use_connect": False},
            "足IK親.R": {"head": Vector((edit_bones["ひざ.R"].tail.x, edit_bones["ひざ.R"].tail.y, 0)),
                       "tail": edit_bones["ひざ.R"].tail, "parent": "全ての親", "use_connect": False},
            "足ＩＫ.R": {"head": edit_bones["ひざ.R"].tail,
                      "tail": edit_bones["ひざ.R"].tail + Vector((0, 0.1, 0)), "parent": "足IK親.R", "use_connect": False},
            "つま先ＩＫ.R": {"head": edit_bones["足首.R"].tail,
                         "tail": edit_bones["足首.R"].tail + Vector((0, 0, -0.05)), "parent": "足ＩＫ.R", "use_connect": False}
        }

        # 创建IK骨骼
        for bone_name, properties in IKbone_properties.items():
            bone_utils.create_or_update_bone(edit_bones, bone_name, properties["head"], properties["tail"], use_connect=False, parent_name=properties["parent"], use_deform=False)
        # 切换到姿态模式
        bpy.ops.object.mode_set(mode='POSE')

        # 获取骨骼对象并添加约束
        left_hiza = obj.pose.bones["ひざ.L"]
        left_kutu = obj.pose.bones["足首.L"]
        right_hiza = obj.pose.bones["ひざ.R"]
        right_kutu = obj.pose.bones["足首.R"]

        # 为ひざ添加 IK 和旋转限制约束
        add_ik_constraint(left_hiza, obj, "足ＩＫ.L", 2, 200, ik_min_x=radians(0), ik_max_x=radians(180), use_ik_limit_x=True,use_ik_limit_y=True,use_ik_limit_z=True)
        add_limit_rotation_constraint(left_hiza, use_limit_x=True, min_x=radians(0.5), max_x=radians(180))

        add_ik_constraint(right_hiza, obj, "足ＩＫ.R", 2, 200, ik_min_x=radians(0), ik_max_x=radians(180), use_ik_limit_x=True,use_ik_limit_y=True,use_ik_limit_z=True)
        add_limit_rotation_constraint(right_hiza, use_limit_x=True, min_x=radians(0.5), max_x=radians(180))

        add_ik_constraint(left_kutu, obj, "つま先ＩＫ.L", 1, 200)
        add_damped_track_constraint(left_kutu, obj, "ひざ.L")

        add_ik_constraint(right_kutu, obj, "つま先ＩＫ.R", 1, 200)
        add_damped_track_constraint(right_kutu, obj, "ひざ.R")

        # ─── Shadow/Dummy 三层约束机制 ───
        # PMX 标准: dummy(挂主骨) → shadow(COPY_TRANSFORMS) → D骨(TRANSFORM)
        bpy.ops.object.mode_set(mode='EDIT')
        edit_bones = obj.data.edit_bones
        from math import pi

        SHADOW_DUMMY_DEFS = [
            # (D骨名, 主骨名)
            ("足D.L",  "足.L"),
            ("足D.R",  "足.R"),
            ("ひざD.L", "ひざ.L"),
            ("ひざD.R", "ひざ.R"),
            ("足首D.L", "足首.L"),
            ("足首D.R", "足首.R"),
        ]

        CANCEL_DEFS = [
            # (cancel名, dummy_parent, shadow_parent)
            ("腰キャンセル.L", "腰", "グルーブ"),
            ("腰キャンセル.R", "腰", "グルーブ"),
        ]

        # 腰キャンセル的 dummy/shadow 骨骼
        for cancel_name, dummy_par, shadow_par in CANCEL_DEFS:
            cancel_eb = edit_bones.get(cancel_name)
            if not cancel_eb:
                continue
            for prefix, par in [("_dummy_", dummy_par), ("_shadow_", shadow_par)]:
                name = prefix + cancel_name
                if not edit_bones.get(name):
                    bone_utils.create_or_update_bone(edit_bones, name,
                        cancel_eb.head.copy(), cancel_eb.tail.copy(),
                        use_connect=False, parent_name=par, use_deform=False)

        # D骨的 dummy/shadow 骨骼
        for d_name, main_name in SHADOW_DUMMY_DEFS:
            d_eb = edit_bones.get(d_name)
            main_eb = edit_bones.get(main_name)
            if not d_eb or not main_eb:
                continue
            # dummy 挂在主骨下
            dummy_name = "_dummy_" + d_name
            if not edit_bones.get(dummy_name):
                bone_utils.create_or_update_bone(edit_bones, dummy_name,
                    d_eb.head.copy(), d_eb.tail.copy(),
                    use_connect=False, parent_name=main_name, use_deform=False)
            # shadow 挂在主骨的父骨骼下（和 D 骨的父骨骼一致）
            shadow_name = "_shadow_" + d_name
            shadow_par = main_eb.parent.name if main_eb.parent else None
            if not edit_bones.get(shadow_name):
                bone_utils.create_or_update_bone(edit_bones, shadow_name,
                    d_eb.head.copy(), d_eb.tail.copy(),
                    use_connect=False, parent_name=shadow_par, use_deform=False)

        bpy.ops.object.mode_set(mode='POSE')

        # shadow ← COPY_TRANSFORMS ← dummy
        all_defs = [(d, m) for d, m in SHADOW_DUMMY_DEFS]
        all_defs += [(c, None) for c, _, _ in CANCEL_DEFS]
        for d_name, _ in all_defs:
            shadow_pb = obj.pose.bones.get("_shadow_" + d_name)
            if shadow_pb and not any(c.type == 'COPY_TRANSFORMS' for c in shadow_pb.constraints):
                ct = shadow_pb.constraints.new(type='COPY_TRANSFORMS')
                ct.name = "mmd_shadow_copy"
                ct.target = obj
                ct.subtarget = "_dummy_" + d_name

        # D骨/腰キャンセル ← TRANSFORM ← shadow (rotation 1:1)
        for d_name, _ in SHADOW_DUMMY_DEFS:
            d_pb = obj.pose.bones.get(d_name)
            if d_pb and not any(c.type == 'TRANSFORM' for c in d_pb.constraints):
                tf = d_pb.constraints.new(type='TRANSFORM')
                tf.name = "mmd_additional_rotation"
                tf.target = obj
                tf.subtarget = "_shadow_" + d_name
                tf.target_space = 'LOCAL'
                tf.owner_space = 'LOCAL'
                tf.map_from = 'ROTATION'
                tf.map_to = 'ROTATION'
                tf.from_min_x_rot = -pi; tf.from_max_x_rot = pi
                tf.from_min_y_rot = -pi; tf.from_max_y_rot = pi
                tf.from_min_z_rot = -pi; tf.from_max_z_rot = pi
                tf.to_min_x_rot = -pi; tf.to_max_x_rot = pi
                tf.to_min_y_rot = -pi; tf.to_max_y_rot = pi
                tf.to_min_z_rot = -pi; tf.to_max_z_rot = pi

        # 腰キャンセル ← TRANSFORM ← shadow (反转旋转：抵消下半身)
        for cancel_name, _, _ in CANCEL_DEFS:
            cancel_pb = obj.pose.bones.get(cancel_name)
            if cancel_pb and not any(c.type == 'TRANSFORM' for c in cancel_pb.constraints):
                tf = cancel_pb.constraints.new(type='TRANSFORM')
                tf.name = "mmd_additional_rotation"
                tf.target = obj
                tf.subtarget = "_shadow_" + cancel_name
                tf.target_space = 'LOCAL'
                tf.owner_space = 'LOCAL'
                tf.map_from = 'ROTATION'
                tf.map_to = 'ROTATION'
                tf.from_min_x_rot = -pi; tf.from_max_x_rot = pi
                tf.from_min_y_rot = -pi; tf.from_max_y_rot = pi
                tf.from_min_z_rot = -pi; tf.from_max_z_rot = pi
                tf.to_min_x_rot = pi; tf.to_max_x_rot = -pi
                tf.to_min_y_rot = pi; tf.to_max_y_rot = -pi
                tf.to_min_z_rot = pi; tf.to_max_z_rot = -pi

        print("[CTMMD 6] Shadow/dummy mechanism created")
        return {'FINISHED'}
