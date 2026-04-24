# 腿权重处理 Playbook

本文是**权重层(L3)** 的专题文档,聚焦 XPS→PMX 转换流程里涉及腿/胯/臀的权重操作 —— 包括:哪些方法可用、怎么调参、尤其是**什么绝对不能碰**。

**本文不覆盖 L1 (rest pose) / L2 (constraint 链) 诊断流程**,那部分完整版在 `hip_leg_fix_methods.md`。L2 没查前不要碰 L3,这是铁律。

---

## 七条硬红线(坚决不能碰)

在动任何权重之前先过这份清单。每条都是踩过坑流过血换来的:

1. ❌ **手动改单顶点权重**
   - 历史教训:2026-04-11 上臂扭曲问题,跳过 L2 直接改权重 13 个 commit 全 reset。根因只是缺一行 `apply_additional_transform`。
   - 规则:L4/L1/L2 没排完前,碰权重 = 走死路。

2. ❌ **合并辅助骨(xtra / ThighTwist / muscle_elbow)到主变形骨**
   - 尝试过:`lThighTwist → 足D.L` (commit `a273e0b`, 2026-04-12)
   - 被 revert:`ee4481e`,保留辅助骨靠父链继承
   - 原因:辅助骨有自己的轴方向和 XPS 原始分布,merge 后丢失独特变形

3. ❌ **用绝对阈值删 下半身 权重**
   - 旧逻辑:`max_d_w >= 0.1 → 删 下半身` → Reika 胯部 3510 verts 炸
   - 更旧逻辑:`D > 0 → 删 下半身` → `下半身=0.95 + 足D=0.005` stray 也被整个干掉
   - 正解 (`06ebdc0`, 2026-04-13):**严格主导** `max_d_w > lower_w`,自然过渡区 `下半身=0.6 + 足D=0.3` 保留

4. ❌ **把 pelvis helper bones reparent 到 腰**
   - 错误引入:`057efd9` 自动 reparent Vagina/Rectum/Labia/Clitoris 等到 腰
   - 后果:与 target parent 不一致
   - 正解 (`746d78e`):全删 reparent 逻辑,xtra08/xtra08opp 保持 parent=pelvis(→下半身)

5. ❌ **用 `mmd_tools.transfer_vertex_weights` / Blender `data_transfer` 推权重**
   - Proximity-based 通用 transfer 对 twist 这种"沿骨轴线性过渡"精度不够
   - 推权重只用 PMXEditor 风格双骨线性插值(下方 §2)

6. ❌ **以"xtra / D 骨权重占比低 = bug"为由去补权重**
   - 实例:Inase 足D 权重 2.7% vs target 15.1%
   - 这是 **mesh 密度差异**,不是 pipeline 问题。Inase 自己的 mesh 本来就少,不该用补权重去"追平"
   - 别用骨权重占比做 regression 指标

7. ❌ **跳步**
   - 元规则:L4 (骨名) → L1 (rest pose) → L2 (constraint 链) → L3 (权重) 严格顺序,不跳
   - 绝大部分"腿权重看起来异常"的问题根因都在 L1/L2

---

## 可用方法(L3 层)

以下是 convert pipeline 里实际使用的权重层操作,按执行顺序:

### 1. `足.L → 足D.L` 复制(不是切)

- 位置:`operators/leg_operator.py:complete_d_bones` (Step 4)
- 行为:新建 `足D.L`,从 `足.L` **完整复制**权重,原 `足.L` 不变
- **这不是切权重**,是复制。D 骨用来配合 IK,主骨权重保留

### 2. PRESERVE_HELPER_KEYWORDS — 辅助骨白名单

- 位置:`operators/leg_operator.py:70-76`
- 当前白名单:`xtra04 / xtra02 / xtra08 / xtra08opp / muscle_elbow`
- 作用:Step 8 Phase 5.1 "merge unused bones" 时,匹配关键字的 `unused ` 前缀骨**跳过 merge**,权重原地保留
- 原理:XPS 源对关节处的辅助变形骨有独特权重分布,通过父链继承就能得到对的变形,没必要 merge

### 3. Phase 4 — Stray Weight Fix

- 位置:`operators/leg_operator.py:652`
- 阈值:`stray_threshold = body_h * 0.185` (body_h = armature Z 尺寸)
- 行为:对每个 VG,找出距离骨段超过阈值的**游离顶点**,迁移到最近目标骨
- 为什么保守:只修"明显不对的 outlier"(通常是 source rig 本身就有的脏点),不碰主体分布
- 0.185 这个数是调出来的:大于这个通常是真 stray,小于这个大概率是合理邻接区

### 4. Phase 5 — Lower Body Cleanup(严格主导版)

- 位置:`operators/leg_operator.py:714-738`
- 核心判据:
  ```python
  if max_d_w > lower_w:      # D 骨权重严格大于 下半身权重
      verts_to_remove.append(v.index)
  ```
- **绝不能改回绝对阈值**(见红线 #3)
- 作用:当 D 骨已经成为该顶点的主导权重时,下半身 的残余是 XPS 源的噪声,可以安全清掉
- 结果:主导的保留,自然过渡的保留,只删"D 骨已主导但 下半身 没清"的噪声顶点

### 5. Phase 6 — 全ての親 → 頭 rename

- 位置:`operators/leg_operator.py:752`
- 为什么特别:原来用"空间最近 deform 骨"迁移,但头发顶点可能被分到跨身体的辅助骨(xtra07pp tail 延伸到脖子)→ 头发跟着手转
- 现行:直接 rename → 頭,一步到位。XPS `root` weights 几乎全是"应该跟头动"的头发/发饰
- 不是腿权重的直接操作,但胯部调试时要知道这条管线存在

### 6. Twist 梯度分裂(双骨线性插值)

- 位置:
  - `operators/twist_operator.py:457` `OBJECT_OT_split_upper_arm_twist_weights`
  - `operators/twist_operator.py:622` `OBJECT_OT_split_forearm_twist_weights`
- 调用点:`operators/leg_operator.py:791-793`,Step 8 assign_weights 最后
- **当前只对手臂 twist 做**(腕捩/手捩),**腿没有对应 op**
- 算法:per-vertex 算沿骨的 `t ∈ [0,1]`,在 t 的相邻两 anchor 之间线性分配
- 手臂 5 个 anchor:
  ```
  t=0.00  腕.L      (0%)
  t=0.25  腕捩1.L   (25%)
  t=0.50  腕捩2.L   (50%)
  t=0.75  腕捩3.L   (75%)
  t=1.00  腕捩.L    (100% main, fixed_axis)
  ```
- 公式:原权重 `w` 在 `[t_lo, t_hi]` 段拆成 `bone_lo: w*(1-k)`, `bone_hi: w*k`,`k = (t-t_lo) / (t_hi-t_lo)`
- **Shoulder dead zone**:`SHOULDER_DEAD_ZONE = 0.05`,t < 0.05 的顶点完全留在 腕.L 本身,避免肩-腕交接处被 腕捩1 吸走权重

> **腿为什么没做梯度分裂?** 目前腿的 twist 辅助骨(xtra02/xtra04/ThighTwist)走 PRESERVE_HELPER_KEYWORDS 路径,靠 XPS 原始权重 + 父链继承。如果未来要给腿加 twist 梯度,手臂版本是模板参考。

---

## 调试 recipe — "腿权重看起来不对"怎么查

严格按顺序,每步都是一个 kill switch:

**Step 1 — L4 骨名**
- 查 `rename_to_mmd` 日志有没有 `Missing`
- VMD 骨名匹配失败的报错

**Step 2 — L1 rest pose**
- `align_arms_to_reference` / `align_fingers_to_reference` 日志看对齐角度
- `bone.matrix_local` Y/Z 轴对比目标
- `Bone.roll` 只能 Edit Mode 访问;Object/Pose 用 `bone.matrix_local.to_3x3().col[2]` 代替

**Step 3 — L2 constraint 链(最容易漏)**
- 在 pose mode 旋转父骨(如 `足.L`),看子骨(`lThighTwist` / `xtra` / `足D.L`)**跟不跟**
- 不跟 → 查 `apply_additional_transform` 是否调用;查 `fixed_axis` / `付与親` / `腰キャンセル` 约束设置
- VG 挂反测试:对比 VG 顶点数(`腕.L` vs `腕捩.L` 不应该接近相等 — 相等大概率挂反)

**Step 4 — L3 权重(最后兜底,极度谨慎)**
- 和 target 比 VG 顶点数差多少 — 大差是 mesh 密度,不是 bug,**别去补**
- 用 `debug-leg-weights.md` 的 dump 脚本看每个顶点的实际权重分布
- 只动本 playbook §2 列的方法,其他一律不碰

---

## 案例对照

### Inase (XNA Lara)
- 胯部辅助骨:`xtra02/xtra04` (parent=thigh) + `xtra08/xtra08opp` (parent=pelvis)
- 处理:全走 PRESERVE_HELPER_KEYWORDS 保留
- xtra08 parent=pelvis → 接替 Lower Body Cleanup 删的下半身权重,胯部变形自然
- 非 cosmetic 0 差异

### Reika (DAZ G8)
- 胯部骨:只有 pelvis(→下半身),**没有** parent=pelvis 的大权重辅助骨
- 大腿扭转辅助骨:`lThighTwist`(parent=lThighBend→足.L)
- 处理:
  - Phase 5.1 不进入(DAZ 骨名没 `unused ` 前缀)→ 权重自动保留 ✓
  - Phase 5.2 不动 ThighTwist → 保留原样 ✓
  - Phase 5 Lower Body Cleanup **必须严格主导**,否则炸(Reika 无辅助骨接替,误删直接暴露)
- 非 cosmetic 0 差异

两个模型结构截然不同,同一套 pipeline 能过 = PRESERVE_HELPER_KEYWORDS + 严格主导 Lower Body Cleanup 是正确的通用设计。

---

## 关键修复记录

| 日期 | Commit | 修复 | 教训 |
|---|---|---|---|
| 2026-04-11 | `3a6ea0c` | `apply_additional_transform` 1 行修 Inase 上臂 twist 不动 | L2 早查,不是 L3 |
| 2026-04-12 | `ee4481e` | revert `a273e0b` ThighTwist merge | 辅助骨不合并 |
| 2026-04-12 | `746d78e` | 删 pelvis helper reparent 到 腰 | 不改父链到默认 |
| 2026-04-13 | `06ebdc0` | Lower Body Cleanup 改严格主导 `D > lower_w` | 绝对阈值是坑 |
| 2026-04-12 | `e732150` 系列 | Carpal 排除出 forearm twist 候选 | leaf vs 有 children 区分 |

---

## Cross-refs

- `hip_leg_fix_methods.md` — L4→L1→L2→L3 完整诊断流程(上层视角)
- `leg_hip_d_bone_pitfalls.md` — D 骨专项坑
- `debug-leg-weights.md` — 权重 dump/对比脚本
- `session_2026_04_13_reika_butt_fix.md` — Reika 胯部修复过程
- `twist_debugging_lessons.md` — L1-L4 诊断框架通用版
- `pitfalls_summary.md` — 跨主题坑索引
- `morph_path_d_lessons.md` — Face morph 专题(互相参考方法论)
