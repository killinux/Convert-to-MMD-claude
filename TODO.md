# TODO

## 目标：通用 XPS → MMD 转换插件

长期目标是把这个插件做成任意 XPS 模型都能一键转 MMD，而不仅限于 XNA Lara Inase。
当前已验证格式：XNA Lara（Inase）+ DAZ Genesis 8（Reika）。

---

## P0 — 通用化剩余工作

### 面部骨清理支持 DAZ 命名

- **`cleanup_face_bones`** 当前只识别 XNA Lara 的 `head xxx` 前缀（`head eyebrow/eyelid/lip/mouth/nose/tongue/cheek/jaw`）
- DAZ 模型用完全不同的命名：`lBrowInner/lBrowMid/lBrowOuter`、`lEyelidUpper/Lower/Inner/Outer`、`lCheekUpper/Lower`、`lLipCorner/LipUpperOuter/LipBelowNose`、`BelowJaw/Chin/LipBelow` 等
- Reika 转换后有 81 根 DAZ 面部骨残留，全部混在骨列表里
- 方案：
  1. 扩展前缀识别（加 DAZ 命名）
  2. 或改用 parent-based 识别：所有 parent=頭（DAZ 里是 `head`）的末端小骨 + 有 < 某阈值顶点权重 = 面部细骨
  3. 或读 preset 的 `head_bone` 字段找头骨，递归扫其子树

### 通用辅助骨保留策略

- 当前 `PRESERVE_HELPER_KEYWORDS` 硬编码 `xtra02/04/08/08opp/muscle_elbow`（Inase XPS 专用）
- DAZ 的 ThighTwist/ShldrTwist/ForearmTwist 没有 `unused ` 前缀，自动跳过 Phase 5.1（无意中达到保留效果）
- 想要通用：
  - 检测原则：若骨 parent 是 MMD 标准骨 && 不是 MMD 标准名 && 有权重 → 默认保留
  - 移除硬编码关键字
  - 需要确保 Inase 4 根 xtra 骨仍保留

### 更多模型格式验证

- 已验证：XNA Lara（Inase）、DAZ Genesis 8（Reika）
- 未验证：Mixamo、VRoid、Unity Humanoid、Bip_001 3ds Max、iClone
- Presets 目录里有 20+ preset 但大多没实测
- 每种格式至少跑一次 + target PMX 对比 + VMD 动作测试

---

## P1 — 上半身后续

- **ダミー.L/R**: MMD 标准的手首末端配饰挂点骨 (parent=手首, 长度~1.2x 手长)。
  无动作影响, 只给配饰/物品用。XPS 无对应源, 需要创建空骨。优先级低, 有动作
  需求后再做。
- **乳奶1.L/R (第二节)**: 当前只 rename `boob left/right 1` → `乳奶.L/R`。
  XPS 有 `boob left/right 2` 作为第二节, 目标 PMX 没有对应骨但有独立运动。
  是否把第二节 rename 成 `乳奶1.L/R` 需要验证是否能在 MMD 里正确变形, 可能
  需要物理 joint 配合。
- **乳奶骨的位置识别版本**: 目前 `boob/breast left/right 1` 是硬编码名字 rename。
  其他 XPS 模型 (Daz/Poser 等) 可能用不同名字。可以加位置识别: 扫描
  parent ∈ {上半身2, 上半身1} + 胸部区域 + 有权重 的骨。

## P2 — 下半身 / 腿

- **腿部 twist 系统**: target PMX 没有腿部 twist 骨 (标准 MMD 也很少有),
  但有些模型会加 (DAZ 有 ThighTwist/ShinTwist)。当前完全不处理，靠保留机制 work。
- **足IK親**: target 有 `足IK親.L/R` (parent=全ての親, 控制 `足ＩＫ` 的父骨),
  现在 `add_mmd_ik` 只创建 `足ＩＫ` 和 `つま先ＩＫ`, 没创建 `足IK親`。
- **脚趾细分骨 (BigToe/SmallToe)**:
  - Inase XPS 源没有 — TODO 可以从 target 克隆
  - Reika DAZ 源有 lBigToe/lBigToe_2 + lSmallToe1~4 + _2 — 可以映射到 MMD 标准的脚趾骨
  - 需要位置识别 + rename 方案

## P3 — 表情 / morph

- **vertex morph 生成**（方案 2，从 `project_face_bones_next.md`）
  - 识别「眼睛」/「嘴」顶点
  - 利用 XPS 面部细骨驱动 shape key 录制
  - 再从 shape key 建 MMD vertex morph
  - 当前转换后 vertex_morphs = 0，完全没表情
- **bone morph 克隆**（方案 3）
  - 读 target 的 mmd_root.bone_morphs 克隆到转换模型
  - 需要先补 MMD 表情控制骨（Jaw Bone 等）

## P4 — 物理

- **通用物理模板**:
  - 当前只有 Inase 模板
  - 需要从更多 target PMX 提取模板
  - 可能需要体型参数化（身高/胸围/腰围缩放）

## P5 — 代码 / 工具

- **operators/ 拆分**: 当前 `bone_operator.py` 里塞了 rename + complete
  + 两个 convert helper, 可以拆成 rename / structure / convert 三个文件。
- **preset 格式 v2**: 加上开关 (是否创建 twist sub, 是否创建 ダミー 等),
  目前只有 bone name 映射。
- **单元测试**: 给 twist_operator 写个能离线跑的 pytest, mock 一个简易 XPS
  骨架, 验证候选识别 + 分配算法。
- **已知 bug 清理**: 见 `doc/known_issues.md` BUG-01 ~ BUG-10

---

## 已完成

### 2026-04-13
- Lower Body Cleanup 从绝对阈值 `D >= 0.1` 改为相对比较 `D > lower_w`（commit `06ebdc0`）
  - Reika 胯部权重恢复 +1857 verts
  - Inase 无 regression
  - 符合「不切权重」原则
- 新增 `doc/hip_leg_fix_methods.md`：L4→L1→L2→L3 诊断顺序 + 可用方法 + 踩坑记录

### 2026-04-12
- pelvis helper bones 不再 reparent 到 腰（commit `746d78e`）
- 通用化重构 P0/P1：shadow/dummy 委托 mmd_tools，体高比例化，canonical A-pose fallback
- DAZ Genesis 8 preset + 完整 pipeline 验证（Reika）

### 2026-04-11
- `apply_additional_transform` 1 行修复 Inase 上臂 twist（commit `3a6ea0c`）
- 骨架对齐 target 完整迭代（10 commit）
- 上半身 twist 系统重写（位置识别）
- 死代码清理 -1930 行

---

## 已知残留差异（不需要修）

- **Reika**：96/206 cosmetic 差异（name_e + lock_loc 全是 Hair 骨），parent 差异 0，非 cosmetic 差异 0
- **Inase**：7/116 差异（1 个 足IK親.L 是 target PMX 自身 bug，其余是 name_e）
- mesh 密度差异（xtra 权重占比低 2.7% vs target 15.1%）不是 bug，是拓扑不同

参考：`doc/hip_leg_fix_methods.md` 的「踩过的坑」章节
