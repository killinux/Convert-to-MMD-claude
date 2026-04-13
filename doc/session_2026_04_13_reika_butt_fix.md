# 2026-04-13 Session: Reika 胯部修复 + 通用化验证

## 背景

续 2026-04-12 通用化重构会话。Reika（DAZ Genesis 8）已基本跑通，但臀部
区域存在轻微变形问题。本次 session 目标：查清根因、在「不切权重」原则内修复。

## 调查过程

1. **第一轮骨骼 diff** — Reika 96/206 cosmetic 差异，其中 11 个 parent 差异集中在
   `Vagina/Rectum/Clitoris/Labia` 等胯部骨：转换后 parent=腰，target parent=下半身。
2. **定位根因**：`bone_operator.py:490-515` 有段「DAZ pelvis helper reparent 到 腰」
   的逻辑，为了防止胯部撕裂错误地把 Vagina 等骨从 下半身 移到 腰。
3. **修复 1**（commit `746d78e`）：删除这段 reparent 逻辑。Parent 差异 11 → 0。
4. **用户反馈**：臀部仍有轻微问题。
5. **深入对比原始 XPS 权重**（Collection 2 的原始 Reika XPS）：
   - 原 XPS `pelvis` 44366 verts / wsum 34733
   - 转换后 `下半身` 41271 verts / wsum 33600（**少了 3095 verts**）
   - Phase 5 Lower Body Cleanup 删除日志合计 3510 verts
6. **定位根因 2**：Lower Body Cleanup 条件 `max_d_w >= 0.1 OR max_d_w > lower_w`
   中的绝对阈值 `>= 0.1` 太激进。胯部自然过渡顶点（`下半身=0.6, 足D.L=0.3`）被误判为
   「腿部主导」删掉下半身权重。Reika 没有类似 Inase xtra08 那样 parent=pelvis 的
   大权重辅助骨「接替」这些被删的权重，导致胯部变形错误。
7. **Inase 为什么没事**：
   - Inase 有 `xtra02/04/08/08opp` 4 根辅助骨（PRESERVE_HELPER_KEYWORDS 保留）
   - `xtra08/xtra08opp` parent=pelvis，权重 1082+1228 verts，刚好在胯部
   - Lower Body Cleanup 删掉下半身权重时，xtra08 接替 → 视觉上看不出来
8. **修复 2**（commit `06ebdc0`）：去掉绝对阈值，只保留相对比较 `max_d_w > lower_w`。

## 代码改动（完整清单）

### `746d78e` — Remove pelvis helper bone reparent to 腰 — keep under 下半身

`operators/bone_operator.py` 删除 27 行（`complete_missing_bones` 末尾的
pelvis helper reparent 逻辑）。

### `06ebdc0` — Lower Body Cleanup: remove absolute D-dominant threshold

`operators/leg_operator.py:714-738`:

```diff
-        # 只在 D 骨权重占主导时才删 下半身 权重。
-        # 旧逻辑 "D 权重 > 0" 会误伤胯部：一个 下半身=0.95 + 足D.L=0.005 (stray) 的顶点
-        # 会被整个删掉 下半身, 只剩 0.01 总权重, 表现为权重不协调、顶点几乎不动。
-        D_DOMINANT_MIN = 0.1  # D 骨权重 >= 0.1 才认为这个顶点"真正属于腿部"
+        # 只在 D 骨权重严格大于 下半身权重 时才删 下半身 权重。
+        # 保留胯部自然过渡区 (下半身=0.6 + 足D=0.3 类型的顶点),
+        # 对应"不切权重"原则: 保留 XPS 原始的权重分布, 不因 D 骨有权重就删下半身。
+        # 绝对阈值 (>= 0.1) 已移除: 之前会误删 Reika 胯部顶点 3510 个导致臀部变形错误。
         ...
-                # D 骨明显主导 (>= 0.1) 或 D 骨权重大于 下半身 权重 → 删 下半身
-                if max_d_w >= D_DOMINANT_MIN or max_d_w > lower_w:
+                # D 骨权重严格大于 下半身权重 → 删 下半身
+                if max_d_w > lower_w:
                     verts_to_remove.append(v.index)
```

### `656fbf9` — Add hip/leg fix methods doc

新增 `doc/hip_leg_fix_methods.md`：L4→L1→L2→L3 诊断顺序 + 16 个可用方法 +
9 个踩过的坑 + 案例对比（Inase vs Reika）。

## 测试验证

### Reika（DAZ Genesis 8）

| 指标 | 修复前 | 修复后 |
|---|---|---|
| 缩放比 | 0.7633 | 0.7633 |
| 共有骨 | 206 | 206 |
| **parent 差异** | **11** | **0** |
| **非 cosmetic 差异** | **11** | **0** |
| 下半身 verts | 41271 | **43128** (+1857) |
| Lower Body Cleanup 删除 | 3510 | **1703** (-51%) |
| 视觉（前/后/侧帧 150/250） | 胯部有问题 | 正常 |

### Inase（XNA Lara）— 回归测试

| 指标 | 基准 | 本次 |
|---|---|---|
| 缩放比 | 0.8364 | 0.8364 ✓ |
| 共有骨 | 116 | 116 ✓ |
| 总差异 | ≤ 7/116 | 7/116 ✓ |
| 非 cosmetic 差异 | 1（足IK親.L，target bug） | 1 ✓ |
| 足D.L / 足D.R | 297 / 296 | 297 / 296 ✓ |
| xtra 辅助骨 PRESERVE | 4 根 | 4 根 ✓ |
| Lower Body Cleanup 删除 | - | 56 |
| 视觉 | 正常 | 正常 ✓ |

**结论**：单一修改同时修复 Reika + 保持 Inase 稳定，完全在「不切权重」原则内。

## 原则的新理解

本次最重要的收获是搞清了 **Inase 能工作 vs Reika 不能工作的根本区别**：

- 不是某个硬编码参数的问题
- 是 **源模型拓扑的差别**：Inase 有 parent=pelvis 的大权重辅助骨（xtra08），
  自然接替 Lower Body Cleanup 删掉的下半身权重；Reika 没有对应辅助骨。
- 因此 Lower Body Cleanup 不能依赖「删掉的权重会被辅助骨补上」这个假设，
  必须在**删除条件本身**保守。

推而广之的原则：**pipeline 的每一步都应该在最保守的前提下工作，不能依赖后续步骤补救**。

## 踩过但避免的坑

本次 session 差点又犯的错误：

1. **尝试把 `lThighTwist/rThighTwist` merge 到 足D.L/R**（commit `a273e0b`，后 `ee4481e` 回滚）
   - 动机：这两根骨 target 没有，看起来「多余」
   - 错误：违反「不切权重」原则。ThighTwist 是 DAZ 大腿扭转辅助骨，
     parent=足.L，靠父链继承旋转提供大腿变形，和 Inase 的 xtra 辅助骨同理。
   - 用户提醒 → 立即回滚。

2. **差点给 DAZ ThighTwist 加 FORCED_TARGETS 规则**
   - 误以为 Phase 5.1 不处理 ThighTwist 是 bug，想补上
   - 实际：Phase 5.1 只处理 `unused ` 前缀是**设计上的正确**，ThighTwist 没前缀所以
     不进入 merge 流程 = 权重自动保留 = 和 PRESERVE_HELPER_KEYWORDS 效果一样
   - 教训：先搞清现有行为为什么这么设计，再判断是不是 bug

## 相关文件

- `doc/hip_leg_fix_methods.md` — 方法清单和诊断顺序（本次新增）
- `doc/leg_hip_d_bone_pitfalls.md` — 2026-04-11 的 8 条腿/胯坑
- `doc/mmd_additional_transform_mechanism.md` — MMD 付与親 机制
- `doc/xps_to_pmx_conversion_fixes.md` — 核心修复原理
- `doc/twist_debugging_lessons.md` — 2026-04-11 twist 系统血泪教训

## 下一步

见 `TODO.md`，重点：
- P0 通用化（DAZ 面部骨清理、通用辅助骨保留、更多格式验证）
- P1 上半身后续（ダミー、乳奶1、位置识别）
- P3 表情 morph（当前转换模型 vertex_morphs = 0）
