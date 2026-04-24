# Path D 经验总结

**What Path D is**: 不跨 mesh transfer,直接在 source mesh 自己上用 source 的 vertex group + 手写公式算 per-vert offset,per-mesh 生成每条 MMD standard morph。

**Why it won**: 前 3 条路(TPS/Sumner/SurfaceDeform+BVH)都在跨 mesh 对齐环节栽了 — 脸薄层/高密度 fold 区域(嘴唇/眼皮)几何差异太大,任何"找最近 tri + warp"的方法都会出现翻唇/mesh tear/位移稀释。Path D 绕开了这个 fundamental 限制。

**Outcome**: Inase 19/19,Reika DAZ 19/19 (后续 S1-S3 通用化后),zero cross-mesh artifacts。

---

## 核心决策:为什么最终是 per-mesh programmatic

| 维度 | Cross-mesh transfer (A/B/C) | Path D (per-mesh) |
|---|---|---|
| 对齐 | 必须做 template↔source 几何配准 | 不需要,source 自己 vg 就是 mask |
| 污染 | bind 泄漏到邻区(鼻/脸颊) | vg 天然零污染 |
| 拓扑敏感 | 上下唇 verts 法线微差→bind 错 | 无关,vg 是定义域 |
| 每条 morph | 理论自动 | 手写公式,19 条 × 小时级 |
| 复杂表情 | 理论上能复用 template | 笑い/困る 需更多 vg 或靠不对称 |

Trade-off 很清楚:**每条 morph 的人力成本换算法鲁棒性**。对"任意 XPS 源、无 target"的约束,这个 trade-off 必选。

---

## 可迁移的工程教训

以下是本项目之外也适用的原则:

### 1. "数据量级对"不等于"视觉对"

反复犯:max offset 12mm、上下唇 Z 方向正反都对、region distribution OK,但视觉还是撅嘴/前突/翻唇。

**对策**:视觉验证是 ground truth。side-by-side template vs source 同 slider 值截图对比,二选一就算完。

### 2. 跨几何域迁移对"薄层 + 高密度 fold"区域不 robust

嘴唇/眼皮拓扑是 3D character rig 里最刁钻的区域。相邻 vert 法线微差就能决定 bind 结果。这是 fundamental 的,不是参数问题。

**对策**:遇到"薄层 + fold"就别做跨 mesh bind。要么 per-triangle affine (Sumner,复杂),要么换用 source 自身结构(Path D)。

### 3. 放弃"cross-mesh 一次解决所有 morph"幻想

Template-driven transfer 的诱惑:写一次算法吃所有 morph。现实:越是复杂表情 (笑い/困る/にやり),template 和 source 骨比/mesh 密度差异放大,越不 robust。

**对策**:接受 per-morph 手写公式成本。简单 morph (あいうえお/まばたき) 几行 recipe,复杂情感类放弃或雕刻 (Path E)。

### 4. 探测目标能力再选方案

本 session 最早浪费回合:选 Purifier Inase 18 当 template,没注意到它是 **bone_morph** 不是 vertex_morph,'あ' 只 Jaw 4.8° 旋转,bake 出来 max 7.5mm。算法再对也传不出"大张嘴"。

**对策**:开工前先 probe 数据 — template vertex_morph 数量 ≥ 19、'あ' max offset ≥ 13mm,否则换 template。同理:上算法前先看 source rig 的 vertex group 数量,决定能做几条 morph。

### 5. "看起来对"的 close-up 可能是 artifact

Blender view_distance < 0.03 摄像机穿进 mesh 内部,看到暗色以为嘴张开,其实是阴影/inner-lip 翻起/mesh tear。

**对策**:front ortho, view_distance 0.08-0.12。必须看到"露牙/露舌"才算张嘴。

### 6. 零污染用 vg mask 天然保证

Path D 每条 recipe 只动显式列出的 vg。不在 vg 里的 vert offset = 0。这是"零污染"的 static guarantee,不需要运行时 check。

**对策**:能用 mask 静态保证的性质就不要靠测试验证。

### 7. 开发期 slider 漂移是隐形 bug

测试 ウィンク右 时如果没清 じと目 的 slider,视觉是两条 morph 叠加,容易误判 ウィンク右 有 bug。

**对策**:任何测试前先 reset 所有 mesh 所有非 basis slider。工具函数 `set_morph_synced` 封装这一行为,禁止直接 `key_block.value = 1.0`。

---

## Path D 成功的结构性条件

这些条件不满足时 Path D 也不 work:

1. **Source mesh 有语义 vertex group** — 如果 source 没有 `lip_upper` / `eyelid_upper_L` 这种 vg,公式写不出来。Inase XPS 和 DAZ G8 都满足,有些山寨 rig 可能不行。
2. **Vg 划分相对干净** — vg 之间 weight overlap 太多时 clamp 行为不可控。DAZ Inner+Outer+主 vg sum → clamp 这种就需要额外 tune 偏移量(见 S2 handoff)。
3. **19 条 MMD spec 能用 ≤ 10 类 vg 覆盖** — 如果某条 morph 需要 vg 语义 source 没提供,要么 fallback 到近似 vg,要么 skip。

---

## 不要再走的三条弯路

**(详细失败分析见 `morph_transfer_paths_2026_04_18.md`,这里只列 summary)**

1. **TPS + IDW + Jacobian** — upper lip offset 被 nose-region verts 稀释,撅嘴不张嘴。landmark-driven scalar 插值在强几何差异的脸上不够。
2. **Blender SurfaceDeform op** — Blender 3.6.21 bug,脚本调 bind 不 trigger 实际绑定,`is_bound` 永远 False。手写 BVH+barycentric 代替后仍因相邻 vert 法线微差→bind 错导致 mesh tear。
3. **Sumner per-tri affine** — 理论对,但 correspondence map 是 research-level 问题,300+ 行 numpy,本项目 ROI 不够。

---

## 交叉引用

- `morph_transfer_paths_2026_04_18.md` — A/B/C/D/E 五条路原理+已/未踩坑完整对比
- `morph_post_mortem_2026_04_18.md` — 前一个 session 三条早期路线 (clone_bone/bake_transfer/XPS recipe) 失败复盘
- `morph_session_handoff_2026_04_18.md` — Path D 实现细节 + Inase 具体 recipe + commit timeline
- `morph_generalization_architecture.md` — S1-S3 通用化后的多 rig 架构
- 代码:`experimental/morph_transfer_poc.py` + `experimental/morph_rigs.py`
