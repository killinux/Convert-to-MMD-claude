"""
Upper-arm / forearm twist bone system (position-based, XPS-agnostic).

为什么要位置识别而不是硬编码骨名:
  XPS 源模型的 twist/辅助骨命名随作者而变 (foretwist / xtra07 / xtra07pp / ...)。
  本算法通过"几何位置 + 权重"扫描出 twist 候选骨, 按沿臂段的 t 值就近分配到
  标准 MMD 槽位 (腕捩 / 腕捩1/2/3 / 手捩 / 手捩1/2/3), 以 rename 为首选手段,
  保留 XPS 原有权重不做切分。槽位无候选时创建空骨, 保持结构完整。
"""

import bpy
from mathutils import Vector
from .. import bone_utils

# 每段产生 1 根主骨 + sub_count 根子骨, 子骨在 sub_ts 位置并取主骨 付与親 的对应影响值
TWIST_SEGMENTS = [
    # (seg_from_base, seg_to_base, main_base, sub_count, main_t, sub_ts)
    ("腕",  "ひじ", "腕捩", 3, 0.60, (0.25, 0.50, 0.75)),
    ("ひじ", "手首", "手捩", 3, 0.60, (0.25, 0.50, 0.75)),
]

TWIST_BONE_LENGTH_RATIO = 0.48  # sub twist 显示长度 = 段长 × 此比例 (原 0.082 / ~0.17 段长)
PERP_THRESHOLD_RATIO = 0.3  # 候选骨 head 到段的垂直距离 < 段长 * 比率 才算命中段
T_RANGE = (-0.1, 1.2)       # 允许 head 投影稍微超出 [0,1]
Z_UP = Vector((0, 0, 1))    # MMD twist/控制骨显示方向惯例: 沿 +Z 长度 1


def _detect_side_format(armature):
    """返回 'prefix' (左/右) 或 'suffix' (.L/.R)"""
    bones = armature.data.bones
    if bones.get("左腕") or bones.get("左ひじ"):
        return "prefix"
    return "suffix"


def _side_name(base, side_fmt, side):
    """side='L' or 'R'"""
    if side_fmt == "prefix":
        return ("左" if side == "L" else "右") + base
    return base + "." + side


def _closest_on_segment(point, seg_from, seg_to):
    """返回 (t, perp_dist). t 是沿段参数 (未 clamp), perp_dist 是点到线段的距离"""
    seg = seg_to - seg_from
    L_sq = seg.length_squared
    if L_sq < 1e-8:
        return 0.0, (point - seg_from).length
    t = (point - seg_from).dot(seg) / L_sq
    t_clamped = max(0.0, min(1.0, t))
    proj = seg_from + t_clamped * seg
    return t, (point - proj).length


def _vg_weight_count(mesh_obj, vg_name):
    vg = mesh_obj.vertex_groups.get(vg_name)
    if not vg:
        return 0
    return sum(
        1 for v in mesh_obj.data.vertices
        for g in v.groups if g.group == vg.index and g.weight > 0.001
    )


def _vg_weighted_t_mean(mesh_obj, vg_name, seg_from_ws, seg_to_ws, mw):
    """返回指定 vgroup 所有权重顶点沿段的加权平均 t (世界空间)"""
    vg = mesh_obj.vertex_groups.get(vg_name)
    if not vg:
        return None
    seg = seg_to_ws - seg_from_ws
    L_sq = seg.length_squared
    if L_sq < 1e-8:
        return None
    total_w = 0.0
    total_wt = 0.0
    for v in mesh_obj.data.vertices:
        w = 0.0
        for g in v.groups:
            if g.group == vg.index:
                w = g.weight
                break
        if w <= 0.001:
            continue
        vw = mw @ v.co
        t = max(0.0, min(1.0, (vw - seg_from_ws).dot(seg) / L_sq))
        total_w += w
        total_wt += w * t
    if total_w <= 0:
        return None
    return total_wt / total_w


def _mmd_target_names():
    """MMD 标准骨名集合 (用于排除候选)"""
    from .. import bone_map_and_group
    names = set(bone_map_and_group.mmd_bone_map.values())
    # 加入本操作要创建/使用的 twist 相关名称
    for base in ("腕捩", "手捩"):
        for suf in (".L", ".R"):
            names.add(base + suf)
            for i in (1, 2, 3):
                names.add(f"{base}{i}{suf}")
    # 常见结构骨
    names.update({"操作中心", "グルーブ", "腰", "上半身3", "首1", "両目",
                  "肩P.L", "肩P.R", "肩C.L", "肩C.R",
                  "腰キャンセル.L", "腰キャンセル.R",
                  "足D.L", "足D.R", "ひざD.L", "ひざD.R",
                  "足首D.L", "足首D.R", "足先EX.L", "足先EX.R",
                  "乳奶.L", "乳奶.R", "ダミー.L", "ダミー.R"})
    return names


def _scan_candidates(armature, mesh_objects, segment_name_pair, side):
    """
    扫描骨架, 返回命中指定段的候选列表:
      [(bone_name, t_head, t_weighted, weight_count, head_world, length), ...]
    """
    seg_from_name, seg_to_name = segment_name_pair
    eb_from = armature.data.bones.get(seg_from_name)
    eb_to = armature.data.bones.get(seg_to_name)
    if not eb_from or not eb_to:
        return [], None, None

    mw = armature.matrix_world
    seg_from_ws = mw @ eb_from.head_local
    seg_to_ws = mw @ eb_to.head_local
    seg_length = (seg_to_ws - seg_from_ws).length
    if seg_length < 1e-5:
        return [], seg_from_ws, seg_to_ws

    exclude = _mmd_target_names()
    # 排除手指/脚趾骨: 从手首或足首往下的子骨链不应该是 twist 候选
    # (DAZ 的 lCarpal1-4 在手首附近，会被误识别为前臂 twist)
    hand_bones = set()
    for hand_name in ("手首.L", "手首.R", "lHand", "rHand"):
        hb = armature.data.bones.get(hand_name)
        if hb:
            for child in hb.children_recursive:
                hand_bones.add(child.name)
    candidates = []
    for bone in armature.data.bones:
        name = bone.name
        if name in exclude or name in hand_bones:
            continue
        if name.startswith("_"):
            continue  # skip mmd_tools dummy/shadow bones
        # 必须有权重
        w_count = sum(_vg_weight_count(m, name) for m in mesh_objects)
        if w_count <= 0:
            continue
        head_ws = mw @ bone.head_local
        t_head, perp = _closest_on_segment(head_ws, seg_from_ws, seg_to_ws)
        if perp > seg_length * PERP_THRESHOLD_RATIO:
            continue
        if not (T_RANGE[0] <= t_head <= T_RANGE[1]):
            continue
        # 算权重加权中心 t (用来分配到最近的 slot)
        t_w = None
        for m in mesh_objects:
            tw = _vg_weighted_t_mean(m, name, seg_from_ws, seg_to_ws, mw)
            if tw is not None:
                t_w = tw
                break
        if t_w is None:
            t_w = max(0.0, min(1.0, t_head))
        length = bone.length
        candidates.append((name, t_head, t_w, w_count, head_ws, length))
    return candidates, seg_from_ws, seg_to_ws


def _assign_candidates_to_slots(candidates, main_t, sub_ts):
    """
    贪心分配: 权重最多的 → main; 其余按 t_head (几何位置) 就近分配到剩余 sub 槽。
    用 t_head 而非 t_w (权重加权 t) 是为了 L/R 对称 — 几何镜像严格对称,
    权重分布在手绘 XPS 模型里常有轻微不对称, 用 t_w 会导致左右 slot 不一致。
    返回: { slot_index: bone_name }
      slot_index: 0 = main, 1..len(sub_ts) = subs
    """
    assignment = {}
    if not candidates:
        return assignment
    # 按权重数量降序, 同权重量按名字字母顺 (L/R 对称)
    sorted_c = sorted(candidates, key=lambda c: (-c[3], c[0]))
    # 第一个 → main
    assignment[0] = sorted_c[0][0]
    used_slots = {0}
    for c in sorted_c[1:]:
        _, t_head, _, _, _, _ = c
        t_clamped = max(0.0, min(1.0, t_head))
        best_slot = None
        best_dist = float("inf")
        for i, st in enumerate(sub_ts, start=1):
            if i in used_slots:
                continue
            d = abs(t_clamped - st)
            if d < best_dist:
                best_dist = d
                best_slot = i
        if best_slot is not None:
            assignment[best_slot] = c[0]
            used_slots.add(best_slot)
    return assignment


class OBJECT_OT_complete_twist_bones(bpy.types.Operator):
    """建立上半身扭转骨系统 (腕捩/手捩 + 1/2/3 子骨, 位置识别, rename 优先)"""
    bl_idname = "object.complete_twist_bones"
    bl_label = "Complete Twist Bones"

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({"ERROR"}, "Please select an armature object")
            return {'CANCELLED'}

        mesh_objects = [
            o for o in bpy.data.objects
            if o.type == 'MESH' and any(
                m.type == 'ARMATURE' and m.object == obj
                for m in o.modifiers
            )
        ]

        print("[CTMMD 2.1] ===== Step 2.1: Twist System (position-based) =====")
        side_fmt = _detect_side_format(obj)
        print(f"[CTMMD 2.1]   Naming mode: {'prefix(左/右)' if side_fmt=='prefix' else 'suffix(.L/.R)'}")

        # Plan: 先在 OBJECT 模式扫描候选 (只读), 构建 (seg, side) -> candidates
        plans = []  # list of dicts per (seg, side)
        for seg_from_base, seg_to_base, main_base, sub_count, main_t, sub_ts in TWIST_SEGMENTS:
            for side in ("L", "R"):
                seg_from_name = _side_name(seg_from_base, side_fmt, side)
                seg_to_name = _side_name(seg_to_base, side_fmt, side)
                candidates, sf_ws, st_ws = _scan_candidates(
                    obj, mesh_objects, (seg_from_name, seg_to_name), side
                )
                plans.append({
                    "seg_from_name": seg_from_name,
                    "seg_to_name": seg_to_name,
                    "main_base": main_base,
                    "main_t": main_t,
                    "sub_ts": sub_ts[:sub_count],
                    "side": side,
                    "candidates": candidates,
                    "assignment": {},
                })

        # 全局去重: 一根 XPS 骨可能同时落在上臂和前臂段 (典型是 foretwist 在
        # ひじ.L 边界)。按"权重加权 t 更 interior (靠近 0.5) "的段优先分配,
        # 从其他段的候选列表中移除。
        def _interior_score(t_w):
            return min(t_w, 1.0 - t_w)  # 越大越 interior
        bone_to_plans = {}
        for idx, plan in enumerate(plans):
            for c in plan["candidates"]:
                bone_to_plans.setdefault(c[0], []).append((idx, c[2]))
        for bone_name, entries in bone_to_plans.items():
            if len(entries) <= 1:
                continue
            # 选 interior_score 最高的段
            best_idx = max(entries, key=lambda e: _interior_score(e[1]))[0]
            for pi, _ in entries:
                if pi != best_idx:
                    plans[pi]["candidates"] = [
                        c for c in plans[pi]["candidates"] if c[0] != bone_name
                    ]

        # 在去重后的候选上分配 slot
        for plan in plans:
            plan["assignment"] = _assign_candidates_to_slots(
                plan["candidates"], plan["main_t"], plan["sub_ts"]
            )
            print(f"[CTMMD 2.1] -- {plan['main_base']} {plan['side']}: {len(plan['candidates'])} candidates --")
            for c in plan["candidates"]:
                print(f"[CTMMD 2.1]     cand: {c[0]:<38s} t_head={c[1]:+.2f} t_w={c[2]:+.2f} w={c[3]}")
            for slot_idx, bone_name in plan["assignment"].items():
                slot_name = plan["main_base"] if slot_idx == 0 else f"{plan['main_base']}{slot_idx}"
                print(f"[CTMMD 2.1]     assign slot {slot_name:<8s} <- {bone_name}")

        # Apply in EDIT mode
        bpy.ops.object.mode_set(mode='EDIT')
        edit_bones = obj.data.edit_bones

        created = []
        renamed = []
        for plan in plans:
            seg_from_eb = edit_bones.get(plan["seg_from_name"])
            seg_to_eb = edit_bones.get(plan["seg_to_name"])
            if not seg_from_eb or not seg_to_eb:
                continue
            side = plan["side"]
            main_base = plan["main_base"]
            all_ts = [plan["main_t"]] + list(plan["sub_ts"])
            slot_names = [_side_name(main_base, side_fmt, side)] + [
                _side_name(f"{main_base}{i}", side_fmt, side)
                for i in range(1, len(plan["sub_ts"]) + 1)
            ]
            seg_dir = (seg_to_eb.head - seg_from_eb.head)
            seg_len = seg_dir.length
            if seg_len < 1e-6:
                continue

            # 所有 twist 骨 (rename 或 create) 都用标准 MMD 显示几何:
            #   head = 段上 t 位置 (沿 parent 段从 seg_from 到 seg_to)
            #   main (腕捩/手捩): tail = head + 段方向 * TWIST_BONE_LENGTH
            #     (target 主 twist 沿臂指向肘, 用于视觉上标示扭转轴方向)
            #   sub  (腕捩1/2/3): tail = head + (0,0,TWIST_BONE_LENGTH)
            #     (target 子 twist 统一朝 +Z, MMD 控制骨惯例)
            # 重置 rename 候选 rest head 安全说明: twist 通过 fixed_axis 做扭转, pivot
            # 沿段移动不影响扭转几何 (点绕轴旋转与轴上 pivot 无关)。候选原 XPS 位置
            # 与标准 t 位置的差异主要沿段方向, 垂直分量很小, 扭转时无明显顶点漂移。
            seg_unit = seg_dir.normalized()
            twist_bone_len = seg_len * TWIST_BONE_LENGTH_RATIO
            for slot_idx, (slot_name, t) in enumerate(zip(slot_names, all_ts)):
                head = seg_from_eb.head + t * seg_dir
                if slot_idx == 0:
                    # main twist: tail 精确对齐父臂 tail (= 子关节 head), 消除 rest gap
                    tail = seg_to_eb.head.copy()
                else:
                    tail = head + Z_UP * twist_bone_len           # sub: +Z
                cand_name = plan["assignment"].get(slot_idx)
                cand_eb = edit_bones.get(cand_name) if cand_name else None
                if cand_eb:
                    # rename 候选: 重置几何到标准位置, 权重跟名字走
                    cand_eb.use_connect = False
                    cand_eb.parent = seg_from_eb
                    cand_eb.head = head
                    cand_eb.tail = tail
                    cand_eb.use_deform = True
                    # main twist: roll 对齐父臂, 保证 local X/Z 与父骨一致,
                    # 使 VMD 四元数通过 mmd_tools PMX bone_mapper 投影时不跑偏
                    if slot_idx == 0:
                        cand_eb.roll = seg_from_eb.roll
                    cand_eb.name = slot_name
                    renamed.append(f"{cand_name} -> {slot_name}")
                else:
                    # 无候选 (或候选在别处已被消费): 创建空骨
                    bone_utils.create_or_update_bone(
                        edit_bones, slot_name, head, tail,
                        use_connect=False,
                        parent_name=plan["seg_from_name"],
                        use_deform=True,
                    )
                    if slot_idx == 0:
                        new_eb = edit_bones.get(slot_name)
                        if new_eb:
                            new_eb.roll = seg_from_eb.roll
                    created.append(slot_name)

        # 串联主链: ひじ parent = 腕捩, 手首 parent = 手捩
        reparent_pairs = [
            ("ひじ", "腕捩"),
            ("手首", "手捩"),
        ]
        for child_base, main_base in reparent_pairs:
            for side in ("L", "R"):
                child_name = _side_name(child_base, side_fmt, side)
                main_name = _side_name(main_base, side_fmt, side)
                child_eb = edit_bones.get(child_name)
                main_eb = edit_bones.get(main_name)
                if not child_eb or not main_eb:
                    continue
                saved_head = child_eb.head.copy()
                saved_tail = child_eb.tail.copy()
                child_eb.use_connect = False
                child_eb.parent = main_eb
                child_eb.head = saved_head
                child_eb.tail = saved_tail
                print(f"[CTMMD 2.1]   Chain: {child_name} parent -> {main_name}")

        bpy.ops.object.mode_set(mode='OBJECT')

        # ===== 交换腕.L ↔ 腕捩.L 的 vertex group =====
        # xtra07pp/xtra07 被 rename 成 腕捩.L/R, 但它们和 腕.L/R 位置完全重合,
        # 所以 xtra07pp 的 vertex group (现在叫"腕捩.L") 实际覆盖的是上臂区域,
        # 和目标 PMX 的 腕.L 权重分布一致。同时原 腕.L (XPS arm shoulder 2)
        # 的权重反而更像目标的 腕捩.L。交换两者的 vertex group 名字来纠正。
        mesh_objects = [
            o for o in bpy.data.objects
            if o.type == 'MESH' and any(
                m.type == 'ARMATURE' and m.object == obj
                for m in o.modifiers
            )
        ]
        twist_swap_pairs = [("腕捩", "腕")]  # 只交换腕捩 (上臂 twist), 手捩不需要
        for base_twist, base_arm in twist_swap_pairs:
            for side in ("L", "R"):
                twist_name = _side_name(base_twist, side_fmt, side)
                arm_name = _side_name(base_arm, side_fmt, side)
                # 只在 twist main 是从 rename 候选来的情况下才交换
                if not any(f"-> {twist_name}" in r for r in renamed):
                    continue
                for mesh in mesh_objects:
                    vg_arm = mesh.vertex_groups.get(arm_name)
                    vg_twist = mesh.vertex_groups.get(twist_name)
                    if not vg_arm and not vg_twist:
                        continue
                    tmp_name = f"__swap_tmp_{side}"
                    if vg_arm:
                        vg_arm.name = tmp_name
                    if vg_twist:
                        vg_twist.name = arm_name
                    if vg_arm:
                        vg_arm.name = twist_name
                print(f"[CTMMD 2.1]   Swap VG: {arm_name} <-> {twist_name}")

        # 设置 hide 标志 + layer: MMD 惯例
        #   main (腕捩/手捩): hide=False (用户可见可操作)
        #   sub  (腕捩1/2/3 / 手捩1/2/3): hide=True (付与親 自动驱动, 不应直接操作)
        # 注意: rename 来的候选骨 (xtra07pp / foretwist) 常因 XPS 导入时 "unused "
        # 前缀导致 hide=True 被继承, 必须显式重置。
        # layer 同样重要: mmd_tools export (pmx/exporter.py:372) 会检查
        #   bone.layers 与 armature.data.layers 的交集, 没交集就写 visible=False 到
        #   PMX, 导致 reimport 时 hide=True 回来。XPS importer 把 unused 骨放到高
        #   layer, 必须把 twist 骨拉回主 layer (layer 0)。
        def _reset_layer(bone):
            # layer 0 True, 其他 False。一次赋值避免"至少一个 layer 必须为 True"约束
            layers = [False] * len(bone.layers)
            layers[0] = True
            bone.layers = layers

        for plan in plans:
            main_name = _side_name(plan["main_base"], side_fmt, plan["side"])
            mb = obj.data.bones.get(main_name)
            if mb:
                _reset_layer(mb)
                mb.hide = False
            for i in range(1, len(plan["sub_ts"]) + 1):
                sub_name = _side_name(f"{plan['main_base']}{i}", side_fmt, plan["side"])
                sb = obj.data.bones.get(sub_name)
                if sb:
                    _reset_layer(sb)
                    sb.hide = True

        print(f"[CTMMD 2.1] Done: renamed {len(renamed)}, created {len(created)}")
        for r in renamed:
            print(f"[CTMMD 2.1]   Renamed: {r}")
        for c in created:
            print(f"[CTMMD 2.1]   Created (empty): {c}")

        self.report({"INFO"}, f"Twist system complete: renamed {len(renamed)}, created {len(created)}")
        return {'FINISHED'}


class OBJECT_OT_split_upper_arm_twist_weights(bpy.types.Operator):
    """可选: 把 腕.L/R 上臂段的顶点权重按沿臂 t 位置做 PMXEditor 风格的
    双骨线性插值分裂。每个顶点在 t 的相邻两个 anchor 骨之间按 (1-k) : k
    混合, 而不是单骨整体搬移, 从而得到连续的 twist 梯度。

    5 个 anchor (twist 影响度):
      t=0.00  腕.L      (0%)
      t=0.25  腕捩1.L   (25%)
      t=0.50  腕捩2.L   (50%)
      t=0.75  腕捩3.L   (75%)
      t=1.00  腕捩.L    (100% main, fixed_axis)

    对 t ∈ [t_lo, t_hi] 的顶点, 原 腕.L 权重 w 分成:
       bone_lo: w * (1 - k)
       bone_hi: w * k       其中 k = (t - t_lo) / (t_hi - t_lo)

    不动 腕捩.L 已有的 XPS 原始顶点 (从 xtra07pp 继承), 只分裂 腕.L 侧。
    建议在 step 5 (assign_weights) 之后运行。"""
    bl_idname = "object.split_upper_arm_twist_weights"
    bl_label = "可选: 上臂 twist 权重渐变"
    bl_description = "PMXEditor 风格双骨插值: 腕.L 顶点沿 t 平滑过渡到 腕捩1/2/3/腕捩 main"

    # 肩关节 dead zone: t < SHOULDER_DEAD_ZONE 的顶点 (贴近 腕.L.head/ 肩关节)
    # 不参与 twist 分权, 完全留在 腕.L 自己身上。避免 肩-腕 交接点的顶点被
    # 腕捩1 等吸走权重, 保持 肩.L+腕.L 双骨主导的 BDEF2 平滑过渡。
    SHOULDER_DEAD_ZONE = 0.05

    def _anchors(self, side):
        return [
            (0.00, f"腕.{side}"),
            (0.25, f"腕捩1.{side}"),
            (0.50, f"腕捩2.{side}"),
            (0.75, f"腕捩3.{side}"),
            (1.00, f"腕捩.{side}"),  # main (100% twist)
        ]

    def _bracket(self, t, anchors):
        """Return ((t_lo, name_lo), (t_hi, name_hi), k) for the segment that
        contains t. k ∈ [0, 1] is the linear blend weight toward the high
        anchor."""
        t = max(0.0, min(1.0, t))
        for i in range(len(anchors) - 1):
            t_lo, n_lo = anchors[i]
            t_hi, n_hi = anchors[i + 1]
            if t_lo <= t <= t_hi:
                span = t_hi - t_lo
                k = (t - t_lo) / span if span > 0 else 0.0
                return (t_lo, n_lo), (t_hi, n_hi), k
        # fallback: clamp to last anchor
        return anchors[-2], anchors[-1], 1.0

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "请先选中骨架")
            return {'CANCELLED'}

        meshes = []
        for m in bpy.data.objects:
            if m.type != 'MESH':
                continue
            for mod in m.modifiers:
                if mod.type == 'ARMATURE' and mod.object == obj:
                    meshes.append(m)
                    break
        if not meshes:
            self.report({'ERROR'}, "未找到绑定该骨架的 mesh")
            return {'CANCELLED'}

        total_verts = 0
        per_slot_add = {}       # bone_name -> 累积 weight
        per_slot_verts = {}     # bone_name -> +verts 计数
        for side in ("L", "R"):
            upper_bone = obj.data.bones.get(f"腕.{side}")
            elbow_bone = obj.data.bones.get(f"ひじ.{side}")
            if not upper_bone or not elbow_bone:
                print(f"[CTMMD twist-split] 跳过 {side}: 缺 腕/ひじ")
                continue

            arm_head_w = obj.matrix_world @ upper_bone.head_local
            arm_end_w = obj.matrix_world @ elbow_bone.head_local
            seg = arm_end_w - arm_head_w
            seg_len_sq = seg.length_squared
            if seg_len_sq < 1e-9:
                continue

            anchors = self._anchors(side)
            source_name = f"腕.{side}"
            all_bone_names = [n for _, n in anchors]

            for m in meshes:
                src_vg = m.vertex_groups.get(source_name)
                if not src_vg:
                    continue

                vgs = {}
                for name in all_bone_names:
                    if name not in m.vertex_groups:
                        m.vertex_groups.new(name=name)
                    vgs[name] = m.vertex_groups[name]

                mesh_mw = m.matrix_world
                # pre-collect (vertex -> plan) to avoid in-loop mutation issues
                plans = []
                for v in m.data.vertices:
                    src_w = 0.0
                    existing = {}
                    for g in v.groups:
                        if g.group == src_vg.index:
                            src_w = g.weight
                    if src_w <= 0:
                        continue
                    # read current weights on all anchor bones so we can
                    # accumulate correctly
                    for name, vg in vgs.items():
                        if name == source_name:
                            continue
                        for g in v.groups:
                            if g.group == vg.index:
                                existing[name] = g.weight
                                break
                    v_world = mesh_mw @ v.co
                    t = (v_world - arm_head_w).dot(seg) / seg_len_sq
                    # 肩关节 dead zone: 贴近 腕.L.head 的顶点不动, 保持 肩/腕
                    # 的多骨混权不被 twist 覆盖
                    if t < self.SHOULDER_DEAD_ZONE:
                        continue
                    (t_lo, n_lo), (t_hi, n_hi), k = self._bracket(t, anchors)
                    w_lo = src_w * (1.0 - k)
                    w_hi = src_w * k
                    plans.append((v.index, n_lo, w_lo, n_hi, w_hi, existing))

                for v_idx, n_lo, w_lo, n_hi, w_hi, existing in plans:
                    # write low anchor (always set since it may equal 腕.L)
                    if n_lo == source_name:
                        if w_lo > 0:
                            vgs[n_lo].add([v_idx], w_lo, 'REPLACE')
                        else:
                            src_vg.remove([v_idx])
                    else:
                        vgs[n_lo].add([v_idx], existing.get(n_lo, 0.0) + w_lo, 'REPLACE')
                    # write high anchor (never 腕.L since bracket goes up)
                    if w_hi > 0:
                        vgs[n_hi].add([v_idx], existing.get(n_hi, 0.0) + w_hi, 'REPLACE')
                    # if the source bone was 腕.L but the low anchor is a twist bone,
                    # clear the original 腕.L entry
                    if n_lo != source_name:
                        src_vg.remove([v_idx])

                    if n_lo != source_name and w_lo > 0:
                        per_slot_add[n_lo] = per_slot_add.get(n_lo, 0.0) + w_lo
                        per_slot_verts[n_lo] = per_slot_verts.get(n_lo, 0) + 1
                    if w_hi > 0:
                        per_slot_add[n_hi] = per_slot_add.get(n_hi, 0.0) + w_hi
                        per_slot_verts[n_hi] = per_slot_verts.get(n_hi, 0) + 1
                    total_verts += 1

        for slot in sorted(per_slot_add.keys()):
            print(f"[CTMMD twist-split] {slot}: +{per_slot_verts[slot]} verts, wsum +{per_slot_add[slot]:.2f}")
        print(f"[CTMMD twist-split] 处理顶点总数: {total_verts}")

        self.report({'INFO'}, f"上臂 twist 权重渐变完成: {total_verts} 个顶点已插值分裂")
        return {'FINISHED'}


class OBJECT_OT_split_forearm_twist_weights(bpy.types.Operator):
    """可选: 把 ひじ.L/R 前腕段的顶点权重按沿臂 t 位置做双骨线性插值分裂。

    5 个 anchor:
      t=0.00  ひじ.L     (0%)
      t=0.25  手捩1.L   (25%)
      t=0.50  手捩2.L   (50%)
      t=0.75  手捩3.L   (75%)
      t=1.00  手捩.L    (100% main)

    建议在 assign_weights + split_upper_arm 之后运行。"""
    bl_idname = "object.split_forearm_twist_weights"
    bl_label = "可选: 前腕 twist 权重渐变"
    bl_description = "双骨插值: ひじ.L 顶点沿 t 过渡到 手捩1/2/3/手捩 main"

    ELBOW_DEAD_ZONE = 0.05

    def _anchors(self, side):
        return [
            (0.00, f"ひじ.{side}"),
            (0.25, f"手捩1.{side}"),
            (0.50, f"手捩2.{side}"),
            (0.75, f"手捩3.{side}"),
            (1.00, f"手捩.{side}"),
        ]

    def _bracket(self, t, anchors):
        t = max(0.0, min(1.0, t))
        for i in range(len(anchors) - 1):
            t_lo, n_lo = anchors[i]
            t_hi, n_hi = anchors[i + 1]
            if t_lo <= t <= t_hi:
                span = t_hi - t_lo
                k = (t - t_lo) / span if span > 0 else 0.0
                return (t_lo, n_lo), (t_hi, n_hi), k
        return anchors[-2], anchors[-1], 1.0

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "请先选中骨架")
            return {'CANCELLED'}

        meshes = [m for m in bpy.data.objects if m.type == 'MESH'
                  and any(mod.type == 'ARMATURE' and mod.object == obj for mod in m.modifiers)]
        if not meshes:
            self.report({'ERROR'}, "未找到绑定该骨架的 mesh")
            return {'CANCELLED'}

        total_verts = 0
        per_slot_add = {}
        per_slot_verts = {}
        for side in ("L", "R"):
            elbow_bone = obj.data.bones.get(f"ひじ.{side}")
            wrist_bone = obj.data.bones.get(f"手首.{side}")
            if not elbow_bone or not wrist_bone:
                continue

            seg_head_w = obj.matrix_world @ elbow_bone.head_local
            seg_end_w = obj.matrix_world @ wrist_bone.head_local
            seg = seg_end_w - seg_head_w
            seg_len_sq = seg.length_squared
            if seg_len_sq < 1e-9:
                continue

            anchors = self._anchors(side)
            source_name = f"ひじ.{side}"
            all_bone_names = [n for _, n in anchors]

            for m in meshes:
                src_vg = m.vertex_groups.get(source_name)
                if not src_vg:
                    continue
                vgs = {}
                for name in all_bone_names:
                    if name not in m.vertex_groups:
                        m.vertex_groups.new(name=name)
                    vgs[name] = m.vertex_groups[name]

                mesh_mw = m.matrix_world
                plans = []
                for v in m.data.vertices:
                    src_w = next((g.weight for g in v.groups if g.group == src_vg.index), 0.0)
                    if src_w <= 0:
                        continue
                    existing = {}
                    for name, vg in vgs.items():
                        if name == source_name:
                            continue
                        for g in v.groups:
                            if g.group == vg.index:
                                existing[name] = g.weight
                                break
                    v_world = mesh_mw @ v.co
                    t = (v_world - seg_head_w).dot(seg) / seg_len_sq
                    if t < self.ELBOW_DEAD_ZONE:
                        continue
                    (t_lo, n_lo), (t_hi, n_hi), k = self._bracket(t, anchors)
                    plans.append((v.index, n_lo, src_w * (1.0 - k), n_hi, src_w * k, existing))

                for v_idx, n_lo, w_lo, n_hi, w_hi, existing in plans:
                    if n_lo == source_name:
                        if w_lo > 0:
                            vgs[n_lo].add([v_idx], w_lo, 'REPLACE')
                        else:
                            src_vg.remove([v_idx])
                    else:
                        vgs[n_lo].add([v_idx], existing.get(n_lo, 0.0) + w_lo, 'REPLACE')
                    if w_hi > 0:
                        vgs[n_hi].add([v_idx], existing.get(n_hi, 0.0) + w_hi, 'REPLACE')
                    if n_lo != source_name:
                        src_vg.remove([v_idx])
                    if n_lo != source_name and w_lo > 0:
                        per_slot_add[n_lo] = per_slot_add.get(n_lo, 0.0) + w_lo
                        per_slot_verts[n_lo] = per_slot_verts.get(n_lo, 0) + 1
                    if w_hi > 0:
                        per_slot_add[n_hi] = per_slot_add.get(n_hi, 0.0) + w_hi
                        per_slot_verts[n_hi] = per_slot_verts.get(n_hi, 0) + 1
                    total_verts += 1

        for slot in sorted(per_slot_add.keys()):
            print(f"[CTMMD fore-twist-split] {slot}: +{per_slot_verts[slot]} verts, wsum +{per_slot_add[slot]:.2f}")
        print(f"[CTMMD fore-twist-split] 处理顶点总数: {total_verts}")
        self.report({'INFO'}, f"前腕 twist 权重渐变完成: {total_verts} 个顶点已插值分裂")
        return {'FINISHED'}
