# 腿/胯/D骨踩坑记录

多次迭代后留下的教训。`operators/leg_operator.py` 中 `complete_d_bones` /
`complete_hip_cancel_bones` / `assign_weights_*` 的现有逻辑是针对这些坑一一修
出来的,**不要轻易重构**。修改前先读这里。

## 1. 腰キャンセル 付与親 必须是 `腰` 不是 `下半身`

**commit**: `428951c`
**症状**: 176 帧腿部 IK 剧烈抖动, jitter > 30° 的帧数爆表
**原因**: `腰キャンセル.L/R` 的 parent 已经是 `下半身`。如果 付与親 target 再
指 `下半身`, mmd_tools 导入 PMX 时会把生成的 `_dummy_腰キャンセル` bone 的
parent 错误地设为 `下半身`, 于是 `下半身` 的大旋转被叠加到 `腰キャンセル` 上,
腿部 IK 链被旋转干扰。
**修复**: `setup_pmx_attributes` 里写死 `additional_transform_bone = "腰"`,
influence = -1.0。reimport 之后验证 `_dummy_腰キャンセル.L.parent == "腰"`
且 `_shadow_腰キャンセル.L.parent == "グルーブ"`。

## 2. 下半身权重清理必须看 D 骨阈值 (≥ 0.1)

**commit**: `70f6afb` (Phase 5)
**症状**: 胯部有一条 0.97 权重的顶点被误删, 胯部出现穿模洞
**原因**: Phase 5 的设计是"把主要受 D 骨影响的顶点从下半身顶点组移除",
但早期判断条件只看"有没有 D 骨权重", 导致 D 骨权重极小 (0.02) 的顶点也被误判
成 D 骨主导, 它们原本属于下半身的 0.97 权重被误删。
**修复**: 判断条件加阈值 `d_bone_weight >= 0.1 and d_bone_weight > lower_body_weight`
才算 D 骨主导, 才删下半身权重。

## 3. 头发 mesh 上的 `全ての親` 顶点组静止

**commit**: `70f6afb` (Phase 6)
**症状**: 动画时头发 3362 个顶点不动 (贴在原点)
**原因**: XPS 模型里有一个名为 `root ground` 的骨, rename_to_mmd 把它改成
`全ての親`。头发 mesh 上 root ground 的顶点组现在变成 `全ての親` 顶点组,
但 `全ての親` 在 MMD 里是控制骨 (`use_deform=False`), 所以这些顶点在姿态变
换时完全静止, 与其它头发骨断开。
**修复**: Phase 6 在 hair mesh (或所有 mesh) 上把 `全ての親` 顶点组 rename/
merge 到 `頭`, 让头发跟着 `頭` 运动。

## 4. XPS 辅助骨不要 merge, 要保留

**commit**: `6edf58a`
**症状**: 胯部变形出现剪切/翻转 (动画时腿弯曲角度>60° 时尤其明显)
**原因**: Phase 2 默认把 unused 骨的权重迁移到最近的 MMD 骨。但 XPS 常在关节
处放 helper bone (`xtra04`/`xtra02` 胯内, `xtra08` 臀外, `muscle_elbow`),
这些 bone 的**轴方向和主骨不同** — 有的向上指, 有的向前指, 用 mesh 上顶点组
带的 delta 旋转补偿特定角度的变形。merge 到轴向不同的主骨后, 旋转差被强制对
齐到主骨的轴, delta 补偿方向就错了, 变形剪切。
**修复**: `PRESERVE_HELPER_KEYWORDS` 列表内的骨**原地保留**, 不做 merge, 作为
额外 deform bone 进入 PMX, 父链继承旋转, 与 XPS 一致。

## 5. Reparent 连接骨时 head 会自动 snap

**commit**: `a9c7e70`
**症状**: step 2.1 reparent 后 `手捩.L` 长度变 0, 或 head 飞到奇怪位置
**原因**: Blender 在 edit mode 下, 如果一根骨的 `use_connect=True`, reparent
时 Blender 会自动把 head snap 到新 parent 的 tail (维持 connected 语义)。这
会破坏原本的几何位置。
**修复**: reparent 三步走:
```python
saved_head = eb.head.copy()
saved_tail = eb.tail.copy()
eb.use_connect = False      # 先 disconnect
eb.parent = new_parent_eb   # 再改 parent
eb.head = saved_head        # 复位
eb.tail = saved_tail
```
twist_operator 和 leg_operator 内所有 reparent 都走这个流程。

## 6. XPS foretwist 不能靠名字 rename 成 腕捩

**commit**: `855e8ec` (revert) + twist_operator 重写
**症状**: 胳膊肘位置不自然, 整条手臂链条形态错乱
**原因**: 早期版本用硬编码映射 `unused bip001 l foretwist -> 腕捩.L`。但
`foretwist` 在 XPS 里物理位置**在前臂**, MMD 的 `腕捩` 语义是**上臂扭转**,
位置在上臂。位置不匹配导致 ひじ.L 被拉到错误的 parent 位置, 链条畸形。
**修复**: `twist_operator.py` 完全用位置识别 — 先扫描候选骨的 `head_local`
到段的投影 t 值, 按段所属分配到 `腕捩` (上臂段) 或 `手捩` (前臂段), 不依赖
骨骼名字。

## 7. PMX 尺度约定 (scale)

**规则**:
- `mmd_tools.export_pmx` 用 `scale=12.0` (MMD 标准坐标系)
- `mmd_tools.import_model` reimport 已经是 12x 的文件时用 `scale=1.0`
- `mmd_tools.import_vmd` 加载 VMD 用 `scale=1.0` (匹配 reimport 后的模型坐标)

**混错的症状**: IK 链接错位, 腿部抖动/穿地, 动作幅度诡异放大缩小。

## 8. 5 阶段 Phase 的执行顺序敏感

`assign_weights` 里的 6 个 phase 顺序是有含义的:
- **Phase 2 (5.1) Unused→主骨 先于 Phase 1 (5.2) 主骨→D骨**: unused 骨先合并
  到主骨 (足/ひざ/足首), 再把主骨权重整体复制到 D 骨。反过来会导致 unused
  的权重没有进入 D 骨链, D 骨动画无效。
- **Phase 2 候选集用主骨而非 D 骨**: 因为 `足D` 的线段靠近臀部, 用 D 骨做
  per-vertex 分配会把臀部顶点误吸入 D 骨。

UI 上的 5.1/5.2 按钮显示顺序和这个内部顺序是一致的 (5.1=Phase 2, 5.2=Phase 1)。
