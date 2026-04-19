# 物理 (刚体) 通用化方案 — 2026-04-19

> 状态: 设计阶段已完成, **Tier 1 进行中**。Reika 实测 21 rigid (body only) vs target PMX 83 rigid
> (含 62 hair), 缺口全部在发型骨链。完整讨论见本文档。

## Context

当前 `operators/physics_operator.py` 的 `setup_physics` + Inase JSON 模板 + 体高缩放 + `fit_to_mesh`
收紧, 只覆盖 body rigid, 对 hair/裙摆/动态辅助骨链完全无能为力。用户需要对**任意 XPS** 都能生成合理物理。

| | Reika 当前 | Reika target PMX |
|-|-|-|
| rigid bodies | 21 | 83 |
| joints | 2 | 64 |
| hair rigids | 0 | 62 |

## 原理调研

### mmd_tools (Mac 本地 `core/model.py` + `core/pmx/importer.py`)

**`Model.createRigidBody(**kwargs)`** — **纯记录层, 无自动化**:
- 调用方必传: `shape_type`, `location` (世界坐标), `rotation` (YXZ Euler 世界), `size`, `dynamics_type`
- 可选: `collision_group_number/mask`, `name`, `name_e`, `bone` (name 字符串, 不是 index), `friction`, `mass`, `angular_damping`, `linear_damping`, `bounce`
- 对象是 MESH + `mmd_type='RIGID_BODY'`, parent 到 `rigidbodies` empty

**`Model.createJoint(**kwargs)`** — 同样纯记录层, 必传 `rigid_a/b`, `location/rotation`, `maximum/minimum_location/rotation`, `spring_angular/linear`

**PMX → Blender 坐标转换** (`importer.py::__importRigids`):
```python
loc  = Vector(rigid.location).xzy * scale       # PMX Y-up xzy swap + 0.08
rot  = Vector(rigid.rotation).xzy * -1          # xzy swap + 镜像
size = Vector(rigid.size).xzy if BOX else Vector(rigid.size)
size = size * scale
```

**结论**: mmd_tools 无默认值, 我们的 `global_scale` + `fit_to_mesh` 都是自建上层。

### PMXEditor (基于社区 15 年积累)

**"从骨自动生成刚体"**:
- 选多根骨 → `編集→ボーン→基本剛体/連結Joint生成`
- 位置 = 骨 head 世界坐标 (或 head/tail 中点)
- 形状:
  - 骨无 tail → **SPHERE** (默认 r)
  - 骨有 tail → **CAPSULE**; length = 骨长; radius ≈ 骨长 × 0.1-0.2
- 硬编码默认: mass=1, friction=0.5, damping=0.5, bounce=0, group=1, mask=全 true

**自动 Joint**: 相邻刚体间; angle limit 默认 ±10°; spring=0

**发型链典型 workflow**:
1. 选整条链 → 自动生成 capsule 链
2. 根骨改 dynamics=0 (追随), 其余 =1 (物理)
3. 根 Joint ±5-10°, 梢 Joint ±30°
4. 质量递减: 根 1.0, 梢 0.2-0.5

**关键启示**:
1. PMXEditor 的"自动生成"是**纯经验公式 + 骨形态判断**, 可以复刻给 XPS 无 target 的场景
2. 最高质量路径仍是"克隆已做好的刚体" — mass/damping/spring/angle-limit 是艺术, 没公式

## 推荐方案 (分层 fallback)

### Tier 1: 从 target PMX 克隆刚体 (主路径, 最准)

新 operator `OBJECT_OT_clone_physics_from_pmx`:
- UI: 文件选择器 → 指向任意 target `.pmx`
- 用 mmd_tools 的 `core.pmx.load()` 读 PMX
- 迭代 `model.rigids`:
  - bone index → bone name: `model.bones[r.bone].name`
  - **命名归一化** `左X → X.L`, `右X → X.R` (dict + fallback 原名)
  - 位置/旋转/大小用 mmd_tools 的 xzy swap + scale=0.08 (参照 `importer.py __importRigids`)
- 迭代 `model.joints`, 重建 rigid_a/b 引用
- 复用现有 `apply_physics()`, **不走 global_scale** (converted 与 target 同体型, scale=1), 仍跑 `fit_to_mesh` 可选收紧
- 命名归一化 + 存在性检查, 不存在的骨 skip + report

### Tier 2: Inase 模板路径 (已有, 保留)

对跟 Inase 同风格的模型, `setup_physics` + `mmd_standard_inase.json` 维持不变。

### Tier 3: 骨链推理自动生成 (无 target PMX 时的主路径)

**场景**: 用户只有 XPS, 没有 target PMX — 最常见, 必须靠推理。

**策略**: body rigid 套 Inase 模板 (Tier 2 通常能处理 humanoid XPS), 发型/裙摆/辅助骨链用 PMXEditor 经验公式补齐。

新 operator `OBJECT_OT_auto_chain_physics`:

**Step 1: 识别动态骨链**
- 不是 canonical body bone (keep-list: 頭/首/上半身*/下半身/肩/腕/ひじ/手首/足/ひざ/足首/乳奶/全ての親/センター 等)
- 没被大量 skinning (权重顶点数 < 30, 排除衣物主骨)
- 单链或浅分叉 (每根最多 2 子骨, 链深 >= 2)
- 根骨挂 canonical body 上 (頭→发型; 腰→裙摆; 手首→袖口)

覆盖: 发型、裙摆、尾巴、触角、耳朵飘带。

**Step 2: PMXEditor 经验公式逐骨生成**
- 有子骨 → CAPSULE; length=bone.length, radius=bone.length × 0.15
- 叶骨 → SPHERE, r=bone.length × 0.15
- 位置 = bone world head + tail/2 (骨中点)
- 旋转 = bone world matrix 的 YXZ
- dynamics: 链根=0 (STATIC), 其余=1 (DYNAMIC)
- 物理参数: mass=0.5 × 0.8^depth (递减), friction=0.5, damping=0.5, bounce=0
- collision_group: hair (头下) → 2, 其他 (body 下) → 3, mask 排除 group 1 (body)

**Step 3: 自动 joint**
- 链内父子间
- location = 父刚体 world 尾
- angle limit: 根 ±10°, 每深一层 +5°, 封顶 ±30°
- spring=0, max/min_location=全 0

**Step 4: fit_to_mesh 复用**
调用 `_fit_rigid_to_bone_verts()` + `_find_best_mesh_for_bone()`。

### 使用决策树

```
有 target PMX?
├─ YES → Tier 1: clone_physics_from_pmx(target)       ← 最准, 1:1 克隆
│         └─ 可选 Tier 3 补未匹配骨链
└─ NO  → Tier 2 + Tier 3:
          1. setup_physics(template=inase) → body    ← Inase 模板 + fit_to_mesh
          2. auto_chain_physics() → 发型/裙摆等      ← PMXEditor 经验公式
```

## 命名归一化表 (放 `physics_operator.py` 模块级)

```
左肩 → 肩.L / 右肩 → 肩.R
左腕 → 腕.L / 右腕 → 腕.R
左ひじ → ひじ.L / 右ひじ → ひじ.R
左手首 → 手首.L / 右手首 → 手首.R
左足 → 足.L / 右足 → 足.R
左ひざ → ひざ.L / 右ひざ → ひざ.R
左足首 → 足首.L / 右足首 → 足首.R
左乳奶 → 乳奶.L / 右乳奶 → 乳奶.R
```

## 改动文件

- `operators/physics_operator.py`
  - `JP_SIDE_PREFIX_MAP`, `CANONICAL_BODY_BONES`
  - `_pmx_rigid_to_entry(rigid, model, scale)`
  - `clone_physics_from_pmx(dst_root, pmx_path, ...)`
  - `OBJECT_OT_clone_physics_from_pmx` (file picker)
  - `_detect_dynamic_chains(arm)`
  - `auto_generate_chain_physics(dst_root, ...)`
  - `OBJECT_OT_auto_chain_physics`
- `ui_panel.py`: 物理 box 加 2 按钮: "🎯 从目标 PMX 克隆刚体" / "💇 自动生成动态骨链刚体"
- `presets/physics/mmd_standard_inase.json`: 不改

## 复用

- `mmd_tools.core.pmx.load(filepath)` — PMX 加载 (Mac 已验证)
- `Model.rigids/joints/bones[i].name` — PMX 数据访问
- `apply_physics()` 主体 — Tier 1 路径
- `_fit_rigid_to_bone_verts()` + `_find_best_mesh_for_bone()` — 收紧半径
- PMX→Blender 坐标转换 (`importer.py::__importRigids` 的 xzy + scale)

## Verification

Reika 场景 (HEAD `891f81a`):

1. **Tier 1**: `clone_physics_from_pmx(target='Reika Shimohira 2 18 None.pmx')`
   → 83 rigids + 64 joints, body ±2% 内匹配, hair capsule chain 生成
   → `mmd_tools.build_rig` + VMD 播放, 头发自然摆动

2. **Tier 3** (模拟无 target): 清 rigid → `setup_physics(inase)` + `auto_chain_physics()`
   → body 21 + 动态链几十条, VMD 下头发会飘 (参数经验值, 不如 Tier 1 精)

3. **Regression**:
   - Inase `setup_physics` 仍走 Tier 2, 零变化
   - fit_to_mesh 日志打印 ひざ/ひじ/首1 shrink (2-8mm)

4. **Edge cases**:
   - target 骨不在 converted → skip + report
   - 归一化失败 → 原名 fallback
   - PMX 损坏 → CANCEL + 报错

## 不做

- 不改 `setup_physics` (Tier 2 保留作 fallback)
- 不引入外部 Python 依赖
- 不自动猜 target PMX 路径
- 不做衣物物理 (超出范围)

## 当前进度 (2026-04-19)

- [x] 原理调研完成 (本文档)
- [x] HEAD `891f81a`: per-bone mesh pick + strand 过滤 + log 阈值 2mm
- [ ] Tier 1: `clone_physics_from_pmx` 实现
- [ ] Tier 1: Reika 实测 (应拿到 83 rigids)
- [ ] Tier 3: `auto_chain_physics` 实现
- [ ] Tier 3: Reika 模拟无 target 实测
