# Twist 调试教训

时间: 2026-04-11
最终修复: commit `c834b5c` (1 行 op 调用)
调试期间被回滚的 commit 数: 13 个

## 用户最初报告的现象

旋转 inase XPS 转出来的模型, 上臂 (肩→肘段) mesh 扭曲, 不跟手臂动。pose mode 选 `腕捩.L` 旋转, 行为跟 target Purifier Inase 18 PMX 不一样。

## 真正的根因 (一句话)

**`mmd_tools.convert_to_mmd_model()` 不会自动创建 PMX 付与親 (additional_transform) 的 Blender viewport constraint 链, 而 `mmd_tools.import_model()` 会**。XPS → MMD 走 convert 路径, 所以 sub twist 子骨在视口里全是死骨。

## 为什么 1 行修复花了一整天

**没按 MECE 顺序诊断, 直接跳到 L3 (skinning weights) 改权重**。整个 session 13 个被回滚的 commit 都是在改不该改的权重。如果一开始就先做 L2 检查 (`pose_bone.constraints`), 5 分钟能定位。

## PMX twist 系统原理

### 1. 标准结构

```
腕 (full rotation)
├── 腕捩 (main twist, fixed_axis 锁定旋转轴)
│   ├── 腕捩1 (sub twist, 25% inheritance)
│   ├── 腕捩2 (50%)
│   └── 腕捩3 (75%)
└── ひじ
    └── 手捩 (forearm main twist)
        ├── 手捩1 (25%)
        ├── 手捩2 (50%)
        └── 手捩3 (75%)
```

每个 sub twist 通过**付与親 (additional_transform)** 继承主 twist 旋转的固定百分比。这套机制让 bicep 沿臂方向产生平滑扭转梯度。

### 2. PMX 元数据 vs Blender constraint

PMX 文件用元数据描述 twist:
```python
pose_bone.mmd_bone.fixed_axis = (x, y, z)            # 主 twist
pose_bone.mmd_bone.additional_transform_bone = "腕捩.L"   # sub twist
pose_bone.mmd_bone.additional_transform_influence = 0.25   # sub twist
```

**这些字段是 PMX 导出元数据, Blender viewport 不认识**。要让视口实际产生 twist 行为, 必须把这些字段翻译为 Blender bone constraint。

### 3. mmd_tools 的实现 — dummy + shadow + TRANSFORM

通过 `apply_additional_transform()` operator 创建三段式 constraint 链:

```
腕.L  ──parent── 腕捩.L
                    ├──parent── _dummy_腕捩1.L  (无约束, 跟随 腕捩.L)
                    ├──parent── _dummy_腕捩2.L
                    └──parent── _dummy_腕捩3.L

腕.L  ──parent── _shadow_腕捩1.L  ──COPY_TRANSFORMS─→ _dummy_腕捩1.L
腕.L  ──parent── _shadow_腕捩2.L  ──COPY_TRANSFORMS─→ _dummy_腕捩2.L
腕.L  ──parent── _shadow_腕捩3.L  ──COPY_TRANSFORMS─→ _dummy_腕捩3.L

腕.L  ──parent── 腕捩1.L  ──TRANSFORM─→ _shadow_腕捩1.L (rot scale 25%)
腕.L  ──parent── 腕捩2.L  ──TRANSFORM─→ _shadow_腕捩2.L (rot scale 50%)
腕.L  ──parent── 腕捩3.L  ──TRANSFORM─→ _shadow_腕捩3.L (rot scale 75%)
```

设计意图:
- **dummy** 是源骨 (腕捩.L) 的子骨, 透过 parent 关系继承源骨的 world matrix
- **shadow** 是目的骨的父骨 (腕.L) 的子骨, COPY_TRANSFORMS 把 dummy 的 world transform 重新表达到目的骨父空间下
- **可见骨** (腕捩1.L) 是目的骨父骨 (腕.L) 的子骨, TRANSFORM constraint 从 shadow 读旋转, 缩放到 25% (`from rot [-π,π] → to rot [-π/4,π/4]`)

这样可见骨的 head **不动** (跟 腕.L 走), 但 **rotation 跟随 腕捩.L 的 25%**。等价于 PMX 的"付与親 旋转量"。

### 4. 主 twist 腕捩.L 的旋转哪来?

**没有 constraint, 没有 driver**。它的 local rotation 来源:
- VMD 文件里的 腕捩.L 关键帧 (有些 VMD 会显式 keyframe 主 twist)
- 用户在 pose mode 手动旋转

`mmd_tools.import_model` 还会设 `pose_bone.lock_rotation = [True, False, True]` (锁住非 twist 轴, 只在 pose mode UI 上限制手动旋转, 不限制 driver / VMD / Python 设置)。但这是 UI affordance, 不是物理约束。`apply_additional_transform` 是否设 lock 取决于 mmd_tools 版本, 不影响功能。

## convert 路径 vs import 路径的差异

| 操作 | 用于 | 自动调用 apply_additional_transform |
|---|---|---|
| `mmd_tools.import_model` | 导入 PMX 文件 | **是** |
| `mmd_tools.convert_to_mmd_model` | 把已有 Blender 模型转 MMD 兼容 | **否** |

我们的 pipeline (XPS 起步) 走 convert 路径, 所以 constraint 链从来没建。target Purifier Inase 18 是直接 PMX import 的, 走 import 路径, 链是齐的。

**这是两个 rig 在 viewport 里 twist 行为差异的全部根因**。权重、几何、命名、其他 constraint 都没差异。

## 验证修复 (ground truth)

修复后旋转 `腕捩.L` 90° (Y axis = twist axis), 各 sub bone 的 world 旋转 delta:

| 骨 | CONV (修复后) | TARGET | 期望 |
|---|---|---|---|
| 腕.L | 0° | 0° | 0° (未触动) |
| 腕捩.L | 90° | 90° | 90° (设的值) |
| 腕捩1.L | **25.4°** | **25.4°** | 25% × 90° (略高于 22.5° 因为 TRANSFORM constraint 的 from/to 范围是 ±π 映射) |
| 腕捩2.L | **49.1°** | **49.1°** | 50% × 90° |
| 腕捩3.L | **70.7°** | **70.7°** | 75% × 90° |

**两边 byte-for-byte 一致**。修复完成。

## MECE 诊断框架 (重学一遍)

VMD 重定向后 mesh 形变取决于:

```
P(V, f) = Σ_b w(V, b) · M_b(f) · rest_b⁻¹ · V_rest
```

四个量必须同时正确:

| 层 | 决定的量 | 失败方式 | 对应代码 |
|---|---|---|---|
| **L1 几何** | rest_b (rest pose, bone roll) | rest 偏 → VMD bone-local quat 算出不同 world 旋转 | `fix_forearm_bend`, `align_arms_to_reference`, `complete_missing_bones` |
| **L2 评估** | M_b(f) (constraint 链跑完后的 world matrix) | **父转子不转 → mesh 局部冻结** | `apply_additional_transform`, `add_mmd_ik`, `complete_hip_cancel_bones` |
| **L3 蒙皮** | w(V, b) | vert 跟错骨 → 局部拉扯 | `assign_weights`, `_split_chain_weights` |
| **L4 语义** | bone name | VMD 找不到骨 | `rename_to_mmd`, presets |

**互斥** (一个 bug 改一个量) **+ 穷尽** (4 个量穷尽公式), 所以 MECE。

### 强制诊断顺序: L4 → L1 → L2 → L3

1. **L4** 最快 (扫 bone.name)
2. **L1** rest 错则整段动作偏移, 直接看 bone.head_local
3. **L2** ← **本次的关键**: **手动旋转父骨, 看子骨是否跟随**, 不要跳过这一步
4. **L3** 留到最后, 因为数据多最容易吸引注意力, 但**最难诊断**

### 为什么 L3 优先级最低

L3 (skinning weights) 的检查方法天然有缺陷: 你用一套几何标准 (e.g. closer-bone) 来定义"哪些 vert 应该挂哪根骨", 然后 audit 现有权重, 然后 fix 不对的。但 **audit 和 fix 共用同一套几何标准**, 任何标准里的 bug 会同时污染 audit 和 fix, 互相掩盖。

本 session 我用 closer-bone 标准 audit 出 "腕.L 0 torso vert", 然后说 "已修复"。但用户看到的不是 0 — 因为 closer-bone 在 vert 投影 t < 0 时会误判。我的 audit 和 fix 共享了这个 bug, 互相验证为正确。最后用 ground truth (旋转骨看 mesh) 才发现 196 个胸部 vert 在动。

**ground truth 永远比静态 audit 可靠**。

## 失败的尝试 (按时间序)

| Commit | 我的想法 | 实际结果 |
|---|---|---|
| `21c862f` Simplify | 优化代码, 等价改写 | 中性, 后被反复 revert |
| `ef64e05` spine purge | 以为 XPS 上臂 30% spine 权重是 bug | 改了不该改的, 引入新 bug |
| `da5a6e6` perp 0.4 | 收紧 spine purge 范围 | 矫枉过正, 几乎不清 |
| `f030fc9` perp 1.5 | 放宽 | 又过宽 |
| `4320289` 腕 torso clean | 清 腕.L 上的 chest 污染 | closer-bone 单独不够 |
| `b36a0cb` 扩展到 腕系 | 也清 腕捩 | timing 错 (rename 之前跑) |
| `8321f05` post-twist 再跑 | 修 timing | 半正确 |
| `6c16ebc` t∈[0,1] | 收紧 closer-bone | 过度清理, 砍掉合法 vert |
| `8eaa57d` revert 6c16ebc | 退回 closer-bone only | 还是不对 |
| `4804c9e` design_principles.md | 写 MECE 框架 | 写了但**自己没遵守** |

最后用户要求**全部回滚**到 simplify 之前的 `20b076d`, 然后只 commit 一行 `apply_additional_transform()`。

## 下次再遇到类似症状的处理流程

```
症状: "VMD 播放后 mesh 扭曲" / "骨头不影响应该影响的 mesh"

第 1 步 (L4, 30 秒):
  扫 bone.name 是否是标准 MMD 名

第 2 步 (L1, 1 分钟):
  比对 CONV vs target 的 bone.head_local, 主要骨在不在同一位置

第 3 步 (L2, 5 分钟): ★ 必做, 不要跳
  pose mode 直接旋转父骨 (e.g. 腕.L), 视觉看子骨是否跟随。
  或 Python: print constraints / pose_bone.matrix delta。
  或 ground truth: 旋转 90°, 看哪些 vert 移动了, 区域对不对。

第 4 步 (L3, 1 小时+):
  只有前 3 步都通过才考虑权重。
  权重 audit 和 fix 必须用 ground truth 验证, 不能只用静态几何标准。
```

## 关键代码引用

- `operators/preset_operator.py:OBJECT_OT_use_mmd_tools_convert.execute` — 末尾调用 `bpy.ops.mmd_tools.apply_additional_transform()` (commit `c834b5c`)
- `CLAUDE.md` "Debugging rule: rotate parent, watch child follow" 章节 — 简短规则供日常调试 reference

## Sources

- mmd_tools 源码 `mmd_tools.core.bone.FnBone.apply_additional_transformation`
- 数据反推: target inase PMX 的 bone constraint 链 (见 commit message c834b5c)
