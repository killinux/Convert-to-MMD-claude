# XPS→PMX 转换插件通用化重构文档

## 背景

插件最初围绕一个 XPS 模型（Inase）开发和调优，代码中有大量硬编码的绝对坐标、距离阈值和特定模型的参考数据。为了支持任意 XPS 模型转换，需要把这些硬编码改成基于模型自身比例的动态计算。

## 核心思路

**一个公式**：`阈值 = 体高 × 比例系数`

- 体高 = `頭.head.z - 足首.L.head.z`（从实际骨骼计算）
- 比例系数 = 原硬编码值 / Inase 体高 1.35

这样不管模型是 1 米高还是 2 米高，阈值都会自动缩放。

---

## P0：关键阈值比例化（必须改，否则换模型必崩）

### 改了什么

#### `leg_operator.py` — 权重分配阈值

| 原值 | 新值 | 作用 |
|------|------|------|
| `HIP_TOLERANCE = 0.05` | `body_h * 0.037` | 髋部顶点 Z 上限容差 |
| `UPPER_BODY_FLOOR = 0.07` | `body_h * 0.052` | 上半身权重 Z 下限 |
| `stray_threshold = 0.25` | `body_h * 0.185` | 迷路权重修复距离 |
| `_guess_side ±0.01` | `body_h * 0.007` | 左右侧判断阈值 |
| `UPPER3_HEAD_Z = 1.3118` | 从 `上半身3.head.z` 直接读取 | 上半身3 权重切割线 |
| `UPPER3_BLEND_START_Z = 1.2725` | 从 `上半身2.tail.z` 直接读取 | 权重渐变起点 |

新增辅助函数 `_body_height(armature)` 统一计算体高。

#### `bone_operator.py` — 骨骼创建位置

| 原值 | 新值 | 作用 |
|------|------|------|
| `Vector((0,0,0.15))` | `body_height * 0.11` | 操作中心 tail |
| `Vector((0,0,0.3))` | `body_height * 0.22` | 全ての親 tail |
| `Vector((0,0,0.8))` | `upper_body_head.z * 0.75` | センター head |
| `y+0.1, z-0.12` | `spine_len * 0.25/0.30` | 腰 head 偏移 |
| `0.082` | `ctrl_bone_len = body_height * 0.06` | 肩P/肩C/ダミー 控制骨长度 |
| 各种 `+0.15/0.20/0.30/0.45` | `spine_len × 比例` | 脊椎骨 fallback 位置 |

新增参考量：`body_height`（体高）、`spine_len`（脊椎长度 = 首-上半身）、`ctrl_bone_len`（控制骨显示长度）。

### 为什么这样算比例

以 Inase 模型为基准反推：
- 体高 = 1.35m
- 原 HIP_TOLERANCE = 0.05 → 0.05/1.35 ≈ 0.037
- 原 stray_threshold = 0.25 → 0.25/1.35 ≈ 0.185
- 以此类推

---

## P1：去除 Inase 特定依赖

### 1. canonical fallback 改标准 A-pose

**文件**: `presets/canonical_arm_dirs.json`

原来存的是 Inase 模型的手臂方向（上臂 X=0.796, Z=-0.605），改成标准 MMD A-pose 45° 下垂方向（X=0.707, Z=-0.707）。

**影响**：只在场景中没有参考模型时生效。有参考模型时（常见流程）不使用 fallback。

### 2. twist 骨显示长度改比例

**文件**: `operators/twist_operator.py`

| 原值 | 新值 | 作用 |
|------|------|------|
| `TWIST_BONE_LENGTH = 0.082` | `seg_len * TWIST_BONE_LENGTH_RATIO(0.48)` | sub twist 骨显示长度 |

改成基于臂段长度的比例。这只影响骨骼在 viewport 里的显示长度，不影响变形。

### 3. twist 候选检测（已经是通用的，无需改）

分析后发现 `_scan_candidates()` 本身就是几何检测（到臂段的投影距离 + 权重质心），不依赖特定骨名。排除列表里的名字都是 MMD 标准骨名。

---

## 验证

所有改动后跑完整 Phase 1 + Phase 2 测试，结果与基准完全一致：

- Scale = 0.8364
- Bones: conv=169, tgt=263, common=160, real=116
- Diffs: 7/116（6 个 hair name_e + 1 个 足IK親 parent，全是已知项）
- 足D.L = 297 verts
- 4 根 xtra 辅助骨 PRESERVE 保留

---

## 剩余 P2 项（未做）

| 项目 | 说明 | 优先级 |
|------|------|--------|
| 通用物理模板 | 目前只有 Inase 提取的模板 | 低（物理可选） |
| IK 偏移改比例 | `足ＩＫ tail +0.1` 等 | 低（影响小） |
| 脚趾细分骨 | XPS 源没有 BigToe/SmallToe | 低（功能缺失） |
| 新模型实测 | 用不同 XPS 模型跑一遍验证 | 中（验证通用性） |
