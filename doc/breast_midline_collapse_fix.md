# 胸部物理问题修复清单

**记录时间:** 2026-04-19, HEAD `5dbcded`
**适用于:** `amp_breast_physics` op 调档后 (或 preset 默认下) 看到的胸部物理异常

## 目录

- 症状 1 — [中线 (cleavage) 塌陷成 V 字](#症状-1-中线塌陷-cleavage-collapse)
- 症状 2 — [部分帧胸部凹陷进身体 (STRONG / 大 angle 时)](#症状-2-胸部凹陷进身体)

---

## 症状 1: 中线塌陷 (cleavage collapse)

**症状:** 跑 VMD 过程中, 两乳之间 (胸骨中线/cleavage) 被拉开成 V 字或出现明显
凹陷, 尤其在 `amp_breast_physics` 调到 STRONG / CUSTOM 大 angle 后。

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

---

## 症状 2: 胸部凹陷进身体

**症状:** 跑 VMD 过程中, 部分帧胸部 mesh 明显凹陷到身体内部 (像是胸部被身体
"吞了一下"), 尤其在 `amp_breast_physics` 调到 STRONG / CUSTOM 大 angle 后或
VMD 含快速动作。RESET / MILD 下通常看不到。

### 根因 (从最可能到最次)

#### R1. Sphere 太小 + 没 body chest anchor rigid → rigid 穿透身体
`mmd_standard_inase.json` 中乳奶 rigid `size_per_bone_length=0.6`, sphere
半径 ≈ 骨长 × 0.6 ≈ 3cm。骨长 = 乳奶.L/R 到 tail 的距离, 通常 5cm。
当 joint ±45° rotate 到朝向身体方向, sphere 中心被带到 body 内部,
sphere 半径不够大, collision 不足以反推出来 → mesh 跟着陷入。

#### R2. physics substeps 不够, 高速 rigid tunnel body
Blender `scene.rigidbody_world.substeps_per_frame=10` (Inase setup 默认),
high-amplitude swing 下, rigid 单帧速度超过 body rigid 厚度 → collision
检测跳过 → rigid 穿透。

#### R3. Joint 允许 rigid rotate 到"朝内"姿态
joint `maximum_rotation` 三轴都 ±45° (STRONG), rigid 绕 Z 轴内转时 sphere
朝向 body 里面, 内转没有物理阻挡 (因为 body 没 PASSIVE rigid 在对应位置)。

#### R4. collision_margin 过小
Blender default `collision_margin=0.04m`, 对于 2-3cm 大小的 sphere 已经
够, 但如果 margin 没显式设置可能更小, 接触判断过严。

---

### 修复方法 (从最简单到复杂)

#### S2-A. RESET op (减小摆幅到不足以穿透) — **最低成本, 优先试**
**做法:** 同症状 1 的 A。`amp_breast_physics(level='RESET')` 回 ±10°,
摆幅小到 rigid 不会 rotate 到身体内部。
**代价:** 摆幅保守。
**状态:** ✅ 已实现 (HEAD `5dbcded`)

#### S2-B. 增大 physics substeps
**做法:** `bpy.context.scene.rigidbody_world.substeps_per_frame = 20`
(或 40)。加倍 substeps, tunneling 概率减半。
**代价:** Bake 慢 2 倍。
**风险:** 无。
**状态:** ⬜ 未实施。如果 A 不够, 试这个 (临时运行时改即可, 不用改代码)。

#### S2-C. 增大 breast sphere size
**做法:** 改 `mmd_standard_inase.json` 中乳奶 rigid 的
`size_per_bone_length` 从 `0.6` → `0.9` 或 `1.0`。sphere 变大, 即使中心穿
到 body 内部边缘, 球面还在外侧能被碰撞推回。
**代价:** sphere 变大后, breast mesh 的 deform 可能被影响 (如果 rigid
是 physics_mode=1 "bone + physics", bone 的位置跟 rigid 中心绑定)。需要
实测是否胸部显得"肿"。
**风险:** 改 preset 影响所有未来 convert。
**状态:** ⬜ 未实施。S2-A + S2-B 都失败再试。

#### S2-D. 增大 collision_margin
**做法:** 对每个 breast rigid 设 `o.rigid_body.collision_margin = 0.01`
(或 0.02)。接触判断提前, 减少穿透窗口。
**代价:** 接触会看起来"飘起来"一点点。
**状态:** ⬜ 未实施。

#### S2-E. 给 body chest 加 PASSIVE rigid — **最根本**
**做法:** `mmd_standard_inase.json` 加一个 body 侧 rigid (比如 `胸体`,
shape=BOX 或 SPHERE, bone=上半身2, type='0' PASSIVE, 覆盖 body mesh
chest 区域)。breast rigid 撞到它会被物理反弹, 从 body 一侧挡住。
**代价:** preset 多 1 rigid, collision group 需要设置 (breast ↔ 胸体
collide, 但 胸体 ↔ 其他 body rigid 不 collide 避免自撞)。
**风险:** collision group 配错会导致 body 其他物理全错。
**状态:** ⬜ 未实施。是最"正确"但工作量最大的方案。

### ⚠️ 尝试失败记录 2: B 方案 (mass=0.999/damp=0.05/mode=2) (2026-04-19, runtime only, 未 commit)

**尝试:** 把 breast rigid 改成 N 式紧弹参数 — mass=0.999, linear/angular damping=0.05,
`mmd_rigid.type='2'` (物理+骨骼位置对齐)。理论上 mode=2 应让 rigid 位置严格跟
bone 走, 物理只影响 rotation。

**实测结果** (Inase + baseline 参数 vs B 参数对比):
| VMD | 参数 | max L-R gap | max/rest |
|---|---|---|---|
| 八方来才 | baseline (mass=1/damp=0.5/mode=1) | 26.10cm | 2.00x |
| 八方来才 | B (mass=0.999/damp=0.05/mode=2) | 22.76cm | 1.74x |
| 摇香 | B | 23.80cm | 1.82x |

数字改善 13% (2.00x → 1.74x), 但**视觉上** peak 帧 (摇香 frame 86 低头弯腰) 仍能
看到明显中线 V 字, bikini 内边缘裸露。用户评价"完全不可用"。

**失败原因:** Blender Bullet 物理引擎对 `mmd_rigid.type='2'` 没严格 kinematic
binding 的 enforcement — linear 的 "0-0" limit 仍有 drift, rigid 位置仍脱离
bone。mode=2 的承诺没兑现。

**教训:** 光调 rigid 参数 (mass/damp/mode) 无法解决中线塌陷, 必须**结构性改动**:
- A2 真 N 式 (加 bone + 重分 weight) — 次优, 重
- D2 runtime anchor op — 避免手写 preset, 待尝试

---

### ⚠️ 尝试失败记录 1: 一次性手写 preset 加 anchor+胸体 (2026-04-19, commit `643c3ba` → reverted `02f5d6c`)

**尝试:** 直接在 `mmd_standard_inase.json` 里加 乳中央 idx=35 + 胸体 idx=36 +
把 breast joint 的 `rigid_a_idx` 从 19 (上半身2) 改成 35 (乳中央), 打算一次
性实现 Fix C + S2-E。

**失败原因:**
- **坐标系错配**。preset 里 rigid `local_matrix` 和 joint `local_matrix_in_a`
  都**相对原 rigid_a (上半身2 rigid)**, 其 matrix 含非 identity rotation。
  我给新 rigid 用 identity rotation + translation = breast joint_in_a 的值,
  结果 anchor 放偏了 20cm。
- 改 rigid_a_idx 但不改 joint `local_matrix_in_a`, joint 位置也飘掉。
- 运行时手动 fix anchor world pos 后 rebuild, 物理更不稳 (L-R gap 拉开到
  原距 2.6 倍, 26cm vs 原 10cm)。

**教训:** preset 里的 matrix 是从 `extract_physics_template` 从**已有 rigid
topology** 抽取出来的精确值, 手工新增 anchor / 改 rigid_a 必须同步改 matrix
坐标系, 不是单改一个字段就行。

**下次的正确做法:** 两条路, 选一:
- **D1** 找一个 TDA 基准 PMX (带乳中央 anchor 的标准模型) → 用
  `extract_physics_template` 抽成新 preset (如 `mmd_tda_with_anchor.json`)。
- **D2** 代码层面加 op `OBJECT_OT_add_breast_anchor`: 动态计算 breast bone
  midpoint, 创建 anchor rigid + 修改现有 joint 的 pivot, 不改 preset。
  这样坐标系由 Blender 运行时算, 避免手写 matrix 错。

推荐 **D2**, 跟 `amp_breast_physics` 一样是独立 op, 对现有 model 即用即改,
不影响其他模型。

#### S2-F. 减小 joint rotation Z 轴 (朝内方向) 上限
**做法:** 不对称 joint 限: X/Y 保持 ±45° (左右/前后), 只把 Z (内旋) 限到
±15°。需要在 amp op 里加 "axis-aware" 模式, 或者直接改 preset 的
`maximum_rotation=[0.785, 0.785, 0.262]` (Z=15°)。
**代价:** breast rotate 不对称, 可能动作不自然。
**风险:** 不同模型 joint 坐标系不同 (local_matrix), 需要确认哪根轴是
"朝内"。
**状态:** ⬜ 未实施。

---

### 推荐尝试序列 (症状 2)

```
[胸部凹进身体]
   │
   ▼
 S2-A (RESET op)           ← 试这个
   │
 解决 ── YES ── 收工
   │
   NO
   ▼
 S2-B (substeps→20)         ← 临时调, 无需改代码
   │
 解决 ── YES ── 考虑改 preset 默认 substeps
   │
   NO
   ▼
 S2-C (sphere 0.6→0.9)      ← 改 preset
   │
   NO
   ▼
 S2-E (加胸体 PASSIVE)       ← 工程量大, 最后上
```

注: S2-D (collision_margin) 和 S2-F (Z 轴限制) 是可选补充, 不走主线。

---

## 相关文件

- `operators/physics_operator.py` — `amp_breast_physics` op (含 RESET)
- `presets/physics/mmd_standard_inase.json` — breast rigid + joint 定义
- `doc/reika_physics_vmd_test.md` — 物理回归测试脚本
- `doc/physics_handoff_2026_04_19.md` — 物理 pipeline handoff
