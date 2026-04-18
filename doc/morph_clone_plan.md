# Clone Target Morphs — 设计文档

## 背景

当前 addon 转换出的 MMD 模型 `vertex_morphs / bone_morphs / material_morphs = 0`，完全没表情（见 `TODO.md` P3 / `ui_panel.py` 表情区占位 Label）。

典型工作流里，target PMX（例如 Purifier Inase 18、Reika Shimohira 2 18）在 preprocessing 阶段就 import 到场景里做骨骼参考，本身自带完整的 MMD 标准表情（あ/い/う/え/お/まばたき/笑い/ウィンク/涙…）。

**最小路径**：把 target 的 topology-safe morph（bone / material / group）克隆到转换模型，vertex / uv morph 留 P2（按 vertex index 走，不同 mesh topology 不安全，需要 proximity-based transfer）。

## 设计

新增 operator `clone_morphs_from_target`（`bl_idname: object.clone_morphs_from_target`），UI 入口在 option2「物理+表情」tab 替换现有 morph 占位 Label。

### 参数

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `source_root` | PointerProperty → Object (poll: mmd_type=='ROOT') | 当前 active 所在 mmd_root | 克隆目的地 |
| `target_root` | PointerProperty → Object (poll: mmd_type=='ROOT', ≠source) | 场景里另一个 mmd_root | 克隆来源 |
| `clear_existing` | BoolProperty | True | 克隆前清空 dst 的三类 morph，避免累积 |

### 流程

1. **枚举 target**：用 `mmd_tools.core.model.Model(target_root)` 拿到 `target_root.mmd_root`，读 `.bone_morphs / .material_morphs / .group_morphs`
2. **建 dst 校验集**：
   - `dst_bones = set(dst_model.armature().data.bones.keys())`
   - `dst_materials = set()` — 遍历 `dst_model.meshes()` 每个 mesh 的 `obj.data.materials` 收集材质名
3. **Clone bone_morph**：for each target morph → 新建 dst entry，复制 `name / name_e / category`；for each `BoneMorphData` offset：
   - 如 `offset.bone ∈ dst_bones` → `dst_bm.data.add()` 复制 `bone / bone_id=-1 / location / rotation`
   - 否则记 skipped_bones
   - 若整条 morph 所有 offset 都 skip → 丢弃整条
4. **Clone material_morph**：同上，校验 `offset.material ∈ dst_materials`；复制 15 个字段（`material / offset_type / diffuse_color / specular_color / ambient_color / edge_color / edge_weight / shininess / texture_factor / sphere_texture_factor / toon_texture_factor / material_offset` 等）
5. **Clone group_morph**：在 bone/material 克隆完之后处理。for each `GroupMorphData` offset 校验 `offset.name ∈ (dst.bone_morphs ∪ dst.material_morphs ∪ dst.group_morphs)`
6. **显式跳过 vertex/uv**：日志 `SKIP N vertex_morphs, M uv_morphs (topology unsafe — TODO P2)`
7. **日志总结**：`[CTMMD 13] Cloned morphs: bone=N/M, material=N/M, group=N/M, skipped bones=[...], skipped materials=[...]`

### 涉及文件

- **新建** `operators/morph_operator.py`
- **修改** `__init__.py` — import + _safe_register + _safe_unregister
- **修改** `ui_panel.py` — 替换 morph_box 的 Label 为真实 operator 按钮
- **修改** `TODO.md` — P3 表情章节状态更新

### 复用

- `mmd_tools.core.model.Model` — addon 已在 `physics_operator.py` import 过
- `Model.armature()` / `Model.meshes()` / `Model.rootObject()`
- 直接 PropertyGroup API：`mmd_root.bone_morphs.add()` / `.data.add()` / `.clear()`
- CTMMD 编号 13（one_click 11 + 12 胸部物理之后）

## 不做

- ❌ vertex_morph / uv_morph 克隆（留 P2，proximity-based transfer）
- ❌ 接入 one_click_convert（表情 clone 依赖手动选 target，不适合全自动）
- ❌ preset schema 改动（preset 不管表情，per-run 选 target）
- ❌ mmd_tools_helper 集成（Display Panel 收尾，P2）

## 验证

### Inase 端到端
```python
# Blender 场景已有 Inase 转换后 root + target Purifier Inase 18 root
bpy.ops.object.clone_morphs_from_target(clear_existing=True)
# 检查
dst = bpy.data.objects['<转换后 root 名>']
print(len(dst.mmd_root.bone_morphs),
      len(dst.mmd_root.material_morphs),
      len(dst.mmd_root.group_morphs))
```
**预期**：bone > 0，三类计数与 target 接近（少数因 dst 缺骨被 skip）。

### Reika 端到端
同上，preset `daz_genesis8`，target `Reika Shimohira 2 18`。

### 回归
跑一次 `one_click_convert` 不触发 clone_morphs，原 11 步基准数据 non-cosmetic diff = 0 保持。

### 边界
- 场景无 target：poll 返回 False，按钮 greyed
- target 0 morph：日志 `target has 0 morphs, nothing to clone`，正常退出
- dst 骨骼全缺：整条 morph 丢弃，日志列 skipped
- 重复跑：`clear_existing=True` 总数稳定
