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

## 已知限制 (2026-04-18 实测)

### Inase 实测结果
- **Smoke test** (target PMX 导两次): 19/19 bone_morphs 全部克隆成功, 骨名/bone_id/rotation/location 全对
- **真实 Inase 转换后**: 0/19 bone_morphs 成功, 19/19 因骨缺失被 dropped
  - skipped bones: `Jaw Bone, QQ1-51` — 这些都是 target PMX 的面部表情驱动骨
  - 根因: 我们的 `cleanup_face_bones` (Step 6) 删除了 XPS 源的面部细骨并把权重合并到 `頭`，而 target 的 bone morphs 用它自己的一套面部骨 (Jaw Bone/QQ*)，两边 rig 结构不兼容

### 解决路径

- **方案 A**: 在 `cleanup_face_bones` 之后，从 target 克隆表情骨到 converted armature (保父链, 相对偏移放置)，然后 clone_morphs 骨名就匹配上了 — **已实现 2026-04-18**
  - 实现: `operators/face_operator.py` `clone_face_bones_from_target`
  - 流程: DFS 找缺的骨 + 父链 → edit mode 创建骨 (head/tail = 相对 parent 的 offset，roll = align_roll(target Z)) → 拷 mmd_bone 元数据
  - 局限: 补了骨但 converted mesh 没权重绑这些骨 (Step 6 已合并到 頭)，morph 旋转骨但不驱动顶点变形
- **方案 B**: bake bone_morph → vertex_morph proximity transfer — **已实现 2026-04-18**
  - 实现: `operators/morph_operator.py` `OBJECT_OT_bake_and_transfer_morphs`, UI ③
  - 流程: 对每条 target bone_morph 临时 pose armature → `evaluated_get(depsgraph)` 拿变形 mesh → per-vert 位移 → KDTree (head-relative + 身高归一化 scale) → 按近邻加权把 offset 写到 source mesh shape key → 注册为 mmd_root.vertex_morphs
  - 参数: distance_threshold (默认 2cm), k_neighbors (默认 3), min_offset_magnitude (默认 0.1mm), clear_existing
  - Inase 实测 19/19 传完, 最大位移 ~5mm (target 20m 体型缩到 src 1.5m 体型后合理)
  - 视觉对比: 嘴/眉/眼睛区位移方向正确, 嘴能开
- **方案 C**: 不删 XPS 面部骨, 改成 rename 映射 (跳过) — 实现复杂, preset 要加 XPS→target 面部骨对照表，放弃

### 技术踩坑记录
1. **Operator 不能用 `PointerProperty(type=bpy.types.Object)` 传参** — Blender 报 `keyword unrecognized`，改 `StringProperty` + `prop_search`
2. **`BoneMorphData.bone` / `MaterialMorphData.material` 是 virtual StringProperty**：getter/setter 通过 `FnModel(prop.id_data).armature()` 查 bone_id/material_id，operator 执行 context 下 setter 会静默失败 (只能从 operator 外面手动赋值才成功)。Fix: bypass RNA setter，预先用 `FnBone(pose_bone).bone_id` / `FnMaterial(mat).material_id` 查好，直接 `dst_off["bone_id"] = N` / `dst_off["material_id"] = N` dict-style 写
3. **`addon_disable + addon_enable` 不会从磁盘 reload 模块** — 必须 `del sys.modules['Convert_to_MMD_claude.*']` 后再 enable
