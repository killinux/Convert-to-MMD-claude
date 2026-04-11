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

TWIST_BONE_LENGTH = 0.082   # 参考 target PMX: 1.0 PMX unit in XPS scale (export ×12)
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
    candidates = []
    for bone in armature.data.bones:
        name = bone.name
        if name in exclude:
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
            for slot_idx, (slot_name, t) in enumerate(zip(slot_names, all_ts)):
                head = seg_from_eb.head + t * seg_dir
                if slot_idx == 0:
                    tail = head + seg_unit * TWIST_BONE_LENGTH  # main: along segment
                else:
                    tail = head + Z_UP * TWIST_BONE_LENGTH       # sub: +Z
                cand_name = plan["assignment"].get(slot_idx)
                cand_eb = edit_bones.get(cand_name) if cand_name else None
                if cand_eb:
                    # rename 候选: 重置几何到标准位置, 权重跟名字走
                    cand_eb.use_connect = False
                    cand_eb.parent = seg_from_eb
                    cand_eb.head = head
                    cand_eb.tail = tail
                    cand_eb.use_deform = True
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

        # 设置 hide 标志: MMD 惯例
        #   main (腕捩/手捩): hide=False (用户可见可操作)
        #   sub  (腕捩1/2/3 / 手捩1/2/3): hide=True (付与親 自动驱动, 不应直接操作)
        # 注意: rename 来的候选骨 (xtra07pp / foretwist) 常因 XPS 导入时 "unused "
        # 前缀导致 hide=True 被继承, 必须显式重置。
        for plan in plans:
            main_name = _side_name(plan["main_base"], side_fmt, plan["side"])
            mb = obj.data.bones.get(main_name)
            if mb:
                mb.hide = False
            for i in range(1, len(plan["sub_ts"]) + 1):
                sub_name = _side_name(f"{plan['main_base']}{i}", side_fmt, plan["side"])
                sb = obj.data.bones.get(sub_name)
                if sb:
                    sb.hide = True

        print(f"[CTMMD 2.1] Done: renamed {len(renamed)}, created {len(created)}")
        for r in renamed:
            print(f"[CTMMD 2.1]   Renamed: {r}")
        for c in created:
            print(f"[CTMMD 2.1]   Created (empty): {c}")

        self.report({"INFO"}, f"Twist system complete: renamed {len(renamed)}, created {len(created)}")
        return {'FINISHED'}
