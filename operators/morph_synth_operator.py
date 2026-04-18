"""Path D programmatic morph synthesis — the working replacement for
the legacy KDTree bake+transfer (OBJECT_OT_bake_and_transfer_morphs, ③).

Thin wrapper around experimental/morph_transfer_poc.py. Core logic lives
there so the dev iteration loop (cli.py exec + reload) keeps working.

All verification operators (Tools A/B/C) are imported from the experimental
module and re-exposed in CLASSES for the addon to register.
"""
import bpy

from ..experimental import morph_transfer_poc as _mt


class OBJECT_OT_synth_vertex_morphs(bpy.types.Operator):
    bl_idname = "object.synth_vertex_morphs"
    bl_label = "④ 程序化合成 19 条 MMD morph (Path D)"
    bl_description = (
        "按 Inase XPS 的 vg + 公式化 recipe 在 5 个脸部 mesh 上烘焙 19 条标准 "
        "MMD 表情 morph (あ/い/う/え/お/ん/まばたき/ウィンク/笑い/困る…). "
        "不需要 target template, 也不做跨 mesh transfer (前者 KDTree 方案视觉会稀释). "
        "自动检测 face/双睫毛/眉/眼球 mesh."
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        meshes = _mt.find_inase_meshes()
        if meshes is None:
            self.report({'ERROR'}, "未找到 Inase 5 个脸部 mesh (face/lash×2/brow/eyeball)")
            return {'CANCELLED'}
        face, lash1, lash2, brow, eyeball = meshes
        _mt.bake_all_for_inase(face, [lash1, lash2], brow, eyeball)
        n_morphs = len([k for k in face.data.shape_keys.key_blocks if k.name != 'Basis'])
        self.report({'INFO'}, f"合成 {n_morphs} 条 morph on {face.name[:22]}")
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
