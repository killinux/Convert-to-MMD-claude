import bpy
from mathutils import Vector
from .. import bone_map_and_group
from .. import bone_utils
from .. import preset_operator


def _split_chain_weights(
    obj, src_name, dst_name, seg_from_name, seg_to_name,
    perp_threshold=1.5, src_keep_floor=0.0,
):
    """PMXEditor 风格两骨沿段插值: 把 src_name 顶点组按沿
    (seg_from_name.head → seg_to_name.head) 段的 t 位置分配到 dst_name。

    两种模式 (由 src_keep_floor 决定):
      * 转移模式 (src_keep_floor=0.0, 默认): 用于"插入中间骨"场景, 比如
        上半身2→上半身3, 顶点从 src 线性迁移到 dst, t=1 时 src 清零。
            src_new = w * (1 - k)
            dst_new += w * k
      * 追加模式 (src_keep_floor=1.0): 用于"相邻骨过渡"场景, 比如 肩→腕
        交接点, 顶点保留 src 原值同时追加 dst, 最终两骨共同支配该顶点
        (export 时 mmd_tools 会 normalize 到 sum=1)。
            src_new = w  (不变)
            dst_new += w * k
      * 中间值 (如 0.5): src 保留至少 50% 的 w, 同时 dst 按 k 累加。

    鲁棒性过滤: 计算顶点到段的垂直距离 perp, 只有
        perp / seg_length <= perp_threshold
    的顶点参与分权, 否则保持原样。避免 XPS 源里"衣服/下摆"等远离骨本体
    但错误挂在同一骨上的顶点被污染。

    典型用法:
      - ("上半身2", "上半身3", "上半身2", "首"):  转移模式 (默认)
      - ("肩.L",   "腕.L",    "肩.L",    "腕.L"):  追加模式 (src_keep_floor=1.0)
    返回 (处理顶点数, 被 perp 过滤的顶点数)。
    """
    src_keep_floor = max(0.0, min(1.0, src_keep_floor))
    src_b = obj.data.bones.get(seg_from_name)
    dst_b = obj.data.bones.get(seg_to_name)
    if not src_b or not dst_b:
        return (0, 0)
    seg_from = src_b.head_local
    seg_to = dst_b.head_local
    seg = seg_to - seg_from
    if seg.length_squared < 1e-9:
        return (0, 0)
    meshes = [
        m for m in bpy.data.objects
        if m.type == 'MESH' and any(
            mod.type == 'ARMATURE' and mod.object == obj for mod in m.modifiers
        )
    ]
    arm_mw = obj.matrix_world
    seg_from_w = arm_mw @ seg_from
    seg_to_w = arm_mw @ seg_to
    seg_w = seg_to_w - seg_from_w
    seg_len_sq_w = seg_w.length_squared
    if seg_len_sq_w < 1e-9:
        return (0, 0)
    perp_limit_sq = (perp_threshold * perp_threshold) * seg_len_sq_w
    moved = 0
    filtered = 0
    for m in meshes:
        src_vg = m.vertex_groups.get(src_name)
        if not src_vg:
            continue
        if dst_name not in m.vertex_groups:
            m.vertex_groups.new(name=dst_name)
        dst_vg = m.vertex_groups[dst_name]
        mesh_mw = m.matrix_world
        plans = []
        for v in m.data.vertices:
            src_w = 0.0
            existing_dst = 0.0
            for g in v.groups:
                if g.group == src_vg.index:
                    src_w = g.weight
                elif g.group == dst_vg.index:
                    existing_dst = g.weight
            if src_w <= 0:
                continue
            v_w = mesh_mw @ v.co
            rel = v_w - seg_from_w
            t = rel.dot(seg_w) / seg_len_sq_w
            t = max(0.0, min(1.0, t))
            if t <= 0:
                continue
            # 垂直距离² = |rel|² - (t·|seg|)²  (rel 已投影到段上)
            perp_sq = rel.length_squared - t * t * seg_len_sq_w
            if perp_sq > perp_limit_sq:
                filtered += 1
                continue
            k = t
            # src 保留下限 = src_keep_floor, 线性部分随 k 从 1 降到 (1 - (1-floor))
            src_factor = 1.0 - k * (1.0 - src_keep_floor)
            new_src = src_w * src_factor
            new_dst = existing_dst + src_w * k
            plans.append((v.index, new_src, new_dst))
        for v_idx, new_src, new_dst in plans:
            if new_src > 1e-6:
                src_vg.add([v_idx], new_src, 'REPLACE')
            else:
                src_vg.remove([v_idx])
            if new_dst > 1e-6:
                dst_vg.add([v_idx], new_dst, 'REPLACE')
            moved += 1
    return (moved, filtered)


def _split_upper_body_3_weights(obj):
    return _split_chain_weights(obj, "上半身2", "上半身3", "上半身2", "首")


def _split_shoulder_to_arm_weights(obj, side):
    """腋窝平滑: 把 肩.{side} 的顶点按沿 肩→腕 段 t 位置追加 腕.{side} 权重,
    同时保留 肩.{side} 原权重 (src_keep_floor=1.0, 追加模式)。这是 肩 和 腕
    相邻骨重叠区的正确做法: 交接点顶点同时由两根骨支配, export 时 mmd_tools
    会 normalize 到 BDEF2 sum=1, 最终 50/50 平滑过渡, 消除 XPS 源硬折痕。"""
    return _split_chain_weights(
        obj, f"肩.{side}", f"腕.{side}", f"肩.{side}", f"腕.{side}",
        src_keep_floor=1.0,
    )




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

        # XPS 通用兜底 rename 表: 把 XPS 已经存在的"位置和角色与 MMD 标准骨完全
        # 对应"的辅助骨直接重命名, 不新建/不迁移。
        #
        # 不在这里处理 twist 骨: 扭转骨 (foretwist / xtra07 / xtra07pp 等) 命名因模型
        # 而异, 且可能位置语义和 XPS 命名不一致。改由 step 2.1 (complete_twist_bones)
        # 按几何位置 + 权重匹配分配到 腕捩/手捩 槽位。
        UNUSED_RENAME_MAP = {
            "unused bip001 pelvis": "下半身",  # 胯部 -> MMD 下半身, 位置一致, 干净 rename
            # 常见 XPS 胸部命名 (用在 XNA Lara / DOA / Tomb Raider 系列)
            "boob left 1": "乳奶.L",
            "boob right 1": "乳奶.R",
            "breast left 1": "乳奶.L",
            "breast right 1": "乳奶.R",
        }
        for src, dst in UNUSED_RENAME_MAP.items():
            src_bone = obj.pose.bones.get(src)
            if src_bone and not obj.pose.bones.get(dst):
                src_bone.name = dst
                renamed.append(f"{src} -> {dst} (auto XPS helper)")

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
            "センター": {"head": Vector((0, 0, 0.8)), "tail": Vector((0, 0, 0.6)), "parent": "全ての親", "use_deform": False, "use_connect": False},
            "グルーブ": {"head": Vector((0, 0, 0.8)), "tail": Vector((0, 0, 0.9)), "parent": "センター", "use_deform": False, "use_connect": False},
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
            # 両目: display-only 控制骨 (parent=頭), 目.L/R 仍直接 parent=頭 (对齐 target PMX 约定)
            ("両目", ["目.L", "目.R", "頭"], lambda: {
                "head": (edit_bones["目.L"].head + edit_bones["目.R"].head) / 2 + Vector((0, -0.05, 0.04)),
                "tail": (edit_bones["目.L"].head + edit_bones["目.R"].head) / 2 + Vector((0, -0.10, 0.04)),
                "parent": "頭", "use_deform": False, "use_connect": False}),
            ("目.L", ["目.L", "頭"], lambda: {"head": edit_bones["目.L"].head, "tail": edit_bones["目.L"].tail, "parent": "頭", "use_connect": False}),
            ("目.R", ["目.R", "頭"], lambda: {"head": edit_bones["目.R"].head, "tail": edit_bones["目.R"].tail, "parent": "頭", "use_connect": False}),
            # 肩P.L/R: 肩的父骨骼, head 与 肩 同位置, tail +Z (MMD 惯例: 控制骨显示朝上)
            # 长度 0.082 XPS unit ≈ 1.0 PMX unit (export scale=12)
            ("肩P.L", ["肩.L"], lambda: {"head": edit_bones["肩.L"].head, "tail": edit_bones["肩.L"].head + Vector((0, 0, 0.082)), "parent": "上半身3", "use_deform": False, "use_connect": False}),
            ("肩P.R", ["肩.R"], lambda: {"head": edit_bones["肩.R"].head, "tail": edit_bones["肩.R"].head + Vector((0, 0, 0.082)), "parent": "上半身3", "use_deform": False, "use_connect": False}),
            # 肩.L/R: parent 改为肩P, 保留原 head/tail
            ("肩.L",  ["肩.L", "腕.L"],  lambda: {"head": edit_bones["肩.L"].head, "tail": edit_bones["腕.L"].head, "parent": "肩P.L", "use_connect": False}),
            ("肩.R",  ["肩.R", "腕.R"],  lambda: {"head": edit_bones["肩.R"].head, "tail": edit_bones["腕.R"].head, "parent": "肩P.R", "use_connect": False}),
            # 肩C.L/R: 肩的キャンセル骨. head = 肩 tail = 腕 head (同一点), tail +Z
            # 注意: 腕 和 肩C 共享 head 不是 tail! 以前版本用 use_connect=True + 小 tail 偏移
            # 的做法会把 腕.head snap 到 肩C.tail, 导致 腕 原位置被拉偏 0.03 单位。
            ("肩C.L", ["肩.L", "腕.L"], lambda: {"head": edit_bones["腕.L"].head, "tail": edit_bones["腕.L"].head + Vector((0, 0, 0.082)), "parent": "肩.L", "use_deform": False, "use_connect": False}),
            ("肩C.R", ["肩.R", "腕.R"], lambda: {"head": edit_bones["腕.R"].head, "tail": edit_bones["腕.R"].head + Vector((0, 0, 0.082)), "parent": "肩.R", "use_deform": False, "use_connect": False}),
            # 腕: parent = 肩C, use_connect=False (不要被 snap 到 肩C.tail)
            ("腕.L",  ["腕.L", "ひじ.L"], lambda: {"head": edit_bones["腕.L"].head, "tail": edit_bones["ひじ.L"].head, "parent": "肩C.L", "use_connect": False}),
            ("腕.R",  ["腕.R", "ひじ.R"], lambda: {"head": edit_bones["腕.R"].head, "tail": edit_bones["ひじ.R"].head, "parent": "肩C.R", "use_connect": False}),
            # ひじ: parent = 腕, use_connect=False (步骤 2.1 会把 parent 改为 腕捩, 提前 disconnect 避免 snap)
            ("ひじ.L", ["ひじ.L"],         lambda: {"head": edit_bones["ひじ.L"].head, "tail": edit_bones.get("手首.L").head if edit_bones.get("手首.L") else edit_bones["ひじ.L"].tail, "parent": "腕.L", "use_connect": False}),
            ("ひじ.R", ["ひじ.R"],         lambda: {"head": edit_bones["ひじ.R"].head, "tail": edit_bones.get("手首.R").head if edit_bones.get("手首.R") else edit_bones["ひじ.R"].tail, "parent": "腕.R", "use_connect": False}),
            # 腰キャンセル骨：抵消下半身旋转，腿部骨骼挂在这下面
            ("腰キャンセル.L", ["足.L"], lambda: {"head": edit_bones["足.L"].head, "tail": Vector((edit_bones["足.L"].head.x, edit_bones["足.L"].head.y, edit_bones["足.L"].head.z + 0.05)), "parent": "下半身", "use_connect": False, "use_deform": False}),
            ("腰キャンセル.R", ["足.R"], lambda: {"head": edit_bones["足.R"].head, "tail": Vector((edit_bones["足.R"].head.x, edit_bones["足.R"].head.y, edit_bones["足.R"].head.z + 0.05)), "parent": "下半身", "use_connect": False, "use_deform": False}),
            # 腿部骨骼：parent 挂到腰キャンセル
            ("足.L",  ["足.L", "ひざ.L"],  lambda: {"head": edit_bones["足.L"].head, "tail": edit_bones["ひざ.L"].head, "parent": "腰キャンセル.L", "use_connect": False}),
            ("足.R",  ["足.R", "ひざ.R"],  lambda: {"head": edit_bones["足.R"].head, "tail": edit_bones["ひざ.R"].head, "parent": "腰キャンセル.R", "use_connect": False}),
            ("ひざ.L", ["ひざ.L", "足首.L"], lambda: {"head": edit_bones["ひざ.L"].head, "tail": edit_bones["足首.L"].head, "parent": "足.L", "use_connect": False}),
            ("ひざ.R", ["ひざ.R", "足首.R"], lambda: {"head": edit_bones["ひざ.R"].head, "tail": edit_bones["足首.R"].head, "parent": "足.R", "use_connect": False}),
            ("足首.L", ["足首.L"],           lambda: {"head": edit_bones["足首.L"].head, "tail": edit_bones["つま先.L"].head.copy() if edit_bones.get("つま先.L") else Vector((edit_bones["足首.L"].head.x, edit_bones["足首.L"].head.y - 0.1, 0)), "parent": "ひざ.L", "use_connect": False}),
            ("足首.R", ["足首.R"],           lambda: {"head": edit_bones["足首.R"].head, "tail": edit_bones["つま先.R"].head.copy() if edit_bones.get("つま先.R") else Vector((edit_bones["足首.R"].head.x, edit_bones["足首.R"].head.y - 0.1, 0)), "parent": "ひざ.R", "use_connect": False}),
            # つま先: parent=足首
            ("つま先.L", ["つま先.L"], lambda: {"head": edit_bones["つま先.L"].head, "tail": edit_bones["つま先.L"].tail, "parent": "足首.L", "use_connect": False}),
            ("つま先.R", ["つま先.R"], lambda: {"head": edit_bones["つま先.R"].head, "tail": edit_bones["つま先.R"].tail, "parent": "足首.R", "use_connect": False}),
            # ダミー.L/R: MMD 手首末端配饰挂点骨, 无权重无付与親, parent=手首
            # head 位于 手首 head 稍往手方向偏移一点, tail 再沿同方向延伸
            ("ダミー.L", ["手首.L"], lambda: {
                "head": edit_bones["手首.L"].head + (edit_bones["手首.L"].tail - edit_bones["手首.L"].head).normalized() * 0.082,
                "tail": edit_bones["手首.L"].head + (edit_bones["手首.L"].tail - edit_bones["手首.L"].head).normalized() * 0.164,
                "parent": "手首.L", "use_deform": False, "use_connect": False}),
            ("ダミー.R", ["手首.R"], lambda: {
                "head": edit_bones["手首.R"].head + (edit_bones["手首.R"].tail - edit_bones["手首.R"].head).normalized() * 0.082,
                "tail": edit_bones["手首.R"].head + (edit_bones["手首.R"].tail - edit_bones["手首.R"].head).normalized() * 0.164,
                "parent": "手首.R", "use_deform": False, "use_connect": False}),
            # 手指0骨 (指根): 手首と指1の中間に作成，指1をre-parent
            ("人指０.L", ["手首.L", "人指１.L"], lambda: {"head": (edit_bones["手首.L"].head + edit_bones["人指１.L"].head) / 2, "tail": edit_bones["人指１.L"].head, "parent": "手首.L", "use_connect": False}),
            ("人指０.R", ["手首.R", "人指１.R"], lambda: {"head": (edit_bones["手首.R"].head + edit_bones["人指１.R"].head) / 2, "tail": edit_bones["人指１.R"].head, "parent": "手首.R", "use_connect": False}),
            ("人指１.L", ["人指１.L"], lambda: {"head": edit_bones["人指１.L"].head, "tail": edit_bones["人指１.L"].tail, "parent": "人指０.L", "use_connect": False}),
            ("人指１.R", ["人指１.R"], lambda: {"head": edit_bones["人指１.R"].head, "tail": edit_bones["人指１.R"].tail, "parent": "人指０.R", "use_connect": False}),
            ("中指０.L", ["手首.L", "中指１.L"], lambda: {"head": (edit_bones["手首.L"].head + edit_bones["中指１.L"].head) / 2, "tail": edit_bones["中指１.L"].head, "parent": "手首.L", "use_connect": False}),
            ("中指０.R", ["手首.R", "中指１.R"], lambda: {"head": (edit_bones["手首.R"].head + edit_bones["中指１.R"].head) / 2, "tail": edit_bones["中指１.R"].head, "parent": "手首.R", "use_connect": False}),
            ("中指１.L", ["中指１.L"], lambda: {"head": edit_bones["中指１.L"].head, "tail": edit_bones["中指１.L"].tail, "parent": "中指０.L", "use_connect": False}),
            ("中指１.R", ["中指１.R"], lambda: {"head": edit_bones["中指１.R"].head, "tail": edit_bones["中指１.R"].tail, "parent": "中指０.R", "use_connect": False}),
            ("薬指０.L", ["手首.L", "薬指１.L"], lambda: {"head": (edit_bones["手首.L"].head + edit_bones["薬指１.L"].head) / 2, "tail": edit_bones["薬指１.L"].head, "parent": "手首.L", "use_connect": False}),
            ("薬指０.R", ["手首.R", "薬指１.R"], lambda: {"head": (edit_bones["手首.R"].head + edit_bones["薬指１.R"].head) / 2, "tail": edit_bones["薬指１.R"].head, "parent": "手首.R", "use_connect": False}),
            ("薬指１.L", ["薬指１.L"], lambda: {"head": edit_bones["薬指１.L"].head, "tail": edit_bones["薬指１.L"].tail, "parent": "薬指０.L", "use_connect": False}),
            ("薬指１.R", ["薬指１.R"], lambda: {"head": edit_bones["薬指１.R"].head, "tail": edit_bones["薬指１.R"].tail, "parent": "薬指０.R", "use_connect": False}),
            ("小指０.L", ["手首.L", "小指１.L"], lambda: {"head": (edit_bones["手首.L"].head + edit_bones["小指１.L"].head) / 2, "tail": edit_bones["小指１.L"].head, "parent": "手首.L", "use_connect": False}),
            ("小指０.R", ["手首.R", "小指１.R"], lambda: {"head": (edit_bones["手首.R"].head + edit_bones["小指１.R"].head) / 2, "tail": edit_bones["小指１.R"].head, "parent": "手首.R", "use_connect": False}),
            ("小指１.L", ["小指１.L"], lambda: {"head": edit_bones["小指１.L"].head, "tail": edit_bones["小指１.L"].tail, "parent": "小指０.L", "use_connect": False}),
            ("小指１.R", ["小指１.R"], lambda: {"head": edit_bones["小指１.R"].head, "tail": edit_bones["小指１.R"].tail, "parent": "小指０.R", "use_connect": False}),
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
        # 隐藏技术骨 (MMD 惯例): 肩C 是 cancel 骨, 通过 付与親 抵消 肩P 旋转,
        # 用户不应直接操作, 因此在 pose mode 隐藏 (只有 edit mode 能看到)。
        # 肩P / ダミー 虽然也是控制骨但用户需要能看到/选中, 保持 hide=False。
        for n in ("肩C.L", "肩C.R"):
            b = obj.data.bones.get(n)
            if b:
                b.hide = True

        # 如果刚创建了 上半身3 (XPS 源无对应骨), 把 上半身2 的顶点按沿段 t 位置
        # 线性分摊给 上半身3, 使 VMD 的 上半身3 键帧真正生效。不跑这步的话
        # 上半身3 在 conv 里会是零权重空骨, target PMX 约 10900 verts 挂在这个骨上。
        if "上半身3" in created_bones:
            n_split, n_filt = _split_upper_body_3_weights(obj)
            print(f"[CTMMD 2] 上半身3 auto-weight: {n_split} verts split from 上半身2 ({n_filt} filtered by perp)")

        # 腋窝平滑: 把 肩.L/R 沿 肩→腕 段的顶点线性分摊给 腕.L/R, 让靠近 腕 那端的
        # 顶点跟随上臂旋转, 消除 XPS 源单骨硬绑定的肩-腕折痕 (在抬手姿态最明显)。
        # target PMX 的腋窝顶点几乎全部同时挂 肩+腕+上半身3, 这个分权把 conv 的
        # 单骨分布向目标的多骨混权靠拢。perp 过滤保证跨身体污染的顶点不参与。
        for side in ("L", "R"):
            if f"肩.{side}" in obj.data.bones and f"腕.{side}" in obj.data.bones:
                n, n_filt = _split_shoulder_to_arm_weights(obj, side)
                if n > 0 or n_filt > 0:
                    print(f"[CTMMD 2] 腋窝 肩→腕.{side} auto-weight: {n} verts split ({n_filt} filtered by perp)")

        self.report({'INFO'}, f"Bone completion finished: created {len(created_bones)}, updated {len(updated_bones)}")

        return {'FINISHED'}


def _convert_name_lr_to_jp(name):
    """将 .L/.R 后缀转为 左/右 前缀。非对称骨骼原样返回。"""
    if name.endswith('.L'):
        base = name[:-2]
        return (base + '左') if base == '腰キャンセル' else ('左' + base)
    elif name.endswith('.R'):
        base = name[:-2]
        return (base + '右') if base == '腰キャンセル' else ('右' + base)
    return name


def _convert_name_jp_to_lr(name):
    """将 左/右 前缀转为 .L/.R 后缀。非对称骨骼原样返回。"""
    if name.endswith('左') and name.startswith('腰キャンセル'):
        return name[:-1] + '.L'
    if name.endswith('右') and name.startswith('腰キャンセル'):
        return name[:-1] + '.R'
    if name.startswith('左'):
        return name[1:] + '.L'
    if name.startswith('右'):
        return name[1:] + '.R'
    return name


class OBJECT_OT_convert_names_to_lr(bpy.types.Operator):
    """骨骼名 左/右 → .L/.R（Blender 镜像友好格式）"""
    bl_idname = "object.convert_names_to_lr"
    bl_label = "Names: 左右 → .L/.R"

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "No armature selected")
            return {'CANCELLED'}

        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        count = 0
        for bone in obj.pose.bones:
            new_name = _convert_name_jp_to_lr(bone.name)
            if new_name != bone.name:
                bone.name = new_name
                count += 1

        self.report({'INFO'}, f"Converted {count} bones to .L/.R format")
        return {'FINISHED'}


class OBJECT_OT_convert_names_to_jp(bpy.types.Operator):
    """骨骼名 .L/.R → 左/右（PMX/VMD 日文格式）"""
    bl_idname = "object.convert_names_to_jp"
    bl_label = "Names: .L/.R → 左右"

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "No armature selected")
            return {'CANCELLED'}

        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        count = 0
        for bone in obj.pose.bones:
            new_name = _convert_name_lr_to_jp(bone.name)
            if new_name != bone.name:
                bone.name = new_name
                count += 1

        self.report({'INFO'}, f"Converted {count} bones to 左/右 format")
        return {'FINISHED'}
