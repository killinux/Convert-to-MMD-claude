# 胸部中线塌陷 (cleavage collapse) 修复方法清单

**症状:** 跑 VMD 过程中, 两乳之间 (胸骨中线/cleavage) 被拉开成 V 字或出现明显
凹陷, 尤其在 `amp_breast_physics` 调到 STRONG / CUSTOM 大 angle 后。

**记录时间:** 2026-04-19, HEAD `5dbcded`

---

## 根因分析 (两个主要嫌疑)

### R1. cleavage 顶点同时绑在 乳奶.L 和 乳奶.R 上
中线那一溜 verts 各自挂 ~0.5 权重到左右胸骨。
左右 bone 一旦独立 rotate (joint 默认 ±10° 也允许), 中线两侧向外转的分量叠加
→ 中线被拉开成 V 字。

### R2. 没有"中央 anchor" rigid
左右乳奶 rigid 只各自 joint 到 `上半身2` 一个点。物理一跑, 两边各走各的, 中线
没有任何中央 constraint 拉住 → cleavage 变形幅度 = 左右摆动差值。
官方 TDA 等模型通常有一个"胸中央" rigid 拴两侧, 本 preset 没有。

### R3. (次要) 调 amp 后 angle 过大
`amp_breast_physics(level=STRONG)` 会把 joint angle 放到 ±45°。配合 R1/R2,
中线拉扯被放大到极值。

---

## 修复方法, 按侵入性从低到高

按 "先试最简单, 不行再升级" 的顺序。每条都列:
- **做法** / **代价** / **风险** / **实施状态**

---

### A. RESET op (一键回 preset 默认) — **最低成本**
**做法:** UI → 🎚 调整胸部物理强度 → **RESET**, 回读
`mmd_standard_inase.json` 的 mass=1.0 / damp=0.5 / ±10°。
**代价:** 胸部摆幅最小 (旧默认值), 视觉可能偏保守。
**风险:** 无, 完全可逆。
**状态:** ✅ 已实现 (HEAD `5dbcded`, 2026-04-19)

---

### B. 缩小 preset 默认 angle (±10° → ±7°)
**做法:** 改 `presets/physics/mmd_standard_inase.json` 的 `maximum_rotation` /
`minimum_rotation` 为 ±7° (0.1222 rad)。
**代价:** 整体摆动幅度减半, 大动作 VMD 看起来偏硬。
**风险:** 改了模板影响所有未来 convert (含其他模型)。
**状态:** ⬜ 未实施。如果 A 回 ±10° 仍然中线塌陷, 再试这个。

---

### C. 加"胸中央" anchor rigid + 对称 joint — **推荐**
**做法:**
1. 在 `上半身2` 骨头 head 处加一个 PASSIVE rigid (或叫 `乳中央`),
   shape=SPHERE, size~3cm, collision_group 跟 breast 独立。
2. 左右 `乳奶.L/R` 的 joint 不再只连 `上半身2`, 而是双边都连到
   `乳中央`。形成 "L—中央—R" 链式约束。
3. 左右独立 rotate 时, 中央 rigid 作为 passive 跟随 上半身2, 约束两侧 joint
   pivot 共享同一点, 抑制左右 drift。
**代价:** preset json 要加 1 rigid + 调 2 个 joint 的 rigid_a_idx。
**风险:** 需要验证 joint 对两个 rigid 的 constraint 是不是过度约束导致
摆动幅度减半; 可能要微调 joint angle 放大点补偿。
**状态:** ⬜ 未实施。是 R2 的直接解决方案, 不动任何权重。

**实施提示:**
- `presets/physics/mmd_standard_inase.json` 加一个 idx=35 的 rigid `乳中央`,
  `bone=上半身2`, `type='0'` (PASSIVE/BONE), size small。
- 左右 breast joint 的 `rigid_a_idx` 从 `19` (上半身2 本身 rigid) 改成 `35`
  (乳中央)。
- 或者左右各加一个 joint 挂到 `乳中央` (双 joint 方案), 视效果选一。
- 改完跑 reika-phys-vmd 回归测试对比振幅。

---

### D. 清 cleavage 顶点的 乳奶.L/R VG 权重 — **最后手段**
**做法:** 把胸骨中线 ~1cm 宽的一溜 vertex 的 乳奶.L 和 乳奶.R weight 清零,
权重全转到 `上半身2` (胸骨骨)。中线 mesh 完全不跟 breast bone 动。
**代价:** cleavage 区域变"死", 正常呼吸/上半身2 转动时中线表现跟以前不同。
**风险:** ⚠️ **违反用户的"不要轻易切权重"原则** (memory:
`feedback_no_cut_weights.md`)。XPS 原始权重设计假设了中线跟随, 动手改可能
牵连一大片。需要用户明确授权。
**状态:** ⬜ 未实施。只在 A / B / C 都失败后考虑。

---

### E. 其他候选 (如果上面都不行)

#### E1. Joint linear spring 拉回
joint 的 `spring_linear` 设一个中心回弹, rigid 飘出太远时被拉回。
**风险:** 跟 angular 组合后可能震荡。需要调参。

#### E2. Rigid 互相 collision 阻挡穿插
检查 `collision_group_number` + `collision_group_mask`, 让 `乳奶.L` 和
`乳奶.R` 能互相 collide, 物理阻挡两边穿越中线。
**状态:** preset 目前 mask 全 True, 已经 collide。但 sphere shape 太小可能
碰不上。可以放大 size 到 50% 骨长度(默认 60%→80%), 物理阻挡更容易。

#### E3. Corrective shape key
当 乳奶.L rotate 到极值时触发一个 corrective shape, 反向补偿中线 mesh。
手工制作成本高, 最复杂, 不推荐。

---

## 推荐尝试流程

```
[出现中线塌陷]
     │
     ▼
  试 A (RESET op)
     │
  解决 ── YES ── 收工
     │
     NO
     ▼
  试 C (中央 anchor) ────── 加 preset rigid + joint
     │
  解决 ── YES ── 改 preset + 写回归测试 + commit
     │
     NO
     ▼
  试 E2 (放大 collision sphere) + E1 (spring_linear)
     │
  解决 ── YES ── 调参入 preset
     │
     NO
     ▼
  用户授权 + 试 D (清 cleavage VG)
```

- 跳过 B (改 preset 默认 angle), 因为损失太大, 而且 A 已经能达到同样效果。

---

## 回归验证

每次改动后, 用 `doc/reika_physics_vmd_test.md` 里的 reika-phys-vmd 流程做对比:
- 八方来才 VMD 里, **关注**帧 80-160 (大摆动段) 的胸部中线是否出现 V 字。
- 振幅基准: 摇香 乳奶.L x ≈ 3.8cm, 八方来才 ≈ 7.3cm。如果改动让振幅降到
  < 60% 基准, 说明改得过头了。

---

## 相关文件

- `operators/physics_operator.py` — `amp_breast_physics` op (含 RESET)
- `presets/physics/mmd_standard_inase.json` — breast rigid + joint 定义
- `doc/reika_physics_vmd_test.md` — 物理回归测试脚本
- `doc/physics_handoff_2026_04_19.md` — 物理 pipeline handoff
