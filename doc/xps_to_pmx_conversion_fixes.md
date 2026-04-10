# XPS → PMX 转换关键修复记录

本文档汇总 2026-04-10 一整天调查并修复的三个核心问题：
1. 腿部 IK 抖动（176 帧严重跳变）
2. 头发权重丢失 + 胯部顶点权重接近零
3. 胯部/腿交界处变形不自然

每个修复都附带**原理**（为什么会出问题）和**思路**（为什么这样改）。

---

## 一、核心原则：最小干预 XPS 权重

**经验教训**：XPS 游戏模型的骨骼、权重、层级在 XPS 原生播放动画时是**正确的**。我们的转换流程越"聪明"（越多 merge/transfer/smooth），丢的信息越多。最好的策略是：**只做结构性改名和补齐，尽量不碰权重数据**。

---

## 二、Bug 1: 腿部 IK 抖动（commit `428951c`）

### 症状

永劫无间摇香 VMD 在转换后的 PMX 上播放时，腿部在 176 个帧上剧烈跳变（单帧最大旋转 166°）。c2（目标 PMX）同一段动画是 0 帧抖动。

### 原理

MMD 的 **付与親** (additional transform) 机制：一个骨骼可以"额外跟随"另一个骨骼的旋转，系数可为 `-1.0`（反向）实现"取消"。详见 `doc/mmd_additional_transform_mechanism.md`。

`腰キャンセル` 是 MMD 标准模型里的"腰取消"骨骼，parent 是 `下半身`，付与親目标应该是 `腰`（祖父），influence `-1.0`。

插件原本的代码把付与親目标设成了 `下半身`（自己的 parent）：

```python
cancel_pb.mmd_bone.additional_transform_bone = "下半身"  # ← 错
```

这个设置在 PMX 导出时是合法的，但 **mmd_tools 在 PMX 重新导入时**，会按付与親目标创建 dummy bone，parent = 付与親目标。设成 `下半身` → dummy parent = `下半身`：

```
_dummy_腰キャンセル.L parent = 下半身   ← 继承 下半身 的大旋转!
_shadow_腰キャンセル.L parent = 腰       ← 坐标系参考错位
```

求值流程：
1. VMD 给 `下半身` 写大旋转（比如 83°）
2. dummy 挂在 `下半身` 下 → dummy 继承这 83°
3. shadow 用 `COPY_TRANSFORMS` 复制 dummy 的 pose
4. `腰キャンセル` 上的 `TRANSFORM` 约束把 shadow 的旋转 × `-1` 作用到自己
5. 但 `腰キャンセル` 本身已经是 `下半身` 的子 —— 于是既继承了 `下半身` 的 83°，又被反向作用一次
6. 两个旋转在不同的参考系里**叠加**而不是**抵消**，产生几何上没有意义的扭转
7. 腿部 IK chain 的 root 在每一帧收到剧烈跳变的值 → IK 解算器跟着跳

### 思路

修复一个字段：把付与親目标改成**祖父** `腰`。因为 `腰` 通常没有动画 (`matrix_basis = identity`)，反向乘 0 还是 0 —— 付与親贡献为恒等，`腰キャンセル` 就只受 parent 链（`下半身`）的自然继承影响。这刚好等价于"自然跟随 parent"的行为，没有叠加。

```python
cancel_pb.mmd_bone.additional_transform_bone = "腰"  # ← 对
```

### 效果

| | 修复前 | 修复后 |
|---|---|---|
| `足.L` 单帧最大旋转 | 166° | 15.2° |
| `>30°` 抖动帧数 | 176 | 0 |
| 对比 c2（目标） | ❌ | ✓ |

一行代码改动，彻底解决。

---

## 三、Bug 2: 胯部 883 顶点接近零权重 + 头发 3362 顶点挂在根骨（commit `70f6afb`）

### Bug 2a - 胯部权重

#### 症状

Body mesh 有 883 个顶点总权重 `< 0.5`，其中 33 个 `< 0.01`（接近零权重）。这些顶点都集中在胯部区域（Z≈1.0m），表现为胯部"权重不协调"。

#### 原理

Phase 5 "Lower Body Cleanup" 的原逻辑：

```python
# 只要有 D 骨权重, 就整个删掉 下半身 权重
if any(g.group in d_vg_indices and g.weight > 0 for g in v.groups):
    verts_to_remove.append(v.index)
```

这是一个**无阈值判断**：顶点只要有**任何**量的 D 骨权重（哪怕是 0.001 的 stray 权重），就把 `下半身` 的权重完全删掉。

典型受害顶点的权重：
```
{'下半身': 0.969, '足D.L': 0.031}
```

这是一个**主要挂在 下半身**（0.969）的顶点，只有极小的 `足D.L` 残余（0.031，来自 XPS 的 `leg left thigh` 绘制时的边缘外溢）。原意图是"删掉 足D.L 0.031"，实际代码删掉了 `下半身 0.969`。

删掉后顶点只剩 `足D.L: 0.031`，total weight 0.031 —— 基本上这个顶点不受任何骨骼控制（接近静止）。

#### 思路

加一个阈值：只有当 D 骨权重**占主导**时才认为该顶点"真正属于腿部"，才删 `下半身`。阈值取 `D 权重 >= 0.1` 或 `D 权重 > 下半身 权重`。

```python
D_DOMINANT_MIN = 0.1
for v in mesh.data.vertices:
    lower_w = next((g.weight for g in v.groups if g.group == lower_vg.index), 0.0)
    if lower_w <= 0:
        continue
    max_d_w = max((g.weight for g in v.groups if g.group in d_vg_indices), default=0.0)
    if max_d_w >= D_DOMINANT_MIN or max_d_w > lower_w:
        verts_to_remove.append(v.index)
```

### Bug 2b - 头发

#### 症状

头发 mesh (`25_0000`) 有 **3362 个顶点** 挂在 `全ての親`（根骨）上，总权重 1713。这些顶点的物理位置在头顶/发梢区域。`全ての親` 是非 deform 控制骨，不会跟任何 VMD 动画移动 → 这部分头发完全静止不动。

#### 原理

XPS 的根骨叫 `root ground`，在 step 1 被重命名为 `全ての親`。XPS 的原作者给某些头发顶点挂了 `root ground` 权重（可能是"不要跟头动的发夹"或者就是 rigging 偷懒）。重命名后这些权重挂到 `全ての親` 上。

插件的 step 5 只处理 `unused *` 前缀的 unused 骨骼。`全ての親` 不是 unused 前缀，所以完全被跳过。这些权重就被遗留在根骨上，整个动画里完全静止。

#### 思路

新增 **Phase 6**：检查所有 mesh，把 `全ての親` 上的权重按顶点空间位置**迁移到最近的 deform 骨骼**。对头发来说，最近的 deform 骨骼是头顶的 `頭/首1/head hair *` 等，自然就跟着头动了。

```python
for v in mesh.data.vertices:
    src_w = vg_weight(v, '全ての親')
    if src_w <= 0.001: continue
    # 找最近的 deform 骨骼
    best_bone = find_nearest_deform_bone(v.co)
    # 把权重迁移过去
    dst_vg.add([v.index], src_w, 'REPLACE')
    root_vg.remove([v.index])
```

### 效果

| 项 | 修复前 | 修复后 |
|---|---|---|
| 胯部 unweighted 顶点 (<0.01) | 33 | **0** |
| 胯部低权重顶点 (<0.5) | 883 | 591* |
| 头发 `全ての親` 顶点 | 3362 | **0** |

*剩余的 591 是正常的多骨混合权重（total <1 是 XPS 源就有的，PMX 导出时自动归一化）。

---

## 四、Bug 3: 胯部变形不自然（commit `6edf58a`）

### 症状

即使前两个 bug 修好后，胯部和腿交界处在动画时仍然看起来不自然，有剪切感。用户反馈："改得更乱了"。

### 调查过程（走过的弯路）

先试了"smooth blend"方案：在髋关节附近手写 smoothstep 空间距离权重混合。结果**更乱** —— 大腿内侧和外侧的过渡不一致，用户拒绝。

然后试 Blender 内置 `vertex_group_smooth`（基于 mesh 拓扑的邻居平均），效果好一些，用户说"好多了"。但这只是让权重模糊化，没解决根本问题。

直到检查 XPS 原始骨骼才找到真正原因。

### 原理（关键发现）

检查 `unused bip001 xtra04` 骨骼的位置：

```
足.L    : head=(0.085, -0.03, 1.02) → tail=(0.083, -0.032, 0.575)   ↓ 指下到膝盖
xtra04  : head=(0.085, -0.03, 1.02) → tail=(0.087, -0.028, 1.464)   ↑ 指上到腹部
```

**`unused bip001 xtra04` 是指向上方的！** 它是 XPS 专门为胯部/大腿内侧做的辅助变形骨，轴方向和 `足.L` **相反**。而且 xtra04 承载了胯部区域 **90% 的权重** (0.898)。

插件的 step 5.1 中 `unused bip001 xtra04` 被按质心距离 merge 到最近的骨骼 `足.L`：

```
[WHOLE] unused bip001 xtra04 -> 足.L (853v) [质心距0.006m]
```

**质心距离只有 0.6cm 所以启发式把它整体 merge 进去**。但 xtra04 的**轴方向**和 足.L 完全相反：
- XPS 里这些顶点绕 xtra04 的"向上轴"旋转（胯部屈曲方向）
- merge 到 足.L 后，顶点绕 足.L 的"向下轴"旋转 —— 方向刚好**反了**

当腿做动作（膝盖抬起/踢腿），旋转轴错反让胯部顶点往"错误"的方向变形，产生剪切感。

类似的辅助骨还有：
- `xtra02` - 右大腿对称版
- `xtra07/07pp` - 肩部辅助
- `xtra08/08opp` - 臀部辅助
- `muscle_elbow_l/r` - 肘部辅助
- `foretwist*` - 手臂扭转

这些都是 XPS rigger 为不同关节的特殊变形加的辅助骨，有自己独特的几何意义。**merge 掉任何一个都丢失了它的轴信息**。

### 思路

**最好的处理就是不处理**。这些骨骼在 XPS 里：
1. 有正确的 parent（大多挂在对应主骨下，如 xtra04 parent = `leg left thigh`）
2. Parent 在 step 1 已经 rename 成了 MMD 标准名（thigh → 足.L）
3. 所以 xtra04 现在的 parent 是 `足.L`

它们会自动通过父链继承 `足.L` 的旋转。它们自己的 local rotation = identity（VMD 不动它），但它们的 **head/tail 位置和轴方向**保持 XPS 原样 → 顶点绕正确的轴旋转 → 变形和 XPS 原生一致。

**代码改动**：

1. **step 1** 自动 rename `unused bip001 pelvis` → `下半身`，让胯部权重原地保留到 MMD 标准骨骼上：

```python
if not getattr(scene, "lower_body_bone", None):
    pelvis_bone = obj.pose.bones.get("unused bip001 pelvis")
    if pelvis_bone and not obj.pose.bones.get("下半身"):
        pelvis_bone.name = "下半身"
```

2. **step 5.1** 新增保留清单，匹配的 unused 辅助骨完全跳过 merge：

```python
PRESERVE_HELPER_KEYWORDS = (
    "xtra04", "xtra02",
    "xtra07", "xtra07pp",
    "xtra08", "xtra08opp",
    "muscle_elbow",
    "foretwist",
)

preserved_bones = [
    b.name for b in obj.data.bones
    if b.name.startswith("unused ")
    and any(kw in b.name.lower() for kw in PRESERVE_HELPER_KEYWORDS)
]
# 这些骨骼权重不动, 作为额外 deform bone 保留到 PMX
```

3. **移除 Phase 7** `vertex_group_smooth`：之前是 workaround，现在根本解决就不需要了。

### 效果

用户反馈："现在好像很好，就要这个版本"

副作用：PMX 里多了 ~10 个 "unused bip001 xxx" 命名的辅助骨。这些骨骼在 MMD 播放器里是**正常的 deform 骨骼**，只是命名不标准，不影响使用。也可以以后考虑 rename 成更规范的名字。

---

## 五、经验教训

### 5.1 MMD 的 付与親 不是"显式坐标运算"，是"通过 dummy/shadow 的隐式机制"

mmd_tools 把 PMX 的 付与親 解析成 Blender 的 dummy + shadow + TRANSFORM 三层约束（详见 `doc/mmd_additional_transform_mechanism.md`）。这意味着：

- **付与親目标的选择会影响 dummy bone 的 parent**
- **dummy bone 的 parent 决定它继承什么旋转**
- **如果 dummy 挂错父，整个链条全乱**

所以设置 付与親 时不能只想"数学上是否等价"，要想"mmd_tools 导入后生成的 dummy chain 是否合理"。

### 5.2 不要无条件地信任 heuristic 的"最近距离 merge"

Step 5.1 用"质心到骨骼线段的最短距离"找 merge 目标。对位置相近的骨骼这个 heuristic 可能判断对，但完全忽略了**骨骼轴方向**。两个 head 重合、tail 相反的骨骼距离为零，但它们的变形效果完全不同。

**教训**：涉及权重迁移的 heuristic 要同时考虑位置和方向，或者直接让用户通过白名单控制。或者最好 —— **不 merge**。

### 5.3 "智能"转换往往不如"朴素"转换

- v1 (smooth blend): 我基于几何分析手写了一套 smoothstep 混合 → 更乱
- v2 (preserve helpers): 不动权重，只保留原骨骼 → 用户满意

每加一层"聪明"的处理，就多一层可能出错的地方。**能保留的就保留，能跳过的就跳过**，这是通用 XPS → PMX 转换的正确方向。

### 5.4 测试流程中的 scale 陷阱

`mmd_tools` 的 export/import scale 参数行为：
- `export_pmx(scale=12)` → PMX 文件坐标被除以 12 保存
- `import_model(scale=1)` → Blender 坐标 = PMX 值 × 1
- `import_vmd(scale=1)` → VMD 里的位移 × 1

如果导出用 12 导入用 12，模型会变 12 倍（文件 × 导入倍数）。如果 VMD 导入 scale 和模型 scale 不匹配，IK 目标位置被错误缩放，IK 目标跑到几百米外 → 整个腿部动画彻底乱（这个陷阱浪费了约 30 分钟调试时间）。

**规则**：
- 导出 PMX 用 `scale=12`（MMD 标准尺度）
- 重新导入这个 PMX 用 `scale=1`（因为文件已经是 12x 了）
- 加载 VMD 用 `scale=1`（匹配模型的实际 Blender 坐标）

---

## 六、验证清单

下一次调完整流程后做这几项检查：

```python
# 1. 付与親目标正确
pb = arm.pose.bones['腰キャンセル.L']
assert pb.mmd_bone.additional_transform_bone == '腰', \
    f"expected 腰, got {pb.mmd_bone.additional_transform_bone}"

# 2. 导出后 dummy parent 正确
m = pmx_load(pmx_path)
dummy = next(b for b in m.bones if b.name == '左_dummy_腰キャンセル')
assert m.bones[dummy.parent].name == '腰'

# 3. 没有 unweighted 顶点
for v in body_mesh.data.vertices:
    assert sum(g.weight for g in v.groups) >= 0.01

# 4. 全ての親 上没有 mesh 权重
root_vg = mesh.vertex_groups.get('全ての親')
if root_vg:
    assert sum(1 for v in mesh.data.vertices
               if any(g.group == root_vg.index and g.weight > 0.001 for g in v.groups)) == 0

# 5. XPS 辅助骨被保留
preserved = [b.name for b in arm.data.bones
             if b.name.startswith('unused ')
             and any(kw in b.name.lower() for kw in ['xtra04','xtra02','muscle_elbow'])]
assert len(preserved) > 0, "expected XPS helper bones to be preserved"

# 6. VMD 腿部抖动 <= baseline
# 采样 1-295 帧, 单帧 足.L 世界旋转差应 <= 20°
```

---

## 七、相关 commits

| Commit | 改动 |
|---|---|
| `428951c` | 修 腰キャンセル 付与親目标 (下半身 → 腰) |
| `f166155` | 文档 `mmd_additional_transform_mechanism.md` |
| `70f6afb` | Phase 5 阈值 + 新增 Phase 6 全ての親 迁移 |
| `64982cd` | （中途实验）Phase 7 vertex_group_smooth — 后续移除 |
| `6edf58a` | PRESERVE_HELPER_KEYWORDS + 移除 Phase 7 |

---

## 八、相关文档

- `doc/mmd_additional_transform_mechanism.md` — 付与親 机制详解
- `doc/leg_jitter_investigation.md` — 腿部抖动完整调查过程
- `doc/dev_guide_2026-04-08.md` — 1-8 步流程总览
