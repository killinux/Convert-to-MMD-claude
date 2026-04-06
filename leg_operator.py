import bpy
from mathutils import Vector
from .. import bone_utils
from .. import bone_map_and_group

# D楠ㄤ笌涓婚鐨勫搴斿叧绯伙紙涓婚鍚?鈫?D楠ㄥ悕锛夛紝鏀寔 .L/.R 鍜?宸?鍙?涓ょ鏍煎紡
D_BONE_PAIRS = [
    # (涓婚鍚庣紑/鍓嶇紑, D楠ㄥ悕)锛屼晶杈圭敱浠ｇ爜鍔ㄦ€佹嫾鎺?    ("瓒?,   "瓒矰"),
    ("銇层仏", "銇层仏D"),
    ("瓒抽", "瓒抽D"),
]

# D楠ㄩ暱搴︾浉瀵逛簬涓婚闀垮害鐨勬瘮渚嬶紙鏉ヨ嚜鐩爣 PMX 鍙傝€冩ā鍨嬶級
D_BONE_LENGTH_RATIO = {
    "瓒矰":   0.193,
    "銇层仏D": 0.200,
    "瓒抽D": 0.796,
}

SIDES = [
    (".L", "宸?),
    (".R", "鍙?),
]

# 2.5 闃舵2锛氬彧鍏佽褰掑苟杩涙鐧藉悕鍗曪紙涓婂崐韬強浠ヤ笅锛岃烦杩囬/澶?鎵嬭噦锛?# 娉ㄦ剰锛氳叞銈儯銉炽偦銉?涓嶅湪姝ゅ垪琛?鈥斺€?瀹冨彧鐢遍樁娈?浠庤冻D澶嶅埗锛屼笉鎺ユ敹 unused 楠ㄥ綊骞?LOWER_BODY_TARGETS = {
    "涓婂崐韬?, "涓婂崐韬?", "涓婂崐韬?", "涓婂崐韬?", "涓嬪崐韬?,
    "瓒矰.L", "瓒矰.R",
    "銇层仏D.L", "銇层仏D.R",
    "瓒抽D.L", "瓒抽D.R",
    "宸﹁冻鍏圗X", "鍙宠冻鍏圗X",
}

# Phase 2 涓撶敤鍊欓€夐泦锛氭帓闄?D 楠ㄣ€?# D 楠ㄦ潈閲嶅凡鍦?Phase 1 浠庝富楠ㄥ鍒讹紝Phase 2 鐨?unused 杩佺Щ鐩爣鍙簲鏄富楠ㄣ€?# 鑻ヤ繚鐣?D 楠紝瓒矰.R tail(Z鈮?.105) 浼氭妸鑷€閮ㄩ《鐐?Z>1.05)鍚歌蛋锛?# 鍐嶇粡 Phase 5 娓呯悊灏变細璇垹涓嬪崐韬殑鑷€閮ㄦ潈閲嶃€?PHASE2_TARGETS = {
    n for n in LOWER_BODY_TARGETS
    if not n.endswith("D.L") and not n.endswith("D.R")
}

def _point_to_segment_dist(point, seg_head, seg_tail):
    """璁＄畻鐐瑰埌绾挎鐨勬渶杩戣窛绂伙紙绾挎鏈€杩戠偣鏂瑰紡锛?""
    seg = seg_tail - seg_head
    seg_len_sq = seg.length_squared
    if seg_len_sq < 1e-8:
        return (point - seg_head).length
    t = max(0.0, min(1.0, (point - seg_head).dot(seg) / seg_len_sq))
    nearest_pt = seg_head + t * seg
    return (point - nearest_pt).length


def _vertex_centroid(bone_name, mesh_objects):
    """杩斿洖椤剁偣缁勭殑鍔犳潈璐ㄥ績锛坵orld space锛夛紝鏃犳潈閲嶆椂杩斿洖 None"""
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
    """浼樺厛鎵?.L/.R 鏍煎紡锛屽啀鎵?宸?鍙?鍓嶇紑鏍煎紡"""
    name_suffix = base + side_suffix          # 瓒?L
    name_prefix = side_prefix + base          # 宸﹁冻
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


# 鈹€鈹€鈹€ 2.2锛氳ˉ鍏?D楠?鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

class OBJECT_OT_complete_d_bones(bpy.types.Operator):
    """妫€娴嬪苟琛ュ叏 D楠紙瓒矰/銇层仏D/瓒抽D锛夛紝骞朵粠涓婚澶嶅埗鏉冮噸"""
    bl_idname = "object.complete_d_bones"
    bl_label = "Complete D-Bones"

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "璇烽€夋嫨楠ㄦ灦瀵硅薄")
            return {'CANCELLED'}

        mesh_objects = [
            o for o in bpy.data.objects
            if o.type == 'MESH' and any(
                m.type == 'ARMATURE' and m.object == obj
                for m in o.modifiers
            )
        ]

        created = []
        skipped = []

        # 鈹€鈹€ 楠ㄩ鍒涘缓锛圗DIT 妯″紡锛屼笉璧嬫潈閲嶏級鈹€鈹€
        print("[CTMMD 3] ===== 姝ラ3锛氳ˉ鍏―楠?=====")
        bpy.ops.object.mode_set(mode='EDIT')
        edit_bones = obj.data.edit_bones

        for base, d_base in D_BONE_PAIRS:
            for side_suffix, side_prefix in SIDES:
                d_name = d_base + side_suffix
                main_name = _get_main_bone_name(obj, base, side_suffix, side_prefix)

                if edit_bones.get(d_name):
                    skipped.append(d_name + " 宸插瓨鍦?)
                    continue
                if not main_name or not edit_bones.get(main_name):
                    skipped.append(d_name + " 涓婚涓嶅瓨鍦?)
                    continue

                main_eb = edit_bones[main_name]
                cancel_name = "鑵般偔銉ｃ兂銈汇儷" + side_suffix
                parent_name = cancel_name if edit_bones.get(cancel_name) else "涓嬪崐韬?

                parent_d = None
                for pb, pdb in D_BONE_PAIRS:
                    if pdb + side_suffix == d_name:
                        break
                    prev_d = edit_bones.get(pdb + side_suffix)
                    if prev_d:
                        parent_d = prev_d

                actual_parent = parent_d.name if parent_d else parent_name
                main_length = (main_eb.tail - main_eb.head).length
                ratio = D_BONE_LENGTH_RATIO.get(d_base, 0.2)
                d_tail = main_eb.head.copy()
                d_tail.z += main_length * ratio
                bone_utils.create_or_update_bone(
                    edit_bones, d_name,
                    main_eb.head.copy(), d_tail,
                    use_connect=False,
                    parent_name=actual_parent,
                    use_deform=True
                )
                eb = edit_bones[d_name]
                head_str = f"({eb.head.x:.3f},{eb.head.y:.3f},{eb.head.z:.3f})"
                print(f"[CTMMD 3]   鏂板缓: {d_name:<12} head={head_str}  鐖?{actual_parent}  涓婚={main_name}")
                created.append(d_name)

        bpy.ops.object.mode_set(mode='OBJECT')

        print(f"[CTMMD 3] D楠ㄥ垱寤哄畬鎴? {len(created)} 涓柊寤? {len(skipped)} 涓烦杩?)
        for s in skipped:
            print(f"[CTMMD 3]   璺宠繃: {s}")
        self.report({'INFO'}, f"D楠ㄥ垱寤? {len(created)} 涓? 鏉冮噸璇锋墽琛?2.5")
        return {'FINISHED'}


# 鈹€鈹€鈹€ 2.3锛氫慨姝ｄ笅鍗婅韩鏉冮噸 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

class OBJECT_OT_fix_lower_body_weights(bpy.types.Operator):
    """浠庝笅鍗婅韩鏉冮噸涓Щ闄ゅ凡鐢盌楠ㄨ鐩栫殑鑵块儴椤剁偣"""
    bl_idname = "object.fix_lower_body_weights"
    bl_label = "Fix Lower Body Weights"

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "璇烽€夋嫨楠ㄦ灦瀵硅薄")
            return {'CANCELLED'}

        mesh_objects = [
            o for o in bpy.data.objects
            if o.type == 'MESH' and any(
                m.type == 'ARMATURE' and m.object == obj
                for m in o.modifiers
            )
        ]

        d_bone_names = [
            "瓒矰.L", "瓒矰.R",
            "銇层仏D.L", "銇层仏D.R",
            "瓒抽D.L", "瓒抽D.R",
        ]

        total_removed = 0
        total_remaining = 0
        processed_meshes = 0

        for mesh_obj in mesh_objects:
            lower_vg = mesh_obj.vertex_groups.get("涓嬪崐韬?)
            if not lower_vg:
                continue

            # 鏀堕泦 D楠?椤剁偣缁勭殑 index
            d_vg_indices = {
                mesh_obj.vertex_groups[n].index
                for n in d_bone_names
                if mesh_obj.vertex_groups.get(n)
            }
            if not d_vg_indices:
                print(f"[CTMMD 2.3]   {mesh_obj.name}: 鏈壘鍒?D楠?椤剁偣缁勶紝璺宠繃")
                continue

            # 鎵惧嚭闇€瑕佷粠涓嬪崐韬Щ闄ょ殑椤剁偣
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
            print(f"[CTMMD 2.3]   {mesh_obj.name}: 涓嬪崐韬?绉婚櫎 {removed} 涓《鐐癸紝鍓╀綑 {after_count} 涓?)

        if processed_meshes == 0:
            self.report({'WARNING'}, "鏈壘鍒板彲澶勭悊鐨勭綉鏍硷紙涓嬪崐韬《鐐圭粍鎴朌楠ㄤ笉瀛樺湪锛?)
            return {'CANCELLED'}

        print(f"[CTMMD 2.3] 涓嬪崐韬潈閲嶄慨姝ｅ畬鎴愶細鍏辩Щ闄?{total_removed} 涓吙閮ㄩ《鐐癸紝鍓╀綑 {total_remaining} 涓?)
        self.report({'INFO'}, f"涓嬪崐韬潈閲嶄慨姝? 绉婚櫎 {total_removed} 涓吙閮ㄩ《鐐癸紝鍓╀綑 {total_remaining} 涓?)
        return {'FINISHED'}


# 鈹€鈹€鈹€ 2.4锛氳ˉ鍏ㄨ叞銈儯銉炽偦銉楠?鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

class OBJECT_OT_complete_hip_cancel_bones(bpy.types.Operator):
    """琛ュ叏鑵般偔銉ｃ兂銈汇儷楠ㄩ锛堟姷娑堣叞閮ㄦ棆杞殑鎺у埗楠級"""
    bl_idname = "object.complete_hip_cancel_bones"
    bl_label = "Complete Hip Cancel Bones"

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "璇烽€夋嫨楠ㄦ灦瀵硅薄")
            return {'CANCELLED'}

        bpy.ops.object.mode_set(mode='EDIT')
        edit_bones = obj.data.edit_bones

        lower_body = edit_bones.get("涓嬪崐韬?)
        if not lower_body:
            bpy.ops.object.mode_set(mode='OBJECT')
            self.report({'ERROR'}, "涓嬪崐韬楠间笉瀛樺湪锛岃鍏堟墽琛岃ˉ鍏ㄧ己澶遍楠?)
            return {'CANCELLED'}

        print("[CTMMD 4] ===== 姝ラ4锛氳ˉ鍏ㄨ叞銈儯銉炽偦銉?=====")
        log = []
        for side_suffix in [".L", ".R"]:
            cancel_name = "鑵般偔銉ｃ兂銈汇儷" + side_suffix
            if edit_bones.get(cancel_name):
                log.append((cancel_name, "宸插瓨鍦紝璺宠繃"))
                continue

            # 浣嶇疆涓?瓒矰 鐩稿悓锛堝弬鑰冪洰鏍?PMX锛夛紝tail 鍥哄畾鍚戜笂
            fd_bone = edit_bones.get("瓒矰" + side_suffix)
            if fd_bone:
                head = fd_bone.head.copy()
                from mathutils import Vector
                tail = Vector((head.x, head.y, head.z + (fd_bone.tail - fd_bone.head).length))
            else:
                head = lower_body.head.copy()
                tail = lower_body.tail.copy()

            bone_utils.create_or_update_bone(
                edit_bones, cancel_name,
                head, tail,
                use_connect=False,
                parent_name="涓嬪崐韬?,
                use_deform=True
            )
            pos_src = f"瓒矰{side_suffix}" if fd_bone else "涓嬪崐韬?fallback)"
            head_str = f"({head.x:.3f},{head.y:.3f},{head.z:.3f})"
            log.append((cancel_name, f"鏂板缓  head={head_str}  浣嶇疆鏉ユ簮={pos_src}  鐖?涓嬪崐韬?))

        bpy.ops.object.mode_set(mode='OBJECT')

        print(f"[CTMMD 4] 鑵般偔銉ｃ兂銈汇儷琛ュ叏锛?)
        for name, note in log:
            print(f"[CTMMD 4]   {name}  {note}")

        created = sum(1 for _, note in log if note == "鏂板缓")
        self.report({'INFO'}, f"鑵般偔銉ｃ兂銈汇儷: {created} 涓柊寤? {len(log)-created} 涓凡瀛樺湪")
        return {'FINISHED'}


# 鈹€鈹€鈹€ 2.1锛氬悎骞舵湭鏄犲皠鏉冮噸 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

MMD_BONE_NAMES = set(bone_map_and_group.mmd_bone_map.values())

def _guess_side(bone, mesh_objects):
    """鏍规嵁楠ㄩ涓嬮《鐐圭殑骞冲潎 X 鍧愭爣鍒ゆ柇宸﹀彸渚с€傝繑鍥?'L'銆?R' 鎴?None銆?""
    x_vals = []
    for mesh in mesh_objects:
        vg = mesh.vertex_groups.get(bone.name)
        if not vg:
            continue
        for v in mesh.data.vertices:
            for g in v.groups:
                if g.group == vg.index and g.weight > 0:
                    # 杞崲鍒颁笘鐣屽潗鏍囧彇 X
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
    """鍒ゆ柇 MMD 楠ㄩ鍚嶇О鐨勪晶杈广€傝繑鍥?'L'銆?R' 鎴?None銆?""
    if bone_name.startswith("宸?) or bone_name.endswith(".L"):
        return 'L'
    if bone_name.startswith("鍙?) or bone_name.endswith(".R"):
        return 'R'
    return None


def _merge_weights_additive(mesh_obj, src_name, dst_name):
    """灏?src_name 椤剁偣缁勬潈閲嶅姞娉曞悎骞跺埌 dst_name锛堜笂闄?1.0锛夛紝杩斿洖鍙楀奖鍝嶉《鐐规暟銆?""
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
        # 璇诲彇鐩爣鐜版湁鏉冮噸
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
    灏?src_name 鏉冮噸鎸夐《鐐瑰湪 seg_from_ws鈫抯eg_to_ws 绾挎涓婄殑鎶曞奖鍙傛暟 t 姊害鍒嗛厤锛?      dst_elbow锛堛伈銇橈級 鑾峰緱 w * t      锛坱=0 鍦?from 绔紝t=1 鍦?to 绔紝闈?to/銇层仒 渚ц秺澶氾級
      dst_twist锛堣厱鎹╋級 鑾峰緱 w * (1-t)  锛堥潬 from/鑵?渚ц秺澶氾級
    涓よ€呮潈閲嶅彔鍔犲埌鍘熸湁鏉冮噸涓婏紙涓婇檺1.0锛夈€?    杩斿洖 (鎬婚《鐐规暟, elbow椤剁偣鏁? twist椤剁偣鏁?銆?    """
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

        # 鎶曞奖鍙傛暟 t锛?=鑵曚晶锛?=銇层仒渚?        vw = mesh_obj.matrix_world @ v.co
        if seg_len_sq < 1e-8:
            t = 0.5
        else:
            t = max(0.0, min(1.0, (vw - seg_from_ws).dot(seg) / seg_len_sq))

        w_elbow = src_w * t
        w_twist = src_w * (1.0 - t)

        # 鍔犲埌鐜版湁鏉冮噸锛堜笂闄?.0锛?        if w_elbow > 0.001:
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
    """妫€娴嬪苟鍚堝苟鏈槧灏勮緟鍔╅鐨勯《鐐规潈閲嶅埌鏈€杩戠殑 MMD 楠ㄩ"""
    bl_idname = "object.merge_unmapped_weights"
    bl_label = "Merge Unmapped Weights"

    DISTANCE_THRESHOLD: bpy.props.FloatProperty(default=0.15)

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "璇烽€夋嫨楠ㄦ灦瀵硅薄")
            return {'CANCELLED'}

        mesh_objects = [
            o for o in bpy.data.objects
            if o.type == 'MESH' and any(
                m.type == 'ARMATURE' and m.object == obj
                for m in o.modifiers
            )
        ]

        # 鏀堕泦鏈槧灏勯楠硷紙鍚嶇О浠?"unused " 寮€澶淬€乽se_deform=True 涓旀湁瀹為檯鏉冮噸锛?        unmapped_bones = [
            bone for bone in obj.data.bones
            if bone.use_deform
            and bone.name.startswith("unused ")
            and any(_vg_has_weight(m, bone.name) for m in mesh_objects)
        ]
        unmapped_names = {b.name for b in unmapped_bones}
        # 鎵€鏈?unused 楠ㄩ鍚嶏紙鍚棤鏉冮噸鐨勶級锛岄伩鍏嶈閫変负鍚堝苟鐩爣
        all_unused_names = {b.name for b in obj.data.bones if b.name.startswith("unused ")}

        print(f"[CTMMD 2.1] ===== 鏈槧灏勬潈閲嶆鏌ユ姤鍛?=====")
        print(f"[CTMMD 2.1] 鍙戠幇 {len(unmapped_bones)} 涓湭鏄犲皠楠ㄩ锛?)

        merged_count = 0
        skipped_count = 0

        for bone in unmapped_bones:
            # 鏀堕泦褰撳墠鏈夊疄闄呮潈閲嶇殑楠ㄩ鍚嶏紙閬垮厤鍚堝苟鍒扮┖楠ㄩ濡?鍙宠冻锛?            bones_with_weight = {
                mesh.vertex_groups[g.group].name
                for mesh in mesh_objects
                for v in mesh.data.vertices
                for g in v.groups
                if g.weight > 0 and g.group < len(mesh.vertex_groups)
            }

            # 鎵炬渶杩戠殑 MMD deform 楠ㄩ
            # 璇勫垎 = head-to-head + 0.1 * head-to-center锛坔ead鐩稿悓鏃剁敤center鏂瑰悜鍋歵iebreaker锛?            nearest = None
            nearest_score = float('inf')
            for candidate in obj.data.bones:
                if candidate.name in all_unused_names:
                    continue
                if not candidate.use_deform:
                    continue
                if candidate.name not in bones_with_weight:
                    continue
                head_dist = (bone.head_local - candidate.head_local).length
                c_center = (candidate.head_local + candidate.tail_local) / 2
                head_to_center = (bone.head_local - c_center).length
                score = head_dist + 0.1 * head_to_center
                if score < nearest_score:
                    nearest_score = score
                    nearest = candidate
            nearest_dist = (bone.head_local - nearest.head_local).length if nearest else float('inf')

            if not nearest:
                print(f"[CTMMD 2.1] 鈿?{bone.name:<30} 鈫?鏃犲€欓€夐楠硷紝璺宠繃")
                skipped_count += 1
                continue

            dist = nearest_dist

            # 缁熻璇ラ楠肩殑鎬绘潈閲嶉《鐐规暟
            total_verts = sum(
                sum(1 for v in m.data.vertices
                    for g in v.groups
                    if m.vertex_groups.get(bone.name)
                    and g.group == m.vertex_groups[bone.name].index
                    and g.weight > 0)
                for m in mesh_objects
            )

            if dist >= self.DISTANCE_THRESHOLD:
                print(f"[CTMMD 2.1] 鈿?{bone.name:<30} 鈫?{nearest.name:<10} (璺漿dist:.2f}m, {total_verts}椤剁偣)  瓒呭嚭闃堝€? 璺宠繃鈥旇浜哄伐澶勭悊")
                skipped_count += 1
                continue

            # 渚ц竟鏍￠獙锛氳嫢涓よ€呬晶杈规槑纭笖鐩稿弽锛屽皾璇曟壘鍚屼晶鍊欓€?            src_side = _guess_side(bone, mesh_objects)
            dst_side = _side_of_mmd_bone(nearest.name)
            if src_side and dst_side and src_side != dst_side:
                # 鍦ㄥ悓渚т腑閲嶆柊鎵炬渶杩戯紙head-to-head锛屼笖鏈夋潈閲嶏級
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
                    sd = f"{same_side_dist:.2f}m" if same_side_nearest else "鏃犲€欓€?
                    print(f"[CTMMD 2.1] 鈿?{bone.name:<30} 鈫?渚ц竟涓嶅尮閰嶄笖鍚屼晶鍊欓€夎秴闃堝€?{sd}), 璺宠繃鈥旇浜哄伐澶勭悊")
                    skipped_count += 1
                    continue

            # 鎵ц鍔犳硶鍚堝苟
            mesh_count = 0
            vert_count = 0
            for mesh in mesh_objects:
                n = _merge_weights_additive(mesh, bone.name, nearest.name)
                if n > 0:
                    vert_count += n
                    mesh_count += 1
                    # 娓呴櫎婧愰楠兼潈閲?                    src_vg = mesh.vertex_groups.get(bone.name)
                    if src_vg:
                        merged_verts = [v.index for v in mesh.data.vertices
                                        for g in v.groups
                                        if g.group == src_vg.index and g.weight > 0]
                        if merged_verts:
                            src_vg.remove(merged_verts)

            # 绂佺敤鏈槧灏勯楠?            obj.data.bones[bone.name].use_deform = False

            print(f"[CTMMD 2.1] 鉁?{bone.name:<30} 鈫?{nearest.name:<10} (璺漿dist:.2f}m, {vert_count}椤剁偣) 鑷姩鍚堝苟 [宸茬鐢╙")
            merged_count += 1

        print(f"[CTMMD 2.1] ===== 鎶ュ憡缁撴潫 =====")
        print(f"[CTMMD 2.1] 鍚堝苟: {merged_count} 涓垚鍔? 璺宠繃: {skipped_count} 涓紙璇﹁涓婃柟锛?)

        self.report({'INFO'}, f"鏈槧灏勬潈閲嶅悎骞? {merged_count} 涓垚鍔? {skipped_count} 涓烦杩?)
        return {'FINISHED'}


# 鈹€鈹€鈹€ 2.5锛氱粺涓€鏉冮噸鍒嗛厤 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

class OBJECT_OT_assign_weights(bpy.types.Operator):
    """缁熶竴鍒嗛厤鏉冮噸锛欴楠ㄢ啇涓婚 鈫?unused楠ㄥ苟鍏楠?鈫?鏂板缓楠ㄩ璧嬪€?鈫?涓嬪崐韬竻鐞?""
    bl_idname = "object.assign_weights"
    bl_label = "Assign Weights"

    DISTANCE_THRESHOLD: bpy.props.FloatProperty(default=0.15)

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "璇烽€夋嫨楠ㄦ灦瀵硅薄")
            return {'CANCELLED'}

        mesh_objects = [
            o for o in bpy.data.objects
            if o.type == 'MESH' and any(
                m.type == 'ARMATURE' and m.object == obj
                for m in o.modifiers
            )
        ]
        if not mesh_objects:
            self.report({'ERROR'}, "鏈壘鍒板叧鑱旂綉鏍?)
            return {'CANCELLED'}

        # 鈹€鈹€ 闃舵1锛欴楠?鈫?涓婚锛屾竻闆朵富楠?鈹€鈹€
        print("[CTMMD 5] ===== 姝ラ5锛氬垎閰嶆潈閲?=====")
        print("[CTMMD 5] 鈹€鈹€ 闃舵1锛欴楠?鈫?涓婚 鈹€鈹€")
        cleared_bones = set()  # 璁板綍宸叉竻闆剁殑涓婚锛屼緵闃舵2鎺掗櫎
        for base, d_base in D_BONE_PAIRS:
            for side_suffix, side_prefix in SIDES:
                d_name = d_base + side_suffix
                main_name = _get_main_bone_name(obj, base, side_suffix, side_prefix)
                if not main_name:
                    print(f"[CTMMD 5]   {d_name}: 涓婚涓嶅瓨鍦紝璺宠繃")
                    continue
                total = 0
                for mesh in mesh_objects:
                    n = bone_utils.copy_vertex_group_weights(mesh, main_name, d_name)
                    total += n
                # 娓呴浂涓婚锛堝凡杞Щ鍒癉楠ㄧ殑椤剁偣锛?                for mesh in mesh_objects:
                    main_vg = mesh.vertex_groups.get(main_name)
                    d_vg = mesh.vertex_groups.get(d_name)
                    if not main_vg or not d_vg:
                        continue
                    d_verts = [v.index for v in mesh.data.vertices
                               for g in v.groups if g.group == d_vg.index and g.weight > 0]
                    if d_verts:
                        main_vg.remove(d_verts)
                cleared_bones.add(main_name)
                print(f"[CTMMD 5]   {d_name} 鈫?{main_name}  {total} 椤剁偣锛屼富楠ㄥ凡娓呴浂")

        # 鈹€鈹€ 闃舵2锛歶nused楠?鈫?鏈€杩戠洰鏍囬锛堥€愰《鐐瑰垎閰嶏級鈹€鈹€
        # 鏀逛负閫愰《鐐规煡鎵炬渶杩戠洰鏍囬锛岄伩鍏嶈法鍖哄煙楠ㄩ锛堝 xtra08opp 鍚屾椂鎺у埗鑷€閮?澶ц吙锛?        # 灏嗘墍鏈夐《鐐归敊璇湴鍒嗛厤鍒板崟涓€鐩爣楠紝閫犳垚鍚庣画涓嬪崐韬竻鐞嗚鍒犺噣閮ㄦ潈閲嶃€?        print("[CTMMD 5] ===== 闃舵2锛歶nused楠?鈫?鐩爣楠紙閫愰《鐐癸級=====")
        all_unused_names = {b.name for b in obj.data.bones if b.name.startswith("unused ")}
        unused_bones = [
            b for b in obj.data.bones
            if b.name.startswith("unused ") and b.use_deform
            and any(_vg_has_weight(m, b.name) for m in mesh_objects)
        ]

        # 棰勮绠楃櫧鍚嶅崟鐩爣楠ㄤ笘鐣屽潗鏍囷紙head/tail锛夛紝渚涢€愰《鐐规煡鎵剧敤
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

        for bone in unused_bones:
            # 鍏堢敤璐ㄥ績鍋氭暣楠ㄧ矖鍒わ細璺濈瓒呴槇鍊煎垯鏁撮璺宠繃
            src_pos = _vertex_centroid(bone.name, mesh_objects) or (obj.matrix_world @ bone.head_local)
            best_name, best_dist = None, float('inf')
            for cname, ch, ct in target_candidates:
                d = _point_to_segment_dist(src_pos, ch, ct)
                if d < best_dist:
                    best_dist = d; best_name = cname
            if not best_name:
                print(f"[CTMMD 5] 鈿?{bone.name:<30} 鏃犲€欓€夛紝璺宠繃")
                skipped_count += 1
                continue
            if best_dist >= self.DISTANCE_THRESHOLD:
                print(f"[CTMMD 5] 鈿?{bone.name:<30} 鈫?{best_name:<12} 璐ㄥ績璺漿best_dist:.3f}m 瓒呴槇鍊硷紝璺宠繃")
                skipped_count += 1
                continue

            # 鎺ㄦ柇婧愰渚ц竟锛堢敤浜庤繃婊ゅ€欓€夛級
            src_side = _guess_side(bone, mesh_objects)

            # 閫愰《鐐癸細瀵规瘡涓《鐐规壘鏈€杩戠洰鏍囬锛堣€冭檻渚ц竟锛夛紝鍔犳硶鍚堝苟鏉冮噸锛屾竻闆舵簮楠?            dst_counts = {}   # {dst_name: vert_count}
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

                    # 绛涢€夊悓渚у€欓€夛紙濡傛灉渚ц竟鍙垽鏂級
                    filtered = target_candidates
                    if src_side:
                        same_side = [(n, h, t) for n, h, t in target_candidates
                                     if _side_of_mmd_bone(n) == src_side or _side_of_mmd_bone(n) is None]
                        if same_side:
                            filtered = same_side

                    # 鎵剧璇ラ《鐐规渶杩戠殑鐩爣楠?                    v_best_name, v_best_dist = None, float('inf')
                    for cname, ch, ct in filtered:
                        d = _point_to_segment_dist(vw, ch, ct)
                        if d < v_best_dist:
                            v_best_dist = d; v_best_name = cname

                    if not v_best_name or v_best_dist >= self.DISTANCE_THRESHOLD:
                        continue

                    # 鍔犳硶鍚堝苟鍒扮洰鏍囬
                    dst_vg = mesh.vertex_groups.get(v_best_name) or mesh.vertex_groups.new(name=v_best_name)
                    cur_dst = next((g.weight for g in v.groups if g.group == dst_vg.index), 0.0)
                    dst_vg.add([v.index], min(cur_dst + src_w, 1.0), 'REPLACE')
                    verts_to_clear.append(v.index)
                    dst_counts[v_best_name] = dst_counts.get(v_best_name, 0) + 1

                if verts_to_clear:
                    src_vg.remove(verts_to_clear)

            obj.data.bones[bone.name].use_deform = False
            total_verts = sum(dst_counts.values())
            dist_str = f"璐ㄥ績璺漿best_dist:.3f}m"
            dst_str = "  ".join(f"{n}({c}v)" for n, c in sorted(dst_counts.items(), key=lambda x: -x[1]))
            print(f"[CTMMD 5] 鉁?{bone.name:<30} 鈫?{dst_str}  [{dist_str}  鍏眥total_verts}椤剁偣] [宸茬鐢╙")
            merged_count += 1

        print(f"[CTMMD 5] 闃舵2: 鍚堝苟{merged_count}涓? 璺宠繃{skipped_count}涓?)

        # 鈹€鈹€ 闃舵3锛氭楠?鏂板缓楠ㄩ璧嬫潈閲?鈹€鈹€
        print("[CTMMD 5] ===== 闃舵3锛氭竻绌鸿叞銈儯銉炽偦銉潈閲?=====")
        # 鑵般偔銉ｃ兂銈汇儷 閫氳繃楠ㄩ灞傜骇+grant rotation绾︽潫宸ヤ綔锛岄《鐐规潈閲嶅簲涓?0
        # 锛堢洰鏍嘝MX涓叞銈儯銉炽偦銉?R/L 鍧囦负 0 verts锛?        for side_suffix in [".L", ".R"]:
            cancel_name = "鑵般偔銉ｃ兂銈汇儷" + side_suffix
            cleared = 0
            for mesh in mesh_objects:
                cancel_vg = mesh.vertex_groups.get(cancel_name)
                if cancel_vg:
                    all_verts = [v.index for v in mesh.data.vertices
                                 for g in v.groups if g.group == cancel_vg.index and g.weight > 0]
                    if all_verts:
                        cancel_vg.remove(all_verts)
                        cleared += len(all_verts)
            print(f"[CTMMD 5]   {cancel_name}: 娓呯┖ {cleared} 涓《鐐规潈閲嶏紙閫氳繃绾︽潫宸ヤ綔锛屾棤闇€鐩存帴鏉冮噸锛?)

        # 鈹€鈹€ 闃舵4锛氳糠璺潈閲嶄慨澶?鈹€鈹€
        # 鍘熷 XPS 涓儴鍒嗛楠硷紙濡傛墜鎸囬锛夊瓨鍦?杩疯矾鏉冮噸"锛?        # 椤剁偣鍦ㄧ┖闂翠笂杩滅璇ラ楠硷紝浣嗘潈閲嶅嵈鎸傚湪鍏朵笂锛圶PS 瀵煎嚭/缁戝畾閿欒锛夈€?        # 渚嬶細arm right finger 5c 鎺у埗浜嗗ぇ鑵垮尯鍩熸暟鐧鹃《鐐广€?        # 淇绛栫暐锛氶亶鍘嗘墍鏈?MMD 鍙樺舰楠紱鑻ラ《鐐瑰埌楠ㄩ娈佃窛绂?> STRAY_THRESHOLD锛?        # 鍒欏皢璇ラ《鐐规潈閲嶈浆绉诲埌璺濈鏈€杩戠殑 LOWER_BODY_TARGETS 楠ㄩ锛屽苟娓呴浂鍘熼楠兼潈閲嶃€?        print("[CTMMD 5] ===== 闃舵4锛氳糠璺潈閲嶄慨澶?=====")
        STRAY_THRESHOLD = 0.25   # 瓒呰繃姝よ窛绂伙紙m锛夎涓鸿糠璺潈閲?        stray_fixed_total = 0

        # 鏀堕泦鐧藉悕鍗曠洰鏍囬楠煎強鍏剁嚎娈典笘鐣屽潗鏍囷紙渚涙渶杩戣窛绂绘煡鎵撅級
        target_bones_ws = []
        for candidate in obj.data.bones:
            if candidate.name in LOWER_BODY_TARGETS and candidate.use_deform:
                h = obj.matrix_world @ candidate.head_local
                t = obj.matrix_world @ candidate.tail_local
                target_bones_ws.append((candidate.name, h, t))

        for mesh in mesh_objects:
            fixed_count = 0
            vg_names_local = {vg.index: vg.name for vg in mesh.vertex_groups}
            # 鍙鐞?MMD 鍙樺舰楠紙鎺掗櫎 unused / 鎺у埗楠級
            mmd_deform_vgs = [
                vg for vg in mesh.vertex_groups
                if not vg.name.startswith("unused ")
                and obj.data.bones.get(vg.name)
                and obj.data.bones[vg.name].use_deform
                and vg.name not in LOWER_BODY_TARGETS
                # 璺宠繃鑵胯剼楠ㄨ嚜韬紙瀹冧滑涓嶄細杩疯矾锛?                and not any(k in vg.name for k in ["瓒?, "銇层仏", "鑵?, "D."])
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
                    if dist > STRAY_THRESHOLD:
                        stray_verts.append((v, src_w, vw))

                if not stray_verts:
                    continue

                # 瀵规瘡涓糠璺《鐐癸細鎵炬渶杩戠洰鏍囬锛岃浆绉绘潈閲?                for v, src_w, vw in stray_verts:
                    best_name, best_dist = None, float('inf')
                    for tname, th, tt in target_bones_ws:
                        d = _point_to_segment_dist(vw, th, tt)
                        if d < best_dist:
                            best_dist = d
                            best_name = tname
                    if not best_name:
                        continue
                    # 杞Щ锛氬姞鍒扮洰鏍囬锛堜笂闄?.0锛夛紝娓呴浂婧愰
                    dst_vg = mesh.vertex_groups.get(best_name) or mesh.vertex_groups.new(name=best_name)
                    cur_dst = next((g.weight for g in v.groups if g.group == dst_vg.index), 0.0)
                    dst_vg.add([v.index], min(cur_dst + src_w, 1.0), 'REPLACE')
                    vg.add([v.index], 0.0, 'REPLACE')
                    fixed_count += 1

                if stray_verts:
                    print(f"[CTMMD 5]   {vg.name:<30} 鈫?杩疯矾椤剁偣 {len(stray_verts):>4} 涓凡杞Щ鑷虫渶杩慏楠?)

            stray_fixed_total += fixed_count

        print(f"[CTMMD 5] 闃舵4 瀹屾垚: 鍏变慨澶嶈糠璺潈閲?{stray_fixed_total} 椤剁偣")

        # 鈹€鈹€ 闃舵5锛氫粠涓嬪崐韬Щ闄ゅ凡琚獶楠ㄨ鐩栫殑椤剁偣 鈹€鈹€
        print("[CTMMD 5] ===== 闃舵5锛氫笅鍗婅韩娓呯悊 =====")
        d_bone_names = [d_base + s for _, d_base in D_BONE_PAIRS for s, _ in SIDES]
        total_removed = 0
        for mesh in mesh_objects:
            lower_vg = mesh.vertex_groups.get("涓嬪崐韬?)
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
                print(f"[CTMMD 5]   {mesh.name}: 涓嬪崐韬Щ闄?{len(verts_to_remove)} 涓狣楠ㄨ鐩栭《鐐?)

        print(f"[CTMMD 5] ===== 鏉冮噸鍒嗛厤瀹屾垚 =====")
        self.report({'INFO'}, f"鏉冮噸鍒嗛厤瀹屾垚锛欴楠ㄨ祴鍊笺€亄merged_count}涓猽nused鍚堝苟銆佽糠璺慨澶峽stray_fixed_total}椤剁偣銆佷笅鍗婅韩娓呯悊{total_removed}椤剁偣")
        return {'FINISHED'}


# 鈹€鈹€鈹€ 2.1锛氳ˉ鍏ㄦ壄杞锛堣厱鎹?/ 鎵嬫崺锛夆攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

# XPS foretwist 鈫?MMD 鎹╅ 鏄犲皠琛?# (xps楠ㄥ悕妯℃澘, 鎹╅鍩哄悕, parent楠ㄥ熀鍚? 浣嶇疆璧风偣楠ㄥ熀鍚? 浣嶇疆缁堢偣楠ㄥ熀鍚? 姣斾緥)
TWIST_PAIRS = [
    ("unused bip001 {prefix}foretwist",  "鑵曟崺", "鑵?, "鑵?,  "銇层仒", 0.6),
    ("unused bip001 {prefix}foretwist1", "鎵嬫崺", "銇层仒", "銇层仒", "鎵嬮", 0.6),
]

# 鎹╅闀垮害锛堝弬鑰冪洰鏍嘝MX锛岀害0.082m锛?TWIST_BONE_LENGTH = 0.082


def _detect_side_format(armature):
    """妫€娴嬮鏋朵娇鐢ㄥ摢绉嶄晶杈瑰懡鍚嶆牸寮忥紝杩斿洖 'prefix'锛堝乏/鍙筹級鎴?'suffix'锛?L/.R锛?""
    bones = armature.data.bones
    if bones.get("宸﹁厱") or bones.get("宸︺伈銇?):
        return "prefix"
    return "suffix"


def _twist_bone_name(base, side_fmt, side):
    """鐢熸垚鎹╅鍚嶇О锛宻ide='L' or 'R'"""
    if side_fmt == "prefix":
        return ("宸? if side == "L" else "鍙?) + base   # 渚嬶細宸﹁厱鎹?    return base + "." + side                             # 渚嬶細鑵曟崺.L


def _arm_bone_name(base, side_fmt, side):
    """鐢熸垚鎵嬭噦楠ㄩ鍚嶇О"""
    if side_fmt == "prefix":
        return ("宸? if side == "L" else "鍙?) + base   # 渚嬶細宸﹁厱
    return base + "." + side                             # 渚嬶細鑵?L


def _xps_foretwist_name(template, side):
    """鐢熸垚 XPS foretwist 楠ㄩ鍚?""
    return template.format(prefix="l " if side == "L" else "r ")


def _clear_and_disable(armature_obj, mesh_objects, bone_name):
    """娓呴櫎鎵€鏈夌綉鏍间腑鎸囧畾椤剁偣缁勭殑鏉冮噸锛屽苟绂佺敤瀵瑰簲楠ㄩ鐨勫彉褰?""
    for mesh in mesh_objects:
        src_vg = mesh.vertex_groups.get(bone_name)
        if src_vg:
            rm = [v.index for v in mesh.data.vertices
                  for g in v.groups if g.group == src_vg.index and g.weight > 0]
            if rm:
                src_vg.remove(rm)
    if bone_name in armature_obj.data.bones:
        armature_obj.data.bones[bone_name].use_deform = False


class OBJECT_OT_complete_twist_bones(bpy.types.Operator):
    """琛ュ叏鎵浆楠紙鑵曟崺/鎵嬫崺锛夛紝骞朵粠XPS foretwist杩佺Щ鏉冮噸"""
    bl_idname = "object.complete_twist_bones"
    bl_label = "Complete Twist Bones"

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "璇烽€夋嫨楠ㄦ灦瀵硅薄")
            return {'CANCELLED'}

        mesh_objects = [
            o for o in bpy.data.objects
            if o.type == 'MESH' and any(
                m.type == 'ARMATURE' and m.object == obj
                for m in o.modifiers
            )
        ]

        print("[CTMMD 2.1] ===== 姝ラ2.1锛氳ˉ鍏ㄦ壄杞 =====")
        side_fmt = _detect_side_format(obj)
        print(f"[CTMMD 2.1]   鍛藉悕鏍煎紡: {'鍓嶇紑锛堝乏/鍙筹級' if side_fmt=='prefix' else '鍚庣紑锛?L/.R锛?}")

        # 鈹€鈹€ EDIT妯″紡锛氬垱寤洪楠?鈹€鈹€
        bpy.ops.object.mode_set(mode='EDIT')
        edit_bones = obj.data.edit_bones

        created = []
        skipped = []

        for xps_template, twist_base, parent_base, from_base, to_base, ratio in TWIST_PAIRS:
            for side in ["L", "R"]:
                twist_name  = _twist_bone_name(twist_base,  side_fmt, side)
                parent_name = _arm_bone_name(parent_base, side_fmt, side)
                from_name   = _arm_bone_name(from_base,   side_fmt, side)
                to_name     = _arm_bone_name(to_base,     side_fmt, side)

                from_bone = edit_bones.get(from_name)
                to_bone   = edit_bones.get(to_name)
                if not from_bone or not to_bone:
                    skipped.append(f"{twist_name}锛堜富楠?{from_name}/{to_name} 涓嶅瓨鍦級")
                    continue

                if edit_bones.get(twist_name):
                    skipped.append(f"{twist_name} 宸插瓨鍦?)
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
                print(f"[CTMMD 2.1]   鏂板缓: {twist_name:<10} head=({head.x:.3f},{head.y:.3f},{head.z:.3f})  鐖?{parent_name}")
                created.append(twist_name)

        bpy.ops.object.mode_set(mode='OBJECT')

        # 鈹€鈹€ OBJECT妯″紡锛氭潈閲嶈縼绉?鈹€鈹€
        print("[CTMMD 2.1] 鈹€鈹€ 鏉冮噸杩佺Щ 鈹€鈹€")
        for xps_template, twist_base, parent_base, from_base, to_base, ratio in TWIST_PAIRS:
            for side in ["L", "R"]:
                twist_name  = _twist_bone_name(twist_base,  side_fmt, side)
                xps_name    = _xps_foretwist_name(xps_template, side)
                elbow_name  = _arm_bone_name("銇层仒", side_fmt, side)   # 宸︺伈銇?/ 鍙炽伈銇?
                if not any(_vg_has_weight(m, xps_name) for m in mesh_objects):
                    print(f"[CTMMD 2.1]   璺宠繃: {xps_name} 鏃犳潈閲嶉《鐐?)
                    continue

                is_foretwist = (twist_base == "鑵曟崺")   # foretwist 鈫?姊害鍒嗛厤锛沠oretwist1 鈫?鍏ㄧ粰鎵嬫崺

                if is_foretwist:
                    # foretwist锛氭搴︽媶鍒嗗埌 銇层仒锛堥潬銇层仒渚э級+ 鑵曟崺锛堥潬鑵曚晶锛?                    from_name = _arm_bone_name(from_base, side_fmt, side)  # 宸﹁厱 / 鍙宠厱
                    to_name   = _arm_bone_name(to_base,   side_fmt, side)  # 宸︺伈銇?/ 鍙炽伈銇?                    from_pb   = obj.pose.bones.get(from_name)
                    to_pb     = obj.pose.bones.get(to_name)
                    if not from_pb or not to_pb:
                        print(f"[CTMMD 2.1]   鈿?姊害鍒嗛厤澶辫触锛堜富楠ㄤ笉瀛樺湪锛夛紝鏀逛负鍏ㄧ粰 {twist_name}")
                        # 閫€鍥炵畝鍗曡縼绉?                        total = 0
                        for mesh in mesh_objects:
                            total += _merge_weights_additive(mesh, xps_name, twist_name)
                        _clear_and_disable(obj, mesh_objects, xps_name)
                        print(f"[CTMMD 2.1]   {xps_name:<42} 鈫?{twist_name:<10}  {total} 椤剁偣 [宸茬鐢╙")
                        continue

                    seg_from_ws = obj.matrix_world @ from_pb.head
                    seg_to_ws   = obj.matrix_world @ to_pb.head

                    total_e = total_t = 0
                    for mesh in mesh_objects:
                        n, ne, nt = _split_weights_gradient(
                            mesh, xps_name, elbow_name, twist_name,
                            seg_from_ws, seg_to_ws
                        )
                        total_e += ne
                        total_t += nt

                    _clear_and_disable(obj, mesh_objects, xps_name)
                    print(f"[CTMMD 2.1]   {xps_name:<42} 鈫?{elbow_name}({total_e}v) + {twist_name}({total_t}v) [姊害] [宸茬鐢╙")

                else:
                    # foretwist1锛氬叏閮ㄨ縼绉诲埌 鎵嬫崺
                    total = 0
                    for mesh in mesh_objects:
                        total += _merge_weights_additive(mesh, xps_name, twist_name)
                    _clear_and_disable(obj, mesh_objects, xps_name)
                    print(f"[CTMMD 2.1]   {xps_name:<42} 鈫?{twist_name:<10}  {total} 椤剁偣 [宸茬鐢╙")

        print(f"[CTMMD 2.1] 瀹屾垚: 鏂板缓 {len(created)} 涓紝璺宠繃 {len(skipped)} 涓?)
        for s in skipped:
            print(f"[CTMMD 2.1]   璺宠繃: {s}")
        self.report({'INFO'}, f"鎵浆楠ㄨˉ鍏? 鏂板缓 {len(created)} 涓?)
        return {'FINISHED'}


# 鈹€鈹€鈹€ 2.6锛氫笂鍗婅韩3鏉冮噸鍒嗛厤 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

# 鐩爣 PMX 鍒嗘瀽寰楀嚭鐨勫弬鏁帮紙鍗曚綅锛欱lender units = PMX鍧愭爣 梅 12.2锛?UPPER3_HEAD_Z    = 1.3118   # 涓婂崐韬? 楠ㄩ head Z锛堢‖鍒囧壊闃堝€硷級
UPPER3_BLEND_START_Z = 1.2725   # 鐩爣PMX涓笂鍗婅韩3鏉冮噸寮€濮嬪嚭鐜扮殑Z锛堟笎鍙樿捣鐐癸級
UPPER3_SOURCE_BONES = ["涓婂崐韬?, "涓婂崐韬?", "涓婂崐韬?"]
UPPER3_TARGET_BONE  = "涓婂崐韬?"


class OBJECT_OT_assign_upper3_weights(bpy.types.Operator):
    """灏嗕笂鍗婅韩/涓婂崐韬?/涓婂崐韬?楂榋鍖哄煙鐨勬潈閲嶉噸鏂板垎閰嶇粰涓婂崐韬?"""
    bl_idname = "object.assign_upper3_weights"
    bl_label = "Assign Upper3 Weights"

    mode: bpy.props.EnumProperty(
        name="妯″紡",
        items=[
            ('HARD_CUT',     '纭垏鍓?,   'Z > 1.3118 鐨勯《鐐规潈閲嶅叏閮ㄧЩ鍏ヤ笂鍗婅韩3'),
            ('PROPORTIONAL', '娓愬彉杩囨浮', '鍦ㄨ繃娓″尯 Z=[1.2725,1.3118] 鍐呯嚎鎬ф贩鍚?),
        ],
        default='HARD_CUT'
    )

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "璇烽€夋嫨楠ㄦ灦瀵硅薄")
            return {'CANCELLED'}

        mesh_objects = [
            o for o in bpy.data.objects
            if o.type == 'MESH' and any(
                m.type == 'ARMATURE' and m.object == obj
                for m in o.modifiers
            )
        ]
        if not mesh_objects:
            self.report({'ERROR'}, "鏈壘鍒板叧鑱旂綉鏍?)
            return {'CANCELLED'}

        mode_label = "纭垏鍓? if self.mode == 'HARD_CUT' else "娓愬彉杩囨浮"
        print(f"[CTMMD 2.6] ===== 涓婂崐韬?鏉冮噸鍒嗛厤锛坽mode_label}锛?====")
        print(f"[CTMMD 2.6]   鏉ユ簮楠ㄩ: {UPPER3_SOURCE_BONES}")
        print(f"[CTMMD 2.6]   鐩爣楠ㄩ: {UPPER3_TARGET_BONE}")
        if self.mode == 'HARD_CUT':
            print(f"[CTMMD 2.6]   鍒囧壊鐐? : Z > {UPPER3_HEAD_Z}")
        else:
            print(f"[CTMMD 2.6]   杩囨浮鍖? : Z=[{UPPER3_BLEND_START_Z}, {UPPER3_HEAD_Z}]锛屼箣涓?00%褰掍笂鍗婅韩3")

        total_transferred = 0
        total_vertices = 0

        for mesh in mesh_objects:
            # 纭繚鐩爣椤剁偣缁勫瓨鍦?            dst_vg = mesh.vertex_groups.get(UPPER3_TARGET_BONE) \
                     or mesh.vertex_groups.new(name=UPPER3_TARGET_BONE)

            mesh_transferred = 0
            mesh_vertices = 0

            for src_name in UPPER3_SOURCE_BONES:
                src_vg = mesh.vertex_groups.get(src_name)
                if not src_vg:
                    continue

                for v in mesh.data.vertices:
                    # 鑾峰彇璇ラ《鐐瑰湪婧愰楠肩殑鏉冮噸
                    src_w = 0.0
                    for g in v.groups:
                        if g.group == src_vg.index:
                            src_w = g.weight
                            break
                    if src_w <= 0:
                        continue

                    co = mesh.matrix_world @ v.co
                    z = co.z

                    # 璁＄畻杞Щ姣斾緥
                    if self.mode == 'HARD_CUT':
                        if z <= UPPER3_HEAD_Z:
                            continue
                        ratio = 1.0
                    else:
                        if z <= UPPER3_BLEND_START_Z:
                            continue
                        elif z >= UPPER3_HEAD_Z:
                            ratio = 1.0
                        else:
                            ratio = (z - UPPER3_BLEND_START_Z) / (UPPER3_HEAD_Z - UPPER3_BLEND_START_Z)

                    transfer_w = src_w * ratio
                    remain_w   = src_w * (1.0 - ratio)

                    # 璇诲彇鐩爣鐜版湁鏉冮噸锛堝姞娉曪紝涓婇檺1.0锛?                    dst_w = 0.0
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
                print(f"[CTMMD 2.6]   {mesh.name}: {mesh_vertices} 椤剁偣澶勭悊锛屾潈閲嶈浆绉?{mesh_transferred:.1f}")

        # 鏈€缁堢粺璁?        print(f"[CTMMD 2.6] ===== 瀹屾垚 =====")
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
                            co = mesh.matrix_world @ v.co
                            zs.append(co.z)
                            cnt += 1
            if cnt:
                print(f"[CTMMD 2.6]   {src_name:<6}: {cnt:5d}椤剁偣  Z=[{min(zs):.3f}, {max(zs):.3f}]")
            else:
                print(f"[CTMMD 2.6]   {src_name:<6}: 0椤剁偣")

        self.report({'INFO'}, f"涓婂崐韬?鏉冮噸鍒嗛厤瀹屾垚锛坽mode_label}锛夛細{total_vertices} 椤剁偣澶勭悊")
        return {'FINISHED'}

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

