import bpy
from mathutils import Vector
from .. import bone_utils
from .. import bone_map_and_group

# D骨与主骨的对应关系(主骨名 -> D骨名)，支持 .L/.R 和 左/右 两种格式。
D_BONE_PAIRS = [
    # (主骨后缀/前缀, D骨名)，侧边由代码动态拼接
    ("足", "足D"),
    ("ひざ", "ひざD"),
    ("足首", "足首D"),
]

# D骨长度相对于主骨长度的比例(来自目标 PMX 参考模型)
D_BONE_LENGTH_RATIO = {
    "足D": 0.193,
    "ひざD": 0.200,
    "足首D": 0.796,
}

SIDES = [
    (".L", "左"),
    (".R", "右"),
]

# 2.5 阶段2：只允许归并进此白名单(上半身及以下，跳过颈部和手臂)。
# 注意：腰キャンセル不在此列，它只在阶段4里从足D位置派生，不接收 unused 骨归并。
LOWER_BODY_TARGETS = {
    "上半身", "上半身1", "上半身2", "上半身3", "下半身",
    # 主骨（后缀格式 .L/.R）
    "足.L", "足.R",
    "ひざ.L", "ひざ.R",
    "足首.L", "足首.R",
    # 主骨（前缀格式 左/右）
    "左足", "右足",
    "左ひざ", "右ひざ",
    "左足首", "右足首",
    # D骨（后缀格式）
    "足D.L", "足D.R",
    "ひざD.L", "ひざD.R",
    "足首D.L", "足首D.R",
    # 足先EX（两种格式）
    "足先EX.L", "足先EX.R",
    "左足先EX", "右足先EX",
}

# Phase 2 专用候选集：使用主骨（足/ひざ/足首）而非 D 骨。
# 5.2 在 5.1 之前执行：unused 权重先合并到主骨，5.1 再把主骨复制到 D 骨。
# 不用 D 骨的原因：足D 线段靠近臀部，会把臀部顶点误吸入 D 骨。
PHASE2_TARGETS = {
    "上半身", "上半身1", "上半身2", "上半身3", "下半身",
    # 后缀格式 (.L/.R)
    "足.L", "足.R",
    "ひざ.L", "ひざ.R",
    "足首.L", "足首.R",
    "足先EX.L", "足先EX.R",
    # 前缀格式 (左/右)
    "左足", "右足",
    "左ひざ", "右ひざ",
    "左足首", "右足首",
    "左足先EX", "右足先EX",
}

# 强制目标映射：骨骼名称包含 key 时，直接整骨转移到指定骨骼，不做逐顶点距离判断。
# 适用于位置语义明确、不需要分割的 unused 骨骼。
FORCED_TARGETS = {
    "pelvis": "下半身",   # 骨盆所有顶点 → 下半身
}

# 需要 per-vertex 拆分的 unused 骨骼名称关键字。
# 只有这些骨骼跨越两个区域（臀部+大腿），才需要逐顶点判断分配到哪根骨骼。
# 其余 unused 骨骼一律使用整骨转移（质心找最近骨骼，全部顶点一起迁移）。
SPLIT_BONES = {
    "xtra08",     # 左侧：包含臀部(Z>1.05) + 大腿，需拆分给 下半身 + 左足
    "xtra08opp",  # 右侧：同上
}

def _point_to_segment_dist(point, seg_head, seg_tail):
    """计算点到线段的最近距离"""
    seg = seg_tail - seg_head
    seg_len_sq = seg.length_squared
    if seg_len_sq < 1e-8:
        return (point - seg_head).length
    t = max(0.0, min(1.0, (point - seg_head).dot(seg) / seg_len_sq))
    nearest_pt = seg_head + t * seg
    return (point - nearest_pt).length


def _vertex_centroid(bone_name, mesh_objects):
    """返回顶点组的加权质心(world space),无权重时返回 None"""
    total = Vector((0, 0, 0))
    w_sum = 0.0
    for mesh in mesh_objects:
        vg = mesh.vertex_groups.get(bone_name)
        if not vg:
            continue
        for v in mesh.data.vertices:
            for g in v.groups:
                if g.group == vg.index and g.weight > 0:
                    total += mesh.matrix_world @ v.co * g.weight
                    w_sum += g.weight
    return (total / w_sum) if w_sum > 0 else None

def _get_main_bone_name(armature, base, side_suffix, side_prefix):
    """优先 .L/.R 格式，再找左/右前缀格式。"""
    name_suffix = base + side_suffix          # 足.L
    name_prefix = side_prefix + base          # 左足
    bones = armature.data.bones
    if bones.get(name_suffix):
        return name_suffix
    if bones.get(name_prefix):
        return name_prefix
    return None

def _vg_has_weight(mesh_obj, vg_name):
    vg = mesh_obj.vertex_groups.get(vg_name)
    if not vg:
        return False
    for v in mesh_obj.data.vertices:
        for g in v.groups:
            if g.group == vg.index and g.weight > 0:
                return True
    return False


# ─── 2.2:补全 D骨 ─────────────────────────────────────────────────────

class OBJECT_OT_complete_d_bones(bpy.types.Operator):
    """检测并补全 D骨(足D/ひざD/足首D),并从主骨复制权重"""
    bl_idname = "object.complete_d_bones"
    bl_label = "Complete D-Bones"

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({"ERROR"}, "Please select an armature object")
            return {'CANCELLED'}

        created = []
        skipped = []

        print("[CTMMD 3] ===== Step 3: Create D-Bones =====")
        bpy.ops.object.mode_set(mode='EDIT')
        edit_bones = obj.data.edit_bones

        for base, d_base in D_BONE_PAIRS:
            for side_suffix, side_prefix in SIDES:
                d_name = d_base + side_suffix
                main_name = _get_main_bone_name(obj, base, side_suffix, side_prefix)

                if edit_bones.get(d_name):
                    skipped.append(d_name + " 已存在")
                    continue
                if not main_name or not edit_bones.get(main_name):
                    skipped.append(d_name + " 主骨不存在")
                    continue

                main_eb = edit_bones[main_name]
                cancel_name = "腰キャンセル" + side_suffix
                parent_name = cancel_name if edit_bones.get(cancel_name) else "下半身"

                parent_d = None
                for _, prev_d_base in D_BONE_PAIRS:
                    if prev_d_base + side_suffix == d_name:
                        break
                    prev_d = edit_bones.get(prev_d_base + side_suffix)
                    if prev_d:
                        parent_d = prev_d

                actual_parent = parent_d.name if parent_d else parent_name
                main_length = (main_eb.tail - main_eb.head).length
                ratio = D_BONE_LENGTH_RATIO.get(d_base, 0.2)
                d_tail = main_eb.head.copy()
                d_tail.z += main_length * ratio
                bone_utils.create_or_update_bone(
                    edit_bones,
                    d_name,
                    main_eb.head.copy(),
                    d_tail,
                    use_connect=False,
                    parent_name=actual_parent,
                    use_deform=True,
                )
                eb = edit_bones[d_name]
                head_str = f"({eb.head.x:.3f},{eb.head.y:.3f},{eb.head.z:.3f})"
                print(f"[CTMMD 3]   Created: {d_name:<12} head={head_str}  parent={actual_parent}  source={main_name}")
                created.append(d_name)

        bpy.ops.object.mode_set(mode='OBJECT')

        print(f"[CTMMD 3] D-bone creation complete: created {len(created)}, skipped {len(skipped)}")
        for s in skipped:
            print(f"[CTMMD 3]   Skipped: {s}")
        self.report({"INFO"}, f"Created {len(created)} D-bones. Run Step 2.5 for weight assignment.")
        return {'FINISHED'}


class OBJECT_OT_fix_lower_body_weights(bpy.types.Operator):
    """从下半身权重中移除已由D骨覆盖的腿部顶点"""
    bl_idname = "object.fix_lower_body_weights"
    bl_label = "Fix Lower Body Weights"

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

        d_bone_names = [
            "足D.L", "足D.R",
            "ひざD.L", "ひざD.R",
            "足首D.L", "足首D.R",
        ]

        total_removed = 0
        total_remaining = 0
        processed_meshes = 0

        for mesh_obj in mesh_objects:
            lower_vg = mesh_obj.vertex_groups.get("下半身")
            if not lower_vg:
                continue

            d_vg_indices = {
                mesh_obj.vertex_groups[n].index
                for n in d_bone_names
                if mesh_obj.vertex_groups.get(n)
            }
            if not d_vg_indices:
                print(f"[CTMMD 2.3]   {mesh_obj.name}: no D-bone vertex groups found, skipped")
                continue

            verts_to_remove = [
                v.index for v in mesh_obj.data.vertices
                if any(g.group in d_vg_indices and g.weight > 0 for g in v.groups)
            ]

            before_count = sum(
                1 for v in mesh_obj.data.vertices
                for g in v.groups
                if g.group == lower_vg.index and g.weight > 0
            )

            lower_vg.remove(verts_to_remove)

            after_count = sum(
                1 for v in mesh_obj.data.vertices
                for g in v.groups
                if g.group == lower_vg.index and g.weight > 0
            )

            removed = before_count - after_count
            total_removed += removed
            total_remaining += after_count
            processed_meshes += 1
            print(f"[CTMMD 2.3]   {mesh_obj.name}: removed {removed} lower-body verts, {after_count} remaining")

        if processed_meshes == 0:
            self.report({'WARNING'}, "No processable mesh found (missing lower-body group or D-bones)")
            return {'CANCELLED'}

        print(f"[CTMMD 2.3] Lower-body cleanup complete: removed {total_removed} leg verts, {total_remaining} remaining")
        self.report({"INFO"}, f"Lower-body weights fixed: removed {total_removed} leg verts, {total_remaining} remaining")
        return {'FINISHED'}


class OBJECT_OT_complete_hip_cancel_bones(bpy.types.Operator):
    """补全腰キャンセル骨骼(抵消腰部旋转的控制骨)"""
    bl_idname = "object.complete_hip_cancel_bones"
    bl_label = "Complete Hip Cancel Bones"

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({"ERROR"}, "Please select an armature object")
            return {'CANCELLED'}

        bpy.ops.object.mode_set(mode='EDIT')
        edit_bones = obj.data.edit_bones

        lower_body = edit_bones.get("下半身")
        if not lower_body:
            bpy.ops.object.mode_set(mode='OBJECT')
            self.report({'ERROR'}, "Lower body bone not found. Run Step 2 first.")
            return {'CANCELLED'}

        print("[CTMMD 4] ===== Step 4: Create Hip Cancel Bones =====")
        created = 0
        log = []
        for side_suffix in [".L", ".R"]:
            cancel_name = "腰キャンセル" + side_suffix
            if edit_bones.get(cancel_name):
                log.append((cancel_name, "已存在,跳过"))
                continue

            # 位置与足D相同(参考目标 PMX)，tail 固定向上
            fd_bone = edit_bones.get("足D" + side_suffix)
            if fd_bone:
                head = fd_bone.head.copy()
                tail = Vector((head.x, head.y, head.z + (fd_bone.tail - fd_bone.head).length))
            else:
                head = lower_body.head.copy()
                tail = lower_body.tail.copy()

            bone_utils.create_or_update_bone(
                edit_bones, cancel_name,
                head, tail,
                use_connect=False,
                parent_name="下半身",
                use_deform=True
            )
            pos_src = f"足D{side_suffix}" if fd_bone else "下半身(fallback)"
            head_str = f"({head.x:.3f},{head.y:.3f},{head.z:.3f})"
            log.append((cancel_name, f"新建  head={head_str}  位置来源={pos_src}  父=下半身"))
            created += 1

        bpy.ops.object.mode_set(mode='OBJECT')

        print("[CTMMD 4] Hip cancel summary:")
        for name, note in log:
            print(f"[CTMMD 4]   {name}  {note}")

        self.report({"INFO"}, f"Hip cancel bones: created {created}, existing {len(log)-created}")
        return {'FINISHED'}


MMD_BONE_NAMES = set(bone_map_and_group.mmd_bone_map.values())

def _guess_side(bone, mesh_objects):
    """根据骨骼下顶点的平均 X 坐标判断左右侧. 返 'L'/'R'/None"""
    x_vals = []
    for mesh in mesh_objects:
        vg = mesh.vertex_groups.get(bone.name)
        if not vg:
            continue
        for v in mesh.data.vertices:
            for g in v.groups:
                if g.group == vg.index and g.weight > 0:
                    # 转换到世界坐标取 X
                    x_vals.append((mesh.matrix_world @ v.co).x)
    if not x_vals:
        return None
    avg_x = sum(x_vals) / len(x_vals)
    if avg_x > 0.01:
        return 'L'
    if avg_x < -0.01:
        return 'R'
    return None


def _side_of_mmd_bone(bone_name):
    """判断 MMD 骨骼名称的侧边. 返 'L'/'R'/None"""
    if bone_name.startswith("左") or bone_name.endswith(".L"):
        return 'L'
    if bone_name.startswith("右") or bone_name.endswith(".R"):
        return 'R'
    return None


def _is_leg_bone(name):
    """判断骨骼名称是否为腿/膝/踝类骨骼（用于Z上限过滤：臀部顶点不应被分配到腿骨）"""
    LEG_KEYWORDS = ["足", "ひざ"]
    for kw in LEG_KEYWORDS:
        if kw in name:
            return True
    return False


def _merge_weights_additive(mesh_obj, src_name, dst_name):
    """将 src_name 顶点组权重加法合并到 dst_name (上限1.0), 返回受影响顶点数"""
    src_vg = mesh_obj.vertex_groups.get(src_name)
    if not src_vg:
        return 0
    dst_vg = mesh_obj.vertex_groups.get(dst_name) or mesh_obj.vertex_groups.new(name=dst_name)
    count = 0
    for v in mesh_obj.data.vertices:
        src_w = 0.0
        for g in v.groups:
            if g.group == src_vg.index:
                src_w = g.weight
                break
        if src_w <= 0:
            continue
        # 读取目标现有权重
        dst_w = 0.0
        for g in v.groups:
            if g.group == dst_vg.index:
                dst_w = g.weight
                break
        new_w = min(src_w + dst_w, 1.0)
        dst_vg.add([v.index], new_w, 'REPLACE')
        count += 1
    return count


def _split_weights_gradient(mesh_obj, src_name, dst_elbow_name, dst_twist_name,
                             seg_from_ws, seg_to_ws):
    """
    src_name 权重按顶点在 seg_from_ws->seg_to_ws 线段上的投影参数 t 梯度分配:
      dst_elbow(ひじ) 获得 w * t, dst_twist(腕捻) 获得 w * (1-t)
    """
    src_vg = mesh_obj.vertex_groups.get(src_name)
    if not src_vg:
        return 0, 0, 0
    dst_elbow_vg = (mesh_obj.vertex_groups.get(dst_elbow_name)
                    or mesh_obj.vertex_groups.new(name=dst_elbow_name))
    dst_twist_vg = (mesh_obj.vertex_groups.get(dst_twist_name)
                    or mesh_obj.vertex_groups.new(name=dst_twist_name))

    seg = seg_to_ws - seg_from_ws
    seg_len_sq = seg.length_squared

    count = count_e = count_t = 0
    for v in mesh_obj.data.vertices:
        src_w = 0.0
        for g in v.groups:
            if g.group == src_vg.index:
                src_w = g.weight
                break
        if src_w <= 0.001:
            continue

        # 投影参数 t: 0=腕侧, 1=ひじ侧
        vw = mesh_obj.matrix_world @ v.co
        if seg_len_sq < 1e-8:
            t = 0.5
        else:
            t = max(0.0, min(1.0, (vw - seg_from_ws).dot(seg) / seg_len_sq))

        w_elbow = src_w * t
        w_twist = src_w * (1.0 - t)

        # 加到现有权重(上限1.0)
        if w_elbow > 0.001:
            cur = next((g.weight for g in v.groups if g.group == dst_elbow_vg.index), 0.0)
            dst_elbow_vg.add([v.index], min(cur + w_elbow, 1.0), 'REPLACE')
            count_e += 1

        if w_twist > 0.001:
            cur = next((g.weight for g in v.groups if g.group == dst_twist_vg.index), 0.0)
            dst_twist_vg.add([v.index], min(cur + w_twist, 1.0), 'REPLACE')
            count_t += 1

        count += 1
    return count, count_e, count_t


class OBJECT_OT_merge_unmapped_weights(bpy.types.Operator):
    """检测并合并未映射辅助骨的顶点权重到最近的 MMD 骨骼"""
    bl_idname = "object.merge_unmapped_weights"
    bl_label = "Merge Unmapped Weights"

    DISTANCE_THRESHOLD: bpy.props.FloatProperty(default=0.15)

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
        if not mesh_objects:
            self.report({"ERROR"}, "No skinned mesh objects found")
            return {'CANCELLED'}

        unmapped_bones = [
            bone for bone in obj.data.bones
            if bone.use_deform
            and bone.name.startswith("unused ")
            and any(_vg_has_weight(m, bone.name) for m in mesh_objects)
        ]
        all_unused_names = {b.name for b in obj.data.bones if b.name.startswith("unused ")}

        print("[CTMMD 2.1] ===== Unmapped Weight Merge Report =====")
        print(f"[CTMMD 2.1] Found {len(unmapped_bones)} unmapped bones")

        merged_count = 0
        skipped_count = 0

        for bone in unmapped_bones:
            bones_with_weight = {
                mesh.vertex_groups[g.group].name
                for mesh in mesh_objects
                for v in mesh.data.vertices
                for g in v.groups
                if g.weight > 0 and g.group < len(mesh.vertex_groups)
            }

            nearest = None
            nearest_score = float('inf')
            for candidate in obj.data.bones:
                if candidate.name in all_unused_names:
                    continue
                if not candidate.use_deform:
                    continue
                if candidate.name not in bones_with_weight:
                    continue
                head_dist = (bone.head_local - candidate.head_local).length
                center = (candidate.head_local + candidate.tail_local) / 2
                head_to_center = (bone.head_local - center).length
                score = head_dist + 0.1 * head_to_center
                if score < nearest_score:
                    nearest_score = score
                    nearest = candidate
            nearest_dist = (bone.head_local - nearest.head_local).length if nearest else float('inf')

            if not nearest:
                print(f"[CTMMD 2.1] [WARN] {bone.name:<30} -> no candidate bone, skipped")
                skipped_count += 1
                continue

            dist = nearest_dist
            total_verts = sum(
                sum(
                    1 for v in mesh.data.vertices
                    for g in v.groups
                    if mesh.vertex_groups.get(bone.name)
                    and g.group == mesh.vertex_groups[bone.name].index
                    and g.weight > 0
                )
                for mesh in mesh_objects
            )

            if dist >= self.DISTANCE_THRESHOLD:
                print(f"[CTMMD 2.1] [WARN] {bone.name:<30} -> {nearest.name:<10} (dist={dist:.2f}m, {total_verts} verts) over threshold, skipped")
                skipped_count += 1
                continue

            src_side = _guess_side(bone, mesh_objects)
            dst_side = _side_of_mmd_bone(nearest.name)
            if src_side and dst_side and src_side != dst_side:
                same_side_nearest = None
                same_side_dist = float('inf')
                for candidate in obj.data.bones:
                    if candidate.name in all_unused_names:
                        continue
                    if not candidate.use_deform:
                        continue
                    if candidate.name not in bones_with_weight:
                        continue
                    if _side_of_mmd_bone(candidate.name) != src_side:
                        continue
                    d = (bone.head_local - candidate.head_local).length
                    if d < same_side_dist:
                        same_side_dist = d
                        same_side_nearest = candidate
                if same_side_nearest and same_side_dist < self.DISTANCE_THRESHOLD:
                    nearest = same_side_nearest
                    dist = same_side_dist
                else:
                    sd = f"{same_side_dist:.2f}m" if same_side_nearest else "无候选"
                    print(f"[CTMMD 2.1] [WARN] {bone.name:<30} -> side mismatch and same-side candidate over threshold ({sd}), skipped")
                    skipped_count += 1
                    continue

            vert_count = 0
            for mesh in mesh_objects:
                n = _merge_weights_additive(mesh, bone.name, nearest.name)
                if n > 0:
                    vert_count += n
                    src_vg = mesh.vertex_groups.get(bone.name)
                    if src_vg:
                        merged_verts = [
                            v.index for v in mesh.data.vertices
                            for g in v.groups
                            if g.group == src_vg.index and g.weight > 0
                        ]
                        if merged_verts:
                            src_vg.remove(merged_verts)

            obj.data.bones[bone.name].use_deform = False
            print(f"[CTMMD 2.1] [OK] {bone.name:<30} -> {nearest.name:<10} (dist={dist:.2f}m, {vert_count} verts) merged [disabled]")
            merged_count += 1

        print("[CTMMD 2.1] ===== Report End =====")
        print(f"[CTMMD 2.1] Merged: {merged_count}, skipped: {skipped_count}")
        self.report({"INFO"}, f"Unmapped weights merged: {merged_count} success, {skipped_count} skipped")
        return {'FINISHED'}


class OBJECT_OT_assign_weights(bpy.types.Operator):
    """统一分配权重: D骨 <- 主骨, unused骨并入目标, 下半身清理"""
    bl_idname = "object.assign_weights"
    bl_label = "Assign Weights"

    DISTANCE_THRESHOLD: bpy.props.FloatProperty(default=0.15)

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
        if not mesh_objects:
            self.report({"ERROR"}, "No skinned mesh objects found")
            return {'CANCELLED'}

        print("[CTMMD 5] ===== Step 5: Unified Weight Assignment =====")
        print("[CTMMD 5] -- 5.1: unused -> main bones --")

        print("[CTMMD 5] ===== 5.1: unused bones -> target bones (per-vertex) =====")
        all_unused_names = {b.name for b in obj.data.bones if b.name.startswith("unused ")}
        unused_bones = [
            b for b in obj.data.bones
            if b.name.startswith("unused ") and b.use_deform
            and any(_vg_has_weight(m, b.name) for m in mesh_objects)
        ]

        target_candidates = []
        for candidate in obj.data.bones:
            if candidate.name in all_unused_names or not candidate.use_deform:
                continue
            if candidate.name in cleared_bones:
                continue
            if candidate.name not in PHASE2_TARGETS:
                continue
            ch = obj.matrix_world @ candidate.head_local
            ct = obj.matrix_world @ candidate.tail_local
            target_candidates.append((candidate.name, ch, ct))

        merged_count = 0
        skipped_count = 0
        fallback_warnings = []  # 收集超阈值骨骼，步骤结束后提示人工处理

        for bone in unused_bones:
            # ── 强制目标检查 ──
            forced_target = None
            for kw, tgt in FORCED_TARGETS.items():
                if kw in bone.name.lower() and obj.data.bones.get(tgt):
                    forced_target = tgt; break
            if forced_target:
                total_moved = 0
                for mesh in mesh_objects:
                    src_vg = mesh.vertex_groups.get(bone.name)
                    if not src_vg: continue
                    dst_vg = mesh.vertex_groups.get(forced_target) or mesh.vertex_groups.new(name=forced_target)
                    verts_to_clear = []
                    for v in mesh.data.vertices:
                        src_w = next((g.weight for g in v.groups if g.group == src_vg.index), 0.0)
                        if src_w <= 0.001: continue
                        cur_dst = next((g.weight for g in v.groups if g.group == dst_vg.index), 0.0)
                        dst_vg.add([v.index], min(cur_dst + src_w, 1.0), 'REPLACE')
                        verts_to_clear.append(v.index)
                        total_moved += 1
                    if verts_to_clear:
                        src_vg.remove(verts_to_clear)
                obj.data.bones[bone.name].use_deform = False
                print(f"[CTMMD 5] [FORCED] {bone.name:<30} -> {forced_target} ({total_moved} verts)")
                merged_count += 1
                continue

            src_pos = _vertex_centroid(bone.name, mesh_objects) or (obj.matrix_world @ bone.head_local)
            best_name, best_dist = None, float('inf')
            for cname, ch, ct in target_candidates:
                dist = _point_to_segment_dist(src_pos, ch, ct)
                if dist < best_dist:
                    best_dist = dist
                    best_name = cname

            if not best_name:
                print(f"[CTMMD 5] [WARN] {bone.name:<30} no candidate, skipped")
                skipped_count += 1
                continue
            src_side = _guess_side(bone, mesh_objects)
            if best_dist >= self.DISTANCE_THRESHOLD:
                vcount = sum(
                    1 for mesh in mesh_objects
                    for v in mesh.data.vertices
                    for g in v.groups
                    if mesh.vertex_groups.get(bone.name) and
                       g.group == mesh.vertex_groups[bone.name].index and g.weight > 0.01
                )
                fallback_warnings.append((bone.name, best_dist, best_name, src_pos.z, vcount))
                print(f"[CTMMD 5] [SKIP] {bone.name:<30} dist {best_dist:.3f}m > threshold, Z={src_pos.z:.3f}, nearest={best_name}, {vcount} verts — 需人工处理")
                skipped_count += 1
                continue
            # ── 判断是否需要 per-vertex 拆分 ──
            needs_split = any(kw in bone.name.lower() for kw in SPLIT_BONES)

            dst_counts = {}
            if needs_split:
                for mesh in mesh_objects:
                    src_vg = mesh.vertex_groups.get(bone.name)
                    if not src_vg: continue
                    verts_to_clear = []
                    for v in mesh.data.vertices:
                        src_w = next((g.weight for g in v.groups if g.group == src_vg.index), 0.0)
                        if src_w <= 0.001: continue
                        vw = mesh.matrix_world @ v.co

                        filtered = target_candidates
                        if src_side:
                            same_side = [(n, h, t) for n, h, t in target_candidates
                                         if _side_of_mmd_bone(n) == src_side or _side_of_mmd_bone(n) is None]
                            if same_side:
                                filtered = same_side

                        HIP_TOLERANCE = 0.05
                        z_filtered = [(n, h, t) for n, h, t in filtered
                                      if not (_is_leg_bone(n) and vw.z > max(h.z, t.z) + HIP_TOLERANCE)]
                        if z_filtered:
                            filtered = z_filtered

                        v_best_name, v_best_dist = None, float('inf')
                        for cname, ch, ct in filtered:
                            dist = _point_to_segment_dist(vw, ch, ct)
                            if dist < v_best_dist:
                                v_best_dist = dist; v_best_name = cname
                        if not v_best_name: continue

                        dst_vg = mesh.vertex_groups.get(v_best_name) or mesh.vertex_groups.new(name=v_best_name)
                        cur_dst = next((g.weight for g in v.groups if g.group == dst_vg.index), 0.0)
                        dst_vg.add([v.index], min(cur_dst + src_w, 1.0), 'REPLACE')
                        verts_to_clear.append(v.index)
                        dst_counts[v_best_name] = dst_counts.get(v_best_name, 0) + 1
                    if verts_to_clear:
                        src_vg.remove(verts_to_clear)
            else:
                for mesh in mesh_objects:
                    src_vg = mesh.vertex_groups.get(bone.name)
                    if not src_vg: continue
                    dst_vg = mesh.vertex_groups.get(best_name) or mesh.vertex_groups.new(name=best_name)
                    verts_to_clear = []
                    for v in mesh.data.vertices:
                        src_w = next((g.weight for g in v.groups if g.group == src_vg.index), 0.0)
                        if src_w <= 0.001: continue
                        cur_dst = next((g.weight for g in v.groups if g.group == dst_vg.index), 0.0)
                        dst_vg.add([v.index], min(cur_dst + src_w, 1.0), 'REPLACE')
                        verts_to_clear.append(v.index)
                        dst_counts[best_name] = dst_counts.get(best_name, 0) + 1
                    if verts_to_clear:
                        src_vg.remove(verts_to_clear)

            obj.data.bones[bone.name].use_deform = False
            total_verts = sum(dst_counts.values())
            mode_str = "SPLIT" if needs_split else "WHOLE"
            dist_str = f"质心距{best_dist:.3f}m"
            dst_str = "  ".join(f"{n}({c}v)" for n, c in sorted(dst_counts.items(), key=lambda x: -x[1]))
            print(f"[CTMMD 5] [{mode_str}] {bone.name:<30} -> {dst_str}  [{dist_str}, {total_verts} verts]")
            merged_count += 1

        print(f"[CTMMD 5] Phase 2 summary: merged {merged_count}, skipped {skipped_count}")
        if fallback_warnings:
            print(f"[CTMMD 5] ⚠️  以下 {len(fallback_warnings)} 根骨骼距离超阈值，已跳过，需人工处理：")
            for bname, dist, nearest, bz, vcount in fallback_warnings:
                print(f"[CTMMD 5]   ✗ {bname:<35} dist={dist:.3f}m  Z={bz:.3f}  最近候选={nearest}  顶点数={vcount}")
            print(f"[CTMMD 5]   → 可加入 FORCED_TARGETS 指定目标，或手动在权重绘制里处理")

        print("[CTMMD 5] ===== 5.2: main bones -> D-bones =====")
        cleared_bones = set()
        for base, d_base in D_BONE_PAIRS:
            for side_suffix, side_prefix in SIDES:
                d_name = d_base + side_suffix
                main_name = _get_main_bone_name(obj, base, side_suffix, side_prefix)
                if not main_name:
                    print(f"[CTMMD 5]   {d_name}: source bone not found, skipped")
                    continue
                total = 0
                for mesh in mesh_objects:
                    total += bone_utils.copy_vertex_group_weights(mesh, main_name, d_name)
                for mesh in mesh_objects:
                    main_vg = mesh.vertex_groups.get(main_name)
                    d_vg = mesh.vertex_groups.get(d_name)
                    if not main_vg or not d_vg:
                        continue
                    d_verts = [
                        v.index for v in mesh.data.vertices
                        for g in v.groups if g.group == d_vg.index and g.weight > 0
                    ]
                    if d_verts:
                        main_vg.remove(d_verts)
                cleared_bones.add(main_name)
                print(f"[CTMMD 5]   {main_name} -> {d_name}  {total} verts, source cleared")

        print("[CTMMD 5] ===== Phase 3: Clear Hip Cancel Weights =====")
        for side_suffix in [".L", ".R"]:
            cancel_name = "腰キャンセル" + side_suffix
            cleared = 0
            for mesh in mesh_objects:
                cancel_vg = mesh.vertex_groups.get(cancel_name)
                if cancel_vg:
                    all_verts = [
                        v.index for v in mesh.data.vertices
                        for g in v.groups if g.group == cancel_vg.index and g.weight > 0
                    ]
                    if all_verts:
                        cancel_vg.remove(all_verts)
                        cleared += len(all_verts)
            print(f"[CTMMD 5]   {cancel_name}: cleared {cleared} vertex weights (constraint-driven bone)")

        print("[CTMMD 5] ===== Phase 4: Fix Stray Weights =====")
        stray_threshold = 0.25
        stray_fixed_total = 0

        target_bones_ws = []
        for candidate in obj.data.bones:
            if candidate.name in LOWER_BODY_TARGETS and candidate.use_deform:
                h = obj.matrix_world @ candidate.head_local
                t = obj.matrix_world @ candidate.tail_local
                target_bones_ws.append((candidate.name, h, t))

        for mesh in mesh_objects:
            fixed_count = 0
            mmd_deform_vgs = [
                vg for vg in mesh.vertex_groups
                if not vg.name.startswith("unused ")
                and obj.data.bones.get(vg.name)
                and obj.data.bones[vg.name].use_deform
                and vg.name not in LOWER_BODY_TARGETS
                and not any(k in vg.name for k in ["足", "ひざ", "腰", "D."])
            ]

            for vg in mmd_deform_vgs:
                bone = obj.data.bones.get(vg.name)
                if not bone:
                    continue
                bone_h_ws = obj.matrix_world @ bone.head_local
                bone_t_ws = obj.matrix_world @ bone.tail_local

                stray_verts = []
                for v in mesh.data.vertices:
                    src_w = next((g.weight for g in v.groups if g.group == vg.index), 0.0)
                    if src_w <= 0.001:
                        continue
                    vw = mesh.matrix_world @ v.co
                    dist = _point_to_segment_dist(vw, bone_h_ws, bone_t_ws)
                    if dist > stray_threshold:
                        stray_verts.append((v, src_w, vw))

                if not stray_verts:
                    continue

                for v, src_w, vw in stray_verts:
                    best_name, best_dist = None, float('inf')
                    for tname, th, tt in target_bones_ws:
                        dist = _point_to_segment_dist(vw, th, tt)
                        if dist < best_dist:
                            best_dist = dist
                            best_name = tname
                    if not best_name:
                        continue
                    dst_vg = mesh.vertex_groups.get(best_name) or mesh.vertex_groups.new(name=best_name)
                    cur_dst = next((g.weight for g in v.groups if g.group == dst_vg.index), 0.0)
                    dst_vg.add([v.index], min(cur_dst + src_w, 1.0), 'REPLACE')
                    vg.add([v.index], 0.0, 'REPLACE')
                    fixed_count += 1

                print(f"[CTMMD 5]   {vg.name:<30} -> moved {len(stray_verts):>4} stray verts to nearest target")

            stray_fixed_total += fixed_count

        print(f"[CTMMD 5] Phase 4 complete: fixed {stray_fixed_total} stray verts")

        print("[CTMMD 5] ===== Phase 5: Lower Body Cleanup =====")
        d_bone_names = [d_base + s for _, d_base in D_BONE_PAIRS for s, _ in SIDES]
        total_removed = 0
        for mesh in mesh_objects:
            lower_vg = mesh.vertex_groups.get("下半身")
            if not lower_vg:
                continue
            d_vg_indices = {mesh.vertex_groups[n].index for n in d_bone_names if mesh.vertex_groups.get(n)}
            verts_to_remove = [
                v.index for v in mesh.data.vertices
                if any(g.group in d_vg_indices and g.weight > 0 for g in v.groups)
            ]
            if verts_to_remove:
                lower_vg.remove(verts_to_remove)
                total_removed += len(verts_to_remove)
                print(f"[CTMMD 5]   {mesh.name}: removed {len(verts_to_remove)} D-bone-covered lower-body verts")

        print("[CTMMD 5] ===== Weight Assignment Complete =====")
        self.report({'INFO'}, f"Weight assignment complete: merged {merged_count} unused bones, fixed {stray_fixed_total} stray verts, removed {total_removed} lower-body verts")
        return {'FINISHED'}


TWIST_PAIRS = [
    ("unused bip001 {prefix}foretwist",  "腕捩", "腕", "腕",  "ひじ", 0.6),
    ("unused bip001 {prefix}foretwist1", "手捩", "ひじ", "ひじ", "手首", 0.6),
]

# XPS foretwist -> MMD 捩骨映射表
# (xps骨骼名模板, 捩骨基名, parent骨基名, 位置起点骨基名, 位置终点骨基名, 比例)
# 捩骨长度(参考目标PMX, 约0.082m)
TWIST_BONE_LENGTH = 0.082


def _detect_side_format(armature):
    """检测骨架使用哪种侧边命名格式, 返回 'prefix'(左/右) 或 'suffix'(.L/.R)"""
    bones = armature.data.bones
    if bones.get("左腕") or bones.get("左ひじ"):
        return "prefix"
    return "suffix"


def _twist_bone_name(base, side_fmt, side):
    """生成捩骨名称, side='L' or 'R'。"""
    if side_fmt == "prefix":
        return ("左" if side == "L" else "右") + base
    return base + "." + side


def _arm_bone_name(base, side_fmt, side):
    """生成手臂链骨骼名称。"""
    if side_fmt == "prefix":
        return ("左" if side == "L" else "右") + base
    return base + "." + side


def _xps_foretwist_name(template, side):
    """生成 XPS foretwist 骨骼。"""
    return template.format(prefix="l " if side == "L" else "r ")


def _clear_and_disable(armature_obj, mesh_objects, bone_name):
    """清除所有网格中指定顶点组的权重, 并禁用对应骨骼的变形。"""
    for mesh in mesh_objects:
        src_vg = mesh.vertex_groups.get(bone_name)
        if src_vg:
            rm = [
                v.index for v in mesh.data.vertices
                for g in v.groups if g.group == src_vg.index and g.weight > 0
            ]
            if rm:
                src_vg.remove(rm)
    if bone_name in armature_obj.data.bones:
        armature_obj.data.bones[bone_name].use_deform = False


class OBJECT_OT_complete_twist_bones(bpy.types.Operator):
    """补全扭转骨(腕捩/手捩),并从XPS foretwist迁移权重"""
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

        print("[CTMMD 2.1] ===== Step 2.1: Create Twist Bones =====")
        side_fmt = _detect_side_format(obj)
        print(f"[CTMMD 2.1]   Naming mode: {'prefix(left/right)' if side_fmt == 'prefix' else 'suffix(.L/.R)'}")

        bpy.ops.object.mode_set(mode='EDIT')
        edit_bones = obj.data.edit_bones

        created = []
        skipped = []

        for xps_template, twist_base, parent_base, from_base, to_base, ratio in TWIST_PAIRS:
            for side in ["L", "R"]:
                twist_name = _twist_bone_name(twist_base, side_fmt, side)
                parent_name = _arm_bone_name(parent_base, side_fmt, side)
                from_name = _arm_bone_name(from_base, side_fmt, side)
                to_name = _arm_bone_name(to_base, side_fmt, side)

                from_bone = edit_bones.get(from_name)
                to_bone = edit_bones.get(to_name)
                if not from_bone or not to_bone:
                    skipped.append(f"{twist_name}(主骨 {from_name}/{to_name} 不存在)")
                    continue

                if edit_bones.get(twist_name):
                    skipped.append(f"{twist_name} 已存在")
                    continue

                direction = (to_bone.head - from_bone.head).normalized()
                head = from_bone.head + ratio * (to_bone.head - from_bone.head)
                tail = head + direction * TWIST_BONE_LENGTH

                bone_utils.create_or_update_bone(
                    edit_bones, twist_name,
                    head, tail,
                    use_connect=False,
                    parent_name=parent_name,
                    use_deform=True
                )
                print(f"[CTMMD 2.1]   Created: {twist_name:<10} head=({head.x:.3f},{head.y:.3f},{head.z:.3f})  parent={parent_name}")
                created.append(twist_name)

        bpy.ops.object.mode_set(mode='OBJECT')

        print("[CTMMD 2.1] -- Weight Transfer --")
        for xps_template, twist_base, parent_base, from_base, to_base, ratio in TWIST_PAIRS:
            for side in ["L", "R"]:
                twist_name = _twist_bone_name(twist_base, side_fmt, side)
                xps_name = _xps_foretwist_name(xps_template, side)
                elbow_name = _arm_bone_name("ひじ", side_fmt, side)
                if not any(_vg_has_weight(m, xps_name) for m in mesh_objects):
                    print(f"[CTMMD 2.1]   Skipped: {xps_name} has no weighted verts")
                    continue

                is_foretwist = (twist_base == "腕捩")

                if is_foretwist:
                    from_name = _arm_bone_name(from_base, side_fmt, side)
                    to_name = _arm_bone_name(to_base, side_fmt, side)
                    from_pb = obj.pose.bones.get(from_name)
                    to_pb = obj.pose.bones.get(to_name)
                    if not from_pb or not to_pb:
                        print(f"[CTMMD 2.1]   [WARN] Gradient split failed (missing source bones), fallback to full transfer -> {twist_name}")
                        total = 0
                        for mesh in mesh_objects:
                            total += _merge_weights_additive(mesh, xps_name, twist_name)
                        _clear_and_disable(obj, mesh_objects, xps_name)
                        print(f"[CTMMD 2.1]   {xps_name:<42} -> {twist_name:<10}  {total} verts [disabled]")
                        continue

                    seg_from_ws = obj.matrix_world @ from_pb.head
                    seg_to_ws = obj.matrix_world @ to_pb.head

                    total_e = total_t = 0
                    for mesh in mesh_objects:
                        _, ne, nt = _split_weights_gradient(
                            mesh, xps_name, elbow_name, twist_name,
                            seg_from_ws, seg_to_ws
                        )
                        total_e += ne
                        total_t += nt

                    _clear_and_disable(obj, mesh_objects, xps_name)
                    print(f"[CTMMD 2.1]   {xps_name:<42} -> {elbow_name}({total_e}v) + {twist_name}({total_t}v) [gradient] [disabled]")
                else:
                    total = 0
                    for mesh in mesh_objects:
                        total += _merge_weights_additive(mesh, xps_name, twist_name)
                    _clear_and_disable(obj, mesh_objects, xps_name)
                    print(f"[CTMMD 2.1]   {xps_name:<42} -> {twist_name:<10}  {total} verts [disabled]")

        print(f"[CTMMD 2.1] Done: created {len(created)}, skipped {len(skipped)}")
        for s in skipped:
            print(f"[CTMMD 2.1]   Skipped: {s}")
        self.report({"INFO"}, f"Twist bone setup complete: created {len(created)}")
        return {'FINISHED'}


# 目标 PMX 分析得出的参数(单位: Blender units = PMX坐标 / 12.2)
UPPER3_HEAD_Z = 1.3118          # 上半身3骨骼 head Z(硬切割阈值)
UPPER3_BLEND_START_Z = 1.2725   # 目标PMX中上半身3权重开始出现的Z(渐变起点)
UPPER3_SOURCE_BONES = ["上半身", "上半身1", "上半身2", "上半身3"]
UPPER3_TARGET_BONE = "上半身3"


class OBJECT_OT_assign_upper3_weights(bpy.types.Operator):
    """将上半身链高 Z 区域的权重重新分配给上半身3。"""
    bl_idname = "object.assign_upper3_weights"
    bl_label = "Assign Upper3 Weights"

    mode: bpy.props.EnumProperty(
        name="模式",
        items=[
            ('HARD_CUT', '硬切', 'Z > 1.3118 的顶点权重全部移入上半身3'),
            ('PROPORTIONAL', '渐变过渡', '在过渡区 Z=[1.2725,1.3118] 内线性混合'),
        ],
        default='HARD_CUT'
    )

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
        if not mesh_objects:
            self.report({"ERROR"}, "No skinned mesh objects found")
            return {'CANCELLED'}

        mode_label = "硬切" if self.mode == 'HARD_CUT' else "渐变过渡"
        print(f"[CTMMD 2.6] ===== Upper Body 3 Weight Assignment ({mode_label}) =====")
        print(f"[CTMMD 2.6]   Source bones: {UPPER3_SOURCE_BONES}")
        print(f"[CTMMD 2.6]   Target bone: {UPPER3_TARGET_BONE}")
        if self.mode == 'HARD_CUT':
            print(f"[CTMMD 2.6]   Cut line: Z > {UPPER3_HEAD_Z}")
        else:
            print(f"[CTMMD 2.6]   Blend zone: Z=[{UPPER3_BLEND_START_Z}, {UPPER3_HEAD_Z}], above = 100% to upper body 3")

        total_transferred = 0
        total_vertices = 0

        for mesh in mesh_objects:
            dst_vg = mesh.vertex_groups.get(UPPER3_TARGET_BONE) or mesh.vertex_groups.new(name=UPPER3_TARGET_BONE)

            mesh_transferred = 0
            mesh_vertices = 0

            for src_name in UPPER3_SOURCE_BONES:
                src_vg = mesh.vertex_groups.get(src_name)
                if not src_vg:
                    continue

                for v in mesh.data.vertices:
                    src_w = 0.0
                    for g in v.groups:
                        if g.group == src_vg.index:
                            src_w = g.weight
                            break
                    if src_w <= 0:
                        continue

                    z = (mesh.matrix_world @ v.co).z

                    if self.mode == 'HARD_CUT':
                        if z <= UPPER3_HEAD_Z:
                            continue
                        ratio = 1.0
                    else:
                        if z <= UPPER3_BLEND_START_Z:
                            continue
                        if z >= UPPER3_HEAD_Z:
                            ratio = 1.0
                        else:
                            ratio = (z - UPPER3_BLEND_START_Z) / (UPPER3_HEAD_Z - UPPER3_BLEND_START_Z)

                    transfer_w = src_w * ratio
                    remain_w = src_w * (1.0 - ratio)

                    dst_w = 0.0
                    for g in v.groups:
                        if g.group == dst_vg.index:
                            dst_w = g.weight
                            break
                    new_dst_w = min(dst_w + transfer_w, 1.0)

                    dst_vg.add([v.index], new_dst_w, 'REPLACE')
                    if remain_w > 0.001:
                        src_vg.add([v.index], remain_w, 'REPLACE')
                    else:
                        src_vg.remove([v.index])

                    mesh_transferred += transfer_w
                    mesh_vertices += 1

            total_transferred += mesh_transferred
            total_vertices += mesh_vertices
            if mesh_vertices > 0:
                print(f"[CTMMD 2.6]   {mesh.name}: processed {mesh_vertices} verts, transferred {mesh_transferred:.1f} weight")

        print("[CTMMD 2.6] ===== Complete =====")
        for src_name in UPPER3_SOURCE_BONES + [UPPER3_TARGET_BONE]:
            zs = []
            cnt = 0
            for mesh in mesh_objects:
                vg = mesh.vertex_groups.get(src_name)
                if not vg:
                    continue
                for v in mesh.data.vertices:
                    for g in v.groups:
                        if g.group == vg.index and g.weight > 0.01:
                            zs.append((mesh.matrix_world @ v.co).z)
                            cnt += 1
            if cnt:
                print(f"[CTMMD 2.6]   {src_name:<6}: {cnt:5d} verts  Z=[{min(zs):.3f}, {max(zs):.3f}]")
            else:
                print(f"[CTMMD 2.6]   {src_name:<6}: 0 verts")

        self.report({"INFO"}, f"Upper body 3 weight assignment complete ({mode_label}): processed {total_vertices} verts")
        return {'FINISHED'}


# ─── 5.1: 阶段1 - D骨赋值 ──────────────────────────────────────────────────────────

class OBJECT_OT_assign_weights_phase1(bpy.types.Operator):
    """阶段1:从主骨复制权重到D骨,清零主骨"""
    bl_idname = "object.assign_weights_phase1"
    bl_label = "5.2 主骨→D骨"

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "Please select an armature object")
            return {'CANCELLED'}

        mesh_objects = [
            o for o in bpy.data.objects
            if o.type == 'MESH' and any(
                m.type == 'ARMATURE' and m.object == obj
                for m in o.modifiers
            )
        ]
        if not mesh_objects:
            self.report({'ERROR'}, "No skinned mesh objects found")
            return {'CANCELLED'}

        print("[CTMMD 5.2] ===== Phase 1: D-bones <- Main Bones =====")

        for base, d_base in D_BONE_PAIRS:
            for side_suffix, side_prefix in SIDES:
                d_name = d_base + side_suffix
                main_name = _get_main_bone_name(obj, base, side_suffix, side_prefix)
                if not main_name:
                    print(f"[CTMMD 5.2]   {d_name}: source bone not found, skipped")
                    continue
                total = 0
                for mesh in mesh_objects:
                    n = bone_utils.copy_vertex_group_weights(mesh, main_name, d_name)
                    total += n
                for mesh in mesh_objects:
                    main_vg = mesh.vertex_groups.get(main_name)
                    d_vg = mesh.vertex_groups.get(d_name)
                    if not main_vg or not d_vg:
                        continue
                    d_verts = [v.index for v in mesh.data.vertices
                               for g in v.groups if g.group == d_vg.index and g.weight > 0]
                    if d_verts:
                        main_vg.remove(d_verts)
                print(f"[CTMMD 5.2]   {d_name} <- {main_name}  {total} verts, source cleared")

        print("[CTMMD 5.2] ===== Phase 1 Complete =====")
        self.report({'INFO'}, "Phase 1 complete: D-bone weights copied. Check the result in Weight Paint.")
        return {'FINISHED'}


# ─── 5.2: 阶段2 - unused合并 ────────────────────────────────────────────────────────

class OBJECT_OT_assign_weights_phase2(bpy.types.Operator):
    """阶段2:将unused骨的权重逐顶点分配到最近的目标骨"""
    bl_idname = "object.assign_weights_phase2"
    bl_label = "5.1 Unused→主骨"

    DISTANCE_THRESHOLD: bpy.props.FloatProperty(default=0.15)

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "Please select an armature object")
            return {'CANCELLED'}

        mesh_objects = [
            o for o in bpy.data.objects
            if o.type == 'MESH' and any(
                m.type == 'ARMATURE' and m.object == obj
                for m in o.modifiers
            )
        ]
        if not mesh_objects:
            self.report({'ERROR'}, "No skinned mesh objects found")
            return {'CANCELLED'}

        print("[CTMMD 5.1] ===== Phase 2: unused bones -> target bones (per-vertex) =====")
        all_unused_names = {b.name for b in obj.data.bones if b.name.startswith("unused ")}
        unused_bones = [
            b for b in obj.data.bones
            if b.name.startswith("unused ") and b.use_deform
            and any(_vg_has_weight(m, b.name) for m in mesh_objects)
        ]

        target_candidates = []
        for candidate in obj.data.bones:
            if candidate.name in all_unused_names or not candidate.use_deform:
                continue
            if candidate.name not in PHASE2_TARGETS:
                continue
            ch = obj.matrix_world @ candidate.head_local
            ct = obj.matrix_world @ candidate.tail_local
            target_candidates.append((candidate.name, ch, ct))

        merged_count = 0
        skipped_count = 0
        fallback_warnings = []  # 收集超阈值骨骼，步骤结束后提示人工处理

        for bone in unused_bones:
            # ── 强制目标检查：骨骼名包含关键字时直接整骨转移，不做距离判断 ──
            forced_target = None
            for kw, tgt in FORCED_TARGETS.items():
                if kw in bone.name.lower() and obj.data.bones.get(tgt):
                    forced_target = tgt; break
            if forced_target:
                total_moved = 0
                for mesh in mesh_objects:
                    src_vg = mesh.vertex_groups.get(bone.name)
                    if not src_vg: continue
                    dst_vg = mesh.vertex_groups.get(forced_target) or mesh.vertex_groups.new(name=forced_target)
                    verts_to_clear = []
                    for v in mesh.data.vertices:
                        src_w = next((g.weight for g in v.groups if g.group == src_vg.index), 0.0)
                        if src_w <= 0.001: continue
                        cur_dst = next((g.weight for g in v.groups if g.group == dst_vg.index), 0.0)
                        dst_vg.add([v.index], min(cur_dst + src_w, 1.0), 'REPLACE')
                        verts_to_clear.append(v.index)
                        total_moved += 1
                    if verts_to_clear:
                        src_vg.remove(verts_to_clear)
                obj.data.bones[bone.name].use_deform = False
                print(f"[CTMMD 5.1] [FORCED] {bone.name:<30} -> {forced_target} ({total_moved} verts)")
                merged_count += 1
                continue

            src_pos = _vertex_centroid(bone.name, mesh_objects) or (obj.matrix_world @ bone.head_local)
            best_name, best_dist = None, float('inf')
            for cname, ch, ct in target_candidates:
                d = _point_to_segment_dist(src_pos, ch, ct)
                if d < best_dist:
                    best_dist = d; best_name = cname
            if not best_name:
                print(f"[CTMMD 5.1] [WARN] {bone.name:<30} no candidate, skipped")
                skipped_count += 1
                continue
            src_side = _guess_side(bone, mesh_objects)

            if best_dist >= self.DISTANCE_THRESHOLD:
                # 超阈值：跳过自动处理，记录到 fallback_warnings 提示人工处理
                vcount = sum(
                    1 for mesh in mesh_objects
                    for v in mesh.data.vertices
                    for g in v.groups
                    if mesh.vertex_groups.get(bone.name) and
                       g.group == mesh.vertex_groups[bone.name].index and g.weight > 0.01
                )
                fallback_warnings.append((bone.name, best_dist, best_name, src_pos.z, vcount))
                print(f"[CTMMD 5.1] [SKIP] {bone.name:<30} dist {best_dist:.3f}m > threshold, Z={src_pos.z:.3f}, nearest={best_name}, {vcount} verts — 需人工处理")
                skipped_count += 1
                continue

            # ── 判断是否需要 per-vertex 拆分 ──
            needs_split = any(kw in bone.name.lower() for kw in SPLIT_BONES)

            dst_counts = {}
            if needs_split:
                # per-vertex 拆分：每个顶点单独找最近候选（含Z上限过滤）
                for mesh in mesh_objects:
                    src_vg = mesh.vertex_groups.get(bone.name)
                    if not src_vg: continue
                    verts_to_clear = []
                    for v in mesh.data.vertices:
                        src_w = next((g.weight for g in v.groups if g.group == src_vg.index), 0.0)
                        if src_w <= 0.001: continue
                        vw = mesh.matrix_world @ v.co

                        filtered = target_candidates
                        if src_side:
                            same_side = [(n, h, t) for n, h, t in target_candidates
                                         if _side_of_mmd_bone(n) == src_side or _side_of_mmd_bone(n) is None]
                            if same_side:
                                filtered = same_side

                        # Z上限过滤：臀部顶点不进腿骨
                        HIP_TOLERANCE = 0.05
                        z_filtered = [(n, h, t) for n, h, t in filtered
                                      if not (_is_leg_bone(n) and vw.z > max(h.z, t.z) + HIP_TOLERANCE)]
                        if z_filtered:
                            filtered = z_filtered

                        v_best_name, v_best_dist = None, float('inf')
                        for cname, ch, ct in filtered:
                            d = _point_to_segment_dist(vw, ch, ct)
                            if d < v_best_dist:
                                v_best_dist = d; v_best_name = cname
                        if not v_best_name: continue

                        dst_vg = mesh.vertex_groups.get(v_best_name) or mesh.vertex_groups.new(name=v_best_name)
                        cur_dst = next((g.weight for g in v.groups if g.group == dst_vg.index), 0.0)
                        dst_vg.add([v.index], min(cur_dst + src_w, 1.0), 'REPLACE')
                        verts_to_clear.append(v.index)
                        dst_counts[v_best_name] = dst_counts.get(v_best_name, 0) + 1
                    if verts_to_clear:
                        src_vg.remove(verts_to_clear)
            else:
                # 整骨转移：全部顶点统一迁移到 best_name
                for mesh in mesh_objects:
                    src_vg = mesh.vertex_groups.get(bone.name)
                    if not src_vg: continue
                    dst_vg = mesh.vertex_groups.get(best_name) or mesh.vertex_groups.new(name=best_name)
                    verts_to_clear = []
                    for v in mesh.data.vertices:
                        src_w = next((g.weight for g in v.groups if g.group == src_vg.index), 0.0)
                        if src_w <= 0.001: continue
                        cur_dst = next((g.weight for g in v.groups if g.group == dst_vg.index), 0.0)
                        dst_vg.add([v.index], min(cur_dst + src_w, 1.0), 'REPLACE')
                        verts_to_clear.append(v.index)
                        dst_counts[best_name] = dst_counts.get(best_name, 0) + 1
                    if verts_to_clear:
                        src_vg.remove(verts_to_clear)

            obj.data.bones[bone.name].use_deform = False
            total_verts = sum(dst_counts.values())
            mode_str = "SPLIT" if needs_split else "WHOLE"
            dist_str = f"质心距{best_dist:.3f}m"
            dst_str = "  ".join(f"{n}({c}v)" for n, c in sorted(dst_counts.items(), key=lambda x: -x[1]))
            print(f"[CTMMD 5.1] [{mode_str}] {bone.name:<30} -> {dst_str}  [{dist_str}, {total_verts} verts]")
            merged_count += 1

        print(f"[CTMMD 5.1] ===== Phase 2 Complete: merged {merged_count}, skipped {skipped_count} =====")
        if fallback_warnings:
            print(f"[CTMMD 5.1] ⚠️  以下 {len(fallback_warnings)} 根骨骼距离超阈值，已跳过，需人工处理：")
            for bname, dist, nearest, bz, vcount in fallback_warnings:
                print(f"[CTMMD 5.1]   ✗ {bname:<35} dist={dist:.3f}m  Z={bz:.3f}  最近候选={nearest}  顶点数={vcount}")
            print(f"[CTMMD 5.1]   → 可加入 FORCED_TARGETS 指定目标，或手动在权重绘制里处理")
        self.report({'INFO'}, f"Phase 2: merged {merged_count}, skipped {skipped_count}" +
                    (f", ⚠️ {len(fallback_warnings)} need manual fix" if fallback_warnings else ""))
        return {'FINISHED'}


# ─── 5.3: 阶段3 - 腰キャンセル清空 ──────────────────────────────────────────────────

class OBJECT_OT_assign_weights_phase3(bpy.types.Operator):
    """阶段3:清空腰キャンセル权重(通过约束工作,无需直接权重)"""
    bl_idname = "object.assign_weights_phase3"
    bl_label = "5.3 腰キャンセル清空"

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "Please select an armature object")
            return {'CANCELLED'}

        mesh_objects = [
            o for o in bpy.data.objects
            if o.type == 'MESH' and any(
                m.type == 'ARMATURE' and m.object == obj
                for m in o.modifiers
            )
        ]
        if not mesh_objects:
            self.report({'ERROR'}, "No skinned mesh objects found")
            return {'CANCELLED'}

        print("[CTMMD 5.3] ===== Phase 3: Clear Hip Cancel Weights =====")
        for side_suffix in [".L", ".R"]:
            cancel_name = "腰キャンセル" + side_suffix
            cleared = 0
            for mesh in mesh_objects:
                cancel_vg = mesh.vertex_groups.get(cancel_name)
                if cancel_vg:
                    all_verts = [v.index for v in mesh.data.vertices
                                 for g in v.groups if g.group == cancel_vg.index and g.weight > 0]
                    if all_verts:
                        cancel_vg.remove(all_verts)
                        cleared += len(all_verts)
            print(f"[CTMMD 5.3]   {cancel_name}: cleared {cleared} vertex weights")

        print("[CTMMD 5.3] ===== Phase 3 Complete =====")
        self.report({'INFO'}, "Phase 3 complete: hip cancel weights cleared")
        return {'FINISHED'}


# ─── 5.4: 阶段4 - 迷路权重修复 ──────────────────────────────────────────────────

class OBJECT_OT_assign_weights_phase4(bpy.types.Operator):
    """阶段4:修复迷路权重(顶点在空间上远离骨骼但权重挂在其上)"""
    bl_idname = "object.assign_weights_phase4"
    bl_label = "5.4 迷路权重修复"

    STRAY_THRESHOLD: bpy.props.FloatProperty(default=0.25)

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "Please select an armature object")
            return {'CANCELLED'}

        mesh_objects = [
            o for o in bpy.data.objects
            if o.type == 'MESH' and any(
                m.type == 'ARMATURE' and m.object == obj
                for m in o.modifiers
            )
        ]
        if not mesh_objects:
            self.report({'ERROR'}, "No skinned mesh objects found")
            return {'CANCELLED'}

        print("[CTMMD 5.4] ===== Phase 4: Fix Stray Weights =====")

        target_bones_ws = []
        for candidate in obj.data.bones:
            if candidate.name in LOWER_BODY_TARGETS and candidate.use_deform:
                h = obj.matrix_world @ candidate.head_local
                t = obj.matrix_world @ candidate.tail_local
                target_bones_ws.append((candidate.name, h, t))

        stray_fixed_total = 0
        for mesh in mesh_objects:
            fixed_count = 0
            mmd_deform_vgs = [
                vg for vg in mesh.vertex_groups
                if not vg.name.startswith("unused ")
                and obj.data.bones.get(vg.name)
                and obj.data.bones[vg.name].use_deform
                and vg.name not in LOWER_BODY_TARGETS
                and not any(k in vg.name for k in ["足", "ひざ", "腰", "D."])
            ]

            for vg in mmd_deform_vgs:
                bone = obj.data.bones.get(vg.name)
                if not bone:
                    continue
                bone_h_ws = obj.matrix_world @ bone.head_local
                bone_t_ws = obj.matrix_world @ bone.tail_local

                stray_verts = []
                for v in mesh.data.vertices:
                    src_w = next((g.weight for g in v.groups if g.group == vg.index), 0.0)
                    if src_w <= 0.001:
                        continue
                    vw = mesh.matrix_world @ v.co
                    dist = _point_to_segment_dist(vw, bone_h_ws, bone_t_ws)
                    if dist > self.STRAY_THRESHOLD:
                        stray_verts.append((v, src_w, vw))

                if not stray_verts:
                    continue

                for v, src_w, vw in stray_verts:
                    best_name, best_dist = None, float('inf')
                    for tname, th, tt in target_bones_ws:
                        d = _point_to_segment_dist(vw, th, tt)
                        if d < best_dist:
                            best_dist = d
                            best_name = tname
                    if not best_name:
                        continue
                    dst_vg = mesh.vertex_groups.get(best_name) or mesh.vertex_groups.new(name=best_name)
                    cur_dst = next((g.weight for g in v.groups if g.group == dst_vg.index), 0.0)
                    dst_vg.add([v.index], min(cur_dst + src_w, 1.0), 'REPLACE')
                    vg.add([v.index], 0.0, 'REPLACE')
                    fixed_count += 1

                if stray_verts:
                    print(f"[CTMMD 5.4]   {vg.name:<30} -> moved {len(stray_verts):>4} stray verts to nearest target")

            stray_fixed_total += fixed_count

        print(f"[CTMMD 5.4] ===== Phase 4 Complete: fixed {stray_fixed_total} stray verts =====")
        self.report({'INFO'}, f"Phase 4 complete: fixed {stray_fixed_total} stray verts")
        return {'FINISHED'}


# ─── 5.5: 阶段5 - 下半身清理 ────────────────────────────────────────────────────────

class OBJECT_OT_assign_weights_phase5(bpy.types.Operator):
    """阶段5:从下半身移除已被D骨覆盖的顶点"""
    bl_idname = "object.assign_weights_phase5"
    bl_label = "5.5 下半身清理"

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "Please select an armature object")
            return {'CANCELLED'}

        mesh_objects = [
            o for o in bpy.data.objects
            if o.type == 'MESH' and any(
                m.type == 'ARMATURE' and m.object == obj
                for m in o.modifiers
            )
        ]
        if not mesh_objects:
            self.report({'ERROR'}, "No skinned mesh objects found")
            return {'CANCELLED'}

        print("[CTMMD 5.5] ===== Phase 5: Lower Body Cleanup =====")
        d_bone_names = [d_base + s for _, d_base in D_BONE_PAIRS for s, _ in SIDES]
        total_removed = 0
        for mesh in mesh_objects:
            lower_vg = mesh.vertex_groups.get("下半身")
            if not lower_vg:
                continue
            d_vg_indices = {mesh.vertex_groups[n].index for n in d_bone_names if mesh.vertex_groups.get(n)}
            verts_to_remove = [
                v.index for v in mesh.data.vertices
                if any(g.group in d_vg_indices and g.weight > 0 for g in v.groups)
            ]
            if verts_to_remove:
                lower_vg.remove(verts_to_remove)
                total_removed += len(verts_to_remove)
                print(f"[CTMMD 5.5]   {mesh.name}: removed {len(verts_to_remove)} D-bone-covered lower-body verts")

        print(f"[CTMMD 5.5] ===== Phase 5 Complete: removed {total_removed} verts =====")
        self.report({'INFO'}, f"Phase 5 complete: removed {total_removed} lower-body verts")
        return {'FINISHED'}


# ─── 5.6: 阶段6 - 未处理顶点组诊断 ──────────────────────────────────────────────────

class OBJECT_OT_assign_weights_phase6(bpy.types.Operator):
    """扫描仍有权重的 unused 骨骼（5.1 尚未处理的），按会怎么处理输出诊断到 log，不修改任何权重"""
    bl_idname = "object.assign_weights_phase6"
    bl_label = "5.6 未处理诊断"

    DISTANCE_THRESHOLD: bpy.props.FloatProperty(default=0.15)

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "Please select an armature object")
            return {'CANCELLED'}

        mesh_objects = [
            o for o in bpy.data.objects
            if o.type == 'MESH' and any(
                m.type == 'ARMATURE' and m.object == obj
                for m in o.modifiers
            )
        ]
        if not mesh_objects:
            self.report({'ERROR'}, "No skinned mesh objects found")
            return {'CANCELLED'}

        print("[CTMMD 5.6] ===== Phase 6: Unprocessed Vertex Group Diagnostic =====")

        # 收集仍有权重的 unused 骨骼（use_deform=True + verts>0）
        all_unused_names = {b.name for b in obj.data.bones if b.name.startswith("unused ")}
        remaining = []
        for b in obj.data.bones:
            if not b.name.startswith("unused ") or not b.use_deform:
                continue
            vcount = sum(
                1 for mesh in mesh_objects
                for v in mesh.data.vertices
                for g in v.groups
                if mesh.vertex_groups.get(b.name) and
                   g.group == mesh.vertex_groups[b.name].index and g.weight > 0.01
            )
            if vcount > 0:
                remaining.append((b, vcount))

        if not remaining:
            print("[CTMMD 5.6] ✓ 所有 unused 骨骼均已处理，无残留权重")
            self.report({'INFO'}, "5.6: 无残留 unused 骨骼")
            return {'FINISHED'}

        # 构建候选列表（与 5.1 相同逻辑）
        target_candidates = []
        for candidate in obj.data.bones:
            if candidate.name in all_unused_names or not candidate.use_deform:
                continue
            if candidate.name not in PHASE2_TARGETS:
                continue
            ch = obj.matrix_world @ candidate.head_local
            ct = obj.matrix_world @ candidate.tail_local
            target_candidates.append((candidate.name, ch, ct))

        print(f"[CTMMD 5.6] 发现 {len(remaining)} 根 unused 骨骼仍有残留权重：")

        forced_list = []
        would_skip = []
        would_process = []

        for bone, vcount in remaining:
            # 判断是否命中 FORCED_TARGETS
            forced_target = None
            for kw, tgt in FORCED_TARGETS.items():
                if kw in bone.name.lower() and obj.data.bones.get(tgt):
                    forced_target = tgt
                    break
            if forced_target:
                forced_list.append((bone.name, vcount, forced_target))
                print(f"[CTMMD 5.6]   FORCED  {bone.name:<35} {vcount:>5}v  → {forced_target}")
                continue

            # 计算质心
            src_pos = _vertex_centroid(bone.name, mesh_objects) or (obj.matrix_world @ bone.head_local)
            best_name, best_dist = None, float('inf')
            for cname, ch, ct in target_candidates:
                d = _point_to_segment_dist(src_pos, ch, ct)
                if d < best_dist:
                    best_dist = d
                    best_name = cname

            if not best_name:
                print(f"[CTMMD 5.6]   WARN    {bone.name:<35} {vcount:>5}v  → 无候选骨骼")
                continue

            needs_split = any(kw in bone.name.lower() for kw in SPLIT_BONES)
            mode = "SPLIT" if needs_split else "WHOLE"

            if best_dist >= self.DISTANCE_THRESHOLD:
                would_skip.append((bone.name, vcount, best_name, best_dist, src_pos.z))
                print(f"[CTMMD 5.6]   SKIP    {bone.name:<35} {vcount:>5}v  dist={best_dist:.3f}m  Z={src_pos.z:.3f}  最近={best_name}")
            else:
                would_process.append((bone.name, vcount, best_name, best_dist, mode))
                print(f"[CTMMD 5.6]   {mode:<6}  {bone.name:<35} {vcount:>5}v  dist={best_dist:.3f}m  → {best_name}")

        print(f"[CTMMD 5.6] ─────────────────────────────────────────────────────────")
        print(f"[CTMMD 5.6] 汇总：FORCED={len(forced_list)}  可自动={len(would_process)}  需人工={len(would_skip)}")
        if would_skip:
            print(f"[CTMMD 5.6] ⚠️  以下骨骼超距离阈值，需人工处理（可加入 FORCED_TARGETS 或手动权重绘制）：")
            for bname, vc, nearest, dist, bz in would_skip:
                print(f"[CTMMD 5.6]   ✗ {bname:<35} {vc:>4}v  dist={dist:.3f}m  Z={bz:.3f}  建议目标={nearest}")
        if would_process:
            print(f"[CTMMD 5.6] 💡 以下骨骼仍可被 5.1 自动处理：")
            for bname, vc, nearest, dist, mode in would_process:
                print(f"[CTMMD 5.6]   ○ {bname:<35} {vc:>4}v  dist={dist:.3f}m  → {nearest}  [{mode}]")

        self.report({'INFO'}, f"5.6: {len(remaining)} 残留 ({len(would_skip)} 需人工, {len(would_process)} 可自动, {len(forced_list)} FORCED)")
        return {'FINISHED'}
