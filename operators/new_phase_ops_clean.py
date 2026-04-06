

# ─── 5.1: 阶段1 - D骨赋值 ──────────────────────────────────────────────────────────

class OBJECT_OT_assign_weights_phase1(bpy.types.Operator):
    """阶段1：从主骨复制权重到D骨，清零主骨"""
    bl_idname = "object.assign_weights_phase1"
    bl_label = "5.1 D骨赋值"

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "请选择骨架对象")
            return {'CANCELLED'}

        mesh_objects = [
            o for o in bpy.data.objects
            if o.type == 'MESH' and any(
                m.type == 'ARMATURE' and m.object == obj
                for m in o.modifiers
            )
        ]
        if not mesh_objects:
            self.report({'ERROR'}, "未找到关联网格")
            return {'CANCELLED'}

        print("[CTMMD 5.1] ===== 阶段1：D骨 ← 主骨 ======")

        for base, d_base in D_BONE_PAIRS:
            for side_suffix, side_prefix in SIDES:
                d_name = d_base + side_suffix
                main_name = _get_main_bone_name(obj, base, side_suffix, side_prefix)
                if not main_name:
                    print(f"[CTMMD 5.1]   {d_name}: 主骨不存在，跳过")
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
                print(f"[CTMMD 5.1]   {d_name} ← {main_name}  {total} 顶点，主骨已清零")

        print("[CTMMD 5.1] ===== 阶段1完成 =====")
        self.report({'INFO'}, "阶段1完成：D骨赋值完成，请在 weight paint 中检查")
        return {'FINISHED'}


# ─── 5.2: 阶段2 - unused合并 ────────────────────────────────────────────────────────

class OBJECT_OT_assign_weights_phase2(bpy.types.Operator):
    """阶段2：将unused骨的权重逐顶点分配到最近的目标骨"""
    bl_idname = "object.assign_weights_phase2"
    bl_label = "5.2 Unused合并"

    DISTANCE_THRESHOLD: bpy.props.FloatProperty(default=0.15)

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "请选择骨架对象")
            return {'CANCELLED'}

        mesh_objects = [
            o for o in bpy.data.objects
            if o.type == 'MESH' and any(
                m.type == 'ARMATURE' and m.object == obj
                for m in o.modifiers
            )
        ]
        if not mesh_objects:
            self.report({'ERROR'}, "未找到关联网格")
            return {'CANCELLED'}

        print("[CTMMD 5.2] ===== 阶段2：unused骨 → 目标骨（逐顶点）=====")
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

        for bone in unused_bones:
            src_pos = _vertex_centroid(bone.name, mesh_objects) or (obj.matrix_world @ bone.head_local)
            best_name, best_dist = None, float('inf')
            for cname, ch, ct in target_candidates:
                d = _point_to_segment_dist(src_pos, ch, ct)
                if d < best_dist:
                    best_dist = d; best_name = cname
            if not best_name:
                print(f"[CTMMD 5.2] ⚠ {bone.name:<30} 无候选，跳过")
                skipped_count += 1
                continue
            if best_dist >= self.DISTANCE_THRESHOLD:
                print(f"[CTMMD 5.2] ⚠ {bone.name:<30} → {best_name:<12} 质心距{best_dist:.3f}m 超阈值，跳过")
                skipped_count += 1
                continue

            src_side = _guess_side(bone, mesh_objects)

            dst_counts = {}
            for mesh in mesh_objects:
                src_vg = mesh.vertex_groups.get(bone.name)
                if not src_vg:
                    continue
                verts_to_clear = []
                for v in mesh.data.vertices:
                    src_w = next((g.weight for g in v.groups if g.group == src_vg.index), 0.0)
                    if src_w <= 0.001:
                        continue
                    vw = mesh.matrix_world @ v.co

                    filtered = target_candidates
                    if src_side:
                        same_side = [(n, h, t) for n, h, t in target_candidates
                                     if _side_of_mmd_bone(n) == src_side or _side_of_mmd_bone(n) is None]
                        if same_side:
                            filtered = same_side

                    v_best_name, v_best_dist = None, float('inf')
                    for cname, ch, ct in filtered:
                        d = _point_to_segment_dist(vw, ch, ct)
                        if d < v_best_dist:
                            v_best_dist = d; v_best_name = cname

                    if not v_best_name or v_best_dist >= self.DISTANCE_THRESHOLD:
                        continue

                    dst_vg = mesh.vertex_groups.get(v_best_name) or mesh.vertex_groups.new(name=v_best_name)
                    cur_dst = next((g.weight for g in v.groups if g.group == dst_vg.index), 0.0)
                    dst_vg.add([v.index], min(cur_dst + src_w, 1.0), 'REPLACE')
                    verts_to_clear.append(v.index)
                    dst_counts[v_best_name] = dst_counts.get(v_best_name, 0) + 1

                if verts_to_clear:
                    src_vg.remove(verts_to_clear)

            obj.data.bones[bone.name].use_deform = False
            total_verts = sum(dst_counts.values())
            dist_str = f"质心距{best_dist:.3f}m"
            dst_str = "  ".join(f"{n}({c}v)" for n, c in sorted(dst_counts.items(), key=lambda x: -x[1]))
            print(f"[CTMMD 5.2] ✓ {bone.name:<30} → {dst_str}  [{dist_str}  共{total_verts}顶点] [已禁用]")
            merged_count += 1

        print(f"[CTMMD 5.2] ===== 阶段2完成：合并{merged_count}个，跳过{skipped_count}个 =====")
        self.report({'INFO'}, f"阶段2完成：合并{merged_count}个unused，请检查权重")
        return {'FINISHED'}


# ─── 5.3: 阶段3 - 腰キャンセル清空 ──────────────────────────────────────────────────

class OBJECT_OT_assign_weights_phase3(bpy.types.Operator):
    """阶段3：清空腰キャンセル权重（通过约束工作，无需直接权重）"""
    bl_idname = "object.assign_weights_phase3"
    bl_label = "5.3 腰キャンセル清空"

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "请选择骨架对象")
            return {'CANCELLED'}

        mesh_objects = [
            o for o in bpy.data.objects
            if o.type == 'MESH' and any(
                m.type == 'ARMATURE' and m.object == obj
                for m in o.modifiers
            )
        ]
        if not mesh_objects:
            self.report({'ERROR'}, "未找到关联网格")
            return {'CANCELLED'}

        print("[CTMMD 5.3] ===== 阶段3：清空腰キャンセル权重 =====")
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
            print(f"[CTMMD 5.3]   {cancel_name}: 清空 {cleared} 个顶点权重")

        print("[CTMMD 5.3] ===== 阶段3完成 =====")
        self.report({'INFO'}, "阶段3完成：腰キャンセル权重已清空")
        return {'FINISHED'}


# ─── 5.4: 阶段4 - 迷路权重修复 ──────────────────────────────────────────────────

class OBJECT_OT_assign_weights_phase4(bpy.types.Operator):
    """阶段4：修复迷路权重（顶点在空间上远离骨骼但权重挂在其上）"""
    bl_idname = "object.assign_weights_phase4"
    bl_label = "5.4 迷路权重修复"

    STRAY_THRESHOLD: bpy.props.FloatProperty(default=0.25)

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "请选择骨架对象")
            return {'CANCELLED'}

        mesh_objects = [
            o for o in bpy.data.objects
            if o.type == 'MESH' and any(
                m.type == 'ARMATURE' and m.object == obj
                for m in o.modifiers
            )
        ]
        if not mesh_objects:
            self.report({'ERROR'}, "未找到关联网格")
            return {'CANCELLED'}

        print("[CTMMD 5.4] ===== 阶段4：迷路权重修复 =====")

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
                    print(f"[CTMMD 5.4]   {vg.name:<30} → 迷路顶点 {len(stray_verts):>4} 个已转移至最近骨")

            stray_fixed_total += fixed_count

        print(f"[CTMMD 5.4] ===== 阶段4完成：共修复迷路权重 {stray_fixed_total} 顶点 =====")
        self.report({'INFO'}, f"阶段4完成：修复{stray_fixed_total}个迷路权重")
        return {'FINISHED'}


# ─── 5.5: 阶段5 - 下半身清理 ────────────────────────────────────────────────────────

class OBJECT_OT_assign_weights_phase5(bpy.types.Operator):
    """阶段5：从下半身移除已被D骨覆盖的顶点"""
    bl_idname = "object.assign_weights_phase5"
    bl_label = "5.5 下半身清理"

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "请选择骨架对象")
            return {'CANCELLED'}

        mesh_objects = [
            o for o in bpy.data.objects
            if o.type == 'MESH' and any(
                m.type == 'ARMATURE' and m.object == obj
                for m in o.modifiers
            )
        ]
        if not mesh_objects:
            self.report({'ERROR'}, "未找到关联网格")
            return {'CANCELLED'}

        print("[CTMMD 5.5] ===== 阶段5：下半身清理 =====")
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
                print(f"[CTMMD 5.5]   {mesh.name}: 下半身移除 {len(verts_to_remove)} 个D骨覆盖顶点")

        print(f"[CTMMD 5.5] ===== 阶段5完成：共移除 {total_removed} 个顶点 =====")
        self.report({'INFO'}, f"阶段5完成：下半身清理{total_removed}个顶点")
        return {'FINISHED'}
