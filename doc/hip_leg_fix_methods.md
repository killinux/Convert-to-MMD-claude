# 腿/胯/臀部修复方法清单（不切权重原则内）

遇到转换后 XPS→PMX 模型的腿、胯、臀部变形问题时，严格按以下顺序诊断和修复。

## 核心原则

**不切权重** = 保留 XPS 源的权重分布和权重比例。

- ✅ **允许**：复制（足→足D）、迁移 unused 骨、插值分裂（twist 梯度）、选择性保护
- ❌ **禁止**：合并主变形骨权重、删除自然过渡区权重、手动改单顶点权重

**mesh 密度差异不是 bug** — 源模型和 target 拓扑不同时，权重顶点数不一致是正常的。

---

## 诊断顺序：L4 → L1 → L2 → L3

严格按顺序，不跳步。几乎所有「腿胯问题」的根因都在 L1/L2，跳到 L3 乱改权重是死路。

### L4 语义层（骨名）

- `rename_to_mmd` + preset 映射把源骨名改成 MMD 标准名
- `UNUSED_RENAME_MAP`（如 `Pectoral → 乳奶`）处理非标准辅助骨
- **检查点**：VMD 能否按名字找到骨

### L1 几何层（rest pose 对齐）

- `align_arms_to_reference` / `align_fingers_to_reference` — 用 target armature 对齐手臂/手指方向
- `fix_forearm_bend` — 前腕弯曲烘焙到 rest pose
- `complete_missing_bones` — 补齐 MMD 必需骨（腰 / グルーブ / 肩P / 肩C / 腰キャンセル / 両目 / ダミー 等）
- **检查点**：bone.head_local / 方向与 target 一致

### L2 约束/父链层

- `complete_twist_bones` — 位置识别，按 `t_head` 自动分 slot（腕捩/手捩 main + sub）
- `complete_d_bones` + Phase 5.2 **复制**（`足.L → 足D.L`，原骨清空）— 这是复制不切权重
- `complete_hip_cancel_bones` — 腰キャンセル 通过 constraint 抵消下半身旋转传到足
- `setup_pmx_attributes` — fixed_axis / 付与親 / 肩C 逆传 等
- `apply_additional_transform`（mmd_tools_convert 末尾自动调用）— 建 viewport constraint 链，让 twist sub 和付与親生效
- **辅助骨保留 + 父链继承**：xtra / ThighTwist 等保留原权重，parent 在主骨上即可自动跟随
- **诊断技巧**（rotate parent, watch child follow）：在 pose mode 旋转父骨，看子骨是否跟随。不跟 = constraint 链没建。

### L3 蒙皮层（权重，极度谨慎）

只有 L4/L1/L2 全排除后才考虑。允许的保守操作：

- **PRESERVE_HELPER_KEYWORDS**：`unused ` 前缀的辅助骨跳过 Phase 5.1 merge（Inase 的 xtra02/04/08/08opp）
- **Phase 4 Stray Weight Fix**：只修距骨段超 `body_h * 0.185` 阈值的游离顶点
- **Lower Body Cleanup**：只在 `max_d_w > lower_w`（D 骨权重严格大于下半身权重）时删下半身权重
- **twist 梯度分裂**（腕捩1/2/3，手捩1/2/3）：把主骨权重按 t 位置**插值**到空 sub slot（非切）

---

## 可用方法完整清单

| # | 方法 | 层级 | 作用 |
|---|---|---|---|
| 1 | rename_to_mmd | L4 | 源骨名 → MMD 标准名 |
| 2 | UNUSED_RENAME_MAP | L4 | 非标辅助骨重命名 |
| 3 | align_arms_to_reference | L1 | 手臂 rest pose 对齐 target |
| 4 | align_fingers_to_reference | L1 | 手指方向对齐 |
| 5 | fix_forearm_bend | L1 | 前腕弯曲烘焙到 rest |
| 6 | complete_missing_bones | L1 | 补全 MMD 必需骨 |
| 7 | complete_twist_bones | L2 | 按位置识别 twist slot |
| 8 | complete_d_bones + Phase 5.2 | L2 | 足→足D 复制（非切） |
| 9 | complete_hip_cancel_bones | L2 | 腰キャンセル 抵消下半身旋转 |
| 10 | setup_pmx_attributes | L2 | fixed_axis/付与親/肩C |
| 11 | apply_additional_transform | L2 | viewport constraint 链 |
| 12 | 辅助骨保留 + 父链继承 | L2 | xtra/ThighTwist 自动跟随 |
| 13 | PRESERVE_HELPER_KEYWORDS | L3 | Phase 5.1 跳过辅助骨 merge |
| 14 | Phase 4 Stray Weight Fix | L3 | 修明显游离顶点（保守） |
| 15 | Lower Body Cleanup（严格模式） | L3 | `D > lower_w` 才删 |
| 16 | twist 梯度分裂 | L3 | 插值分配到空 sub |

---

## 踩过的坑（血泪教训）

### 权重相关

1. ❌ **合并辅助骨到主变形骨**
   - 例：2026-04-13 尝试把 `lThighTwist` 合并到 `足D.L`
   - 后果：违反不切权重原则，失去 XPS 原始变形
   - 正解：保留 parent=足.L，靠父链继承旋转

2. ❌ **Lower Body Cleanup 用绝对阈值 `D 权重 >= 0.1`**
   - 后果：Reika 胯部 3510 verts 的下半身权重被误删，臀部变形错误
   - 正解（2026-04-13 `06ebdc0`）：只用相对比较 `max_d_w > lower_w`
   - 原理：保留 `下半身=0.6, 足D=0.3` 这种自然过渡区

3. ❌ **旧旧逻辑 `D > 0 → 删下半身`**
   - 后果：`下半身=0.95 + 足D=0.005`(stray) 会被整个删光
   - 历史教训已记录

4. ❌ **手动改单顶点权重**
   - 几乎永远是错的，先查 L1/L2

5. ❌ **认为 xtra 权重占比低是 bug**
   - Inase 足D 权重 2.7% vs target 15.1%
   - 这是 mesh 密度差异，不是 pipeline bug

### 父链相关

6. ❌ **把 pelvis helper bones reparent 到 腰**
   - 例：2026-04-12 之前的 `bone_operator.py` 逻辑把 Vagina/Rectum/Labia/Clitoris 等 reparent 到 腰
   - 后果：与 target parent 不一致
   - 正解（`746d78e`）：删除这段 reparent 逻辑，保留 parent=下半身

### 诊断相关

7. ❌ **跳过 L2 直接改 L3**
   - 2026-04-11 血泪教训：用户报告上臂扭曲，我跳过 L2 直接 spine purge / torso clean，13 commit 乱改权重，最后全部 reset
   - 原因其实只是缺 `apply_additional_transform` 1 行
   - 教训：L2 rotate parent watch child follow 测试必做

8. ❌ **VG 挂反（如 腕.L ↔ 腕捩.L）**
   - 先查 VG 顶点数对比，不要猜

9. ❌ **VMD scale 混用**
   - export=15, reimport=0.08, VMD 必须匹配 reimport
   - 虽然和权重无关，但容易被误诊成权重问题

---

## 关键修复记录

| 日期 | Commit | 修复 |
|---|---|---|
| 2026-04-11 | `3a6ea0c` | `apply_additional_transform` 1 行修复 Inase 上臂 twist viewport 不动 |
| 2026-04-12 | `746d78e` | 删除 pelvis helper bones 到 腰 的 reparent 逻辑（Reika 胯部骨 parent 对齐 target） |
| 2026-04-13 | `06ebdc0` | Lower Body Cleanup 去绝对阈值，只用相对比较 `D > lower_w`（Reika 胯部权重恢复 +1857 verts） |

---

## 实际案例参考

### Inase（XNA Lara 格式）

- 胯部辅助骨：`xtra02/xtra04`(parent=thigh) + `xtra08/xtra08opp`(parent=pelvis)
- 处理：全部通过 `PRESERVE_HELPER_KEYWORDS` 保留
- 结果：xtra08 parent=pelvis 能「接替」Lower Body Cleanup 删的下半身权重，胯部变形自然

### Reika（DAZ Genesis 8 格式）

- 胯部骨：pelvis（MMD 后是下半身）为主要权重源，没有 parent=pelvis 的大权重辅助骨
- 大腿扭转辅助骨：`lThighTwist/rThighTwist`，parent=lThighBend（MMD 后是足.L）
- 处理：
  - Phase 5.1 不进入（无 `unused ` 前缀）→ 权重自动保留 ✓
  - Phase 5.2 不动 ThighTwist → 保留原样 ✓
  - Phase 5 Lower Body Cleanup 必须用**相对比较**才不会误删胯部（Reika 没有辅助骨接替）
- 结果（2026-04-13）：parent 0 差异，非 cosmetic 0 差异

---

## 快速检查清单

出现腿/胯问题时，按顺序自问：

1. L4: 骨名对不对？`rename_to_mmd` 日志有没有 `Missing`？
2. L1: rest pose 和 target 对齐了吗？`align_arms_to_reference` 旋转角度是否合理？
3. L2: 在 pose mode 旋转父骨（如 足.L），子骨（如 lThighTwist/xtra）跟不跟？不跟就查 constraint 链和 `apply_additional_transform`
4. L2: `fixed_axis` / `付与親` / `腰キャンセル` 约束对不对？
5. L3（最后）: 权重 VG 顶点数和 target 差多少？差 = 本身 mesh 密度不同？别去补
6. 如果确定是 L3 问题：是 Lower Body Cleanup 误删？stray weight？VG 挂反？**永远不要手改单顶点权重**

相关文档：
- `leg_hip_d_bone_pitfalls.md`
- `twist_debugging_lessons.md`
- `mmd_additional_transform_mechanism.md`
- `xps_to_pmx_conversion_fixes.md`
