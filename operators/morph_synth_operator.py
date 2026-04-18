"""Path D programmatic morph synthesis — the working replacement for
the legacy KDTree bake+transfer (OBJECT_OT_bake_and_transfer_morphs, ③).

Thin wrapper around experimental/morph_transfer_poc.py. Core logic lives
there so the dev iteration loop (cli.py exec + reload) keeps working.

All verification operators (Tools A/B/C) are imported from the experimental
module and re-exposed in CLASSES for the addon to register.
"""
import bpy

from ..experimental import morph_transfer_poc as _mt
from ..experimental.morph_rigs import RIG_MAPS


class OBJECT_OT_synth_vertex_morphs(bpy.types.Operator):
    bl_idname = "object.synth_vertex_morphs"
    bl_label = "④ 程序化合成 19 条 MMD morph (Path D)"
    bl_description = (
        "通用化 Path D: 按 rig 的 vg + 公式 recipe 烘焙 19 条标准 MMD 表情 "
        "(あ/い/う/え/お/ん/まばたき/ウィンク/笑い/困る…). 自动识别 rig 类型 "
        "(xps_inase / daz_g8 / …) 并按 mesh 角色 (primary_face/eyelashes/eyebrow/eyeball) 分发."
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        print("[CTMMD 6] ===== Step 6: Synth Vertex Morphs (Path D, universal) =====")
        rig = _mt.detect_rig()
        if rig is None:
            self.report({'ERROR'}, "未识别 rig 类型 (scene vg 不含 head lip lower middle 等签名)")
            return {'CANCELLED'}
        rig_map = RIG_MAPS[rig]
        print(f"[CTMMD 6] detected rig: {rig}")
        meshes_by_role = _mt.find_meshes_by_role_vgs(rig_map)
        primary_face = meshes_by_role.get('primary_face') or []
        if not primary_face:
            self.report(
                {'ERROR'},
                f"未找到 primary_face mesh (rig={rig}). "
                f"可能是 cleanup_face_bones (step 7) 已跑过把 vg 合并了, 请重新导入 XPS 或用 '🚀 一键转换'.",
            )
            return {'CANCELLED'}
        _mt.bake_all_universal(meshes_by_role, rig_map)
        face = primary_face[0]
        n_morphs = len([k for k in face.data.shape_keys.key_blocks if k.name != 'Basis'])
        print(f"[CTMMD 6] Done: {n_morphs} morphs on {face.name}")
        self.report({'INFO'}, f"合成 {n_morphs} 条 morph on {face.name[:22]} (rig={rig})")
        return {'FINISHED'}


# Classes exposed for addon registration.
# Order matters: operators before panels (none here); modal registered once.
CLASSES = (
    OBJECT_OT_synth_vertex_morphs,
    _mt.MORPH_OT_verify_modal,
    _mt.MORPH_OT_run_spec_check,
    _mt.MORPH_OT_run_batch_screenshot,
    _mt.MORPH_OT_start_verify_modal,
)
