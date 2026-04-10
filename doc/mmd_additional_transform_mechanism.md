# MMD 付与親（additional transform）机制与 Blender 实现

本文档记录 MMD 的"付与親"概念，以及 mmd_tools 在 Blender 里用 dummy/shadow + 约束三层结构实现它的原理。看懂这个就能理解为什么 `腰キャンセル` 的付与親目标必须是 `腰` 而不是 `下半身`（leg jitter bug 的根因）。

---

## 一、MMD 的付与親概念

在 MMD 里，一个骨骼除了父子关系之外，还可以"跟随"另一个骨骼的旋转（或位移）。这个"跟随关系"就叫**付与親**（附加变换）。

```
骨骼 A（付与親目标）           骨骼 B（付与親接收方）
     旋转 θ          ───→           旋转 θ × influence
```

关键参数：

| 字段 | 含义 |
|---|---|
| `additional_transform_bone` | 付与親**目标**骨骼名 |
| `has_additional_rotation` | 是否跟随旋转 |
| `has_additional_location` | 是否跟随位移 |
| `additional_transform_influence` | 跟随系数 |

**influence** 的几个典型值：

| influence | 效果 |
|---|---|
| `+1.0` | 完全同步跟随 |
| `-1.0` | 反向（抵消） |
| `0.5` | 跟一半 |
| `0.0` | 不跟随 |

付与親和父子关系**独立**：一个骨骼可以 parent 指 A，付与親指 B；两者的旋转都会影响它。

---

## 二、典型用例：腰キャンセル

MMD 标准模型里，腿的链条是：

```
腰 → 下半身 → 腰キャンセル → 足 → ひざ → 足首
```

`下半身` 会跟着上半身的旋转一起动（比如弯腰），但**脚应该保持站立不动**。为此需要一个"取消"机制：

- `腰キャンセル` 的 **parent = 下半身**（所以会继承 下半身 的旋转）
- `腰キャンセル` 的 **付与親 = 腰** (`influence = -1.0`) —— 反向跟随 腰

数学上的效果：
- 腰 没有动画（`matrix_basis = identity`）
- 反向跟随 × 0 = 0 → 腰キャンセル 付与親贡献 = 0
- 腰キャンセル 的旋转最终由 parent 链决定 = 下半身 的旋转

看起来好像没起作用？关键在于：**在 PMX / MMD 运行时**，付与親的计算方式不是简单乘法，而是把目标的**局部旋转**叠加上来。当 下半身 有旋转时，`腰キャンセル` 被 parent 带过去一次，然后付与親用 -1 把 **parent 里那段带过去的旋转**抵消掉。

换句话说：**付与親指"祖父"就是在做"抵消父骨的旋转"**。这个技巧只在目标是祖父时成立。

> ⚠️ **绝对不能把付与親目标设成 parent 自己**。因为 parent 已经通过 parent 链把自己的旋转传给你了，再让付与親也从 parent 拿旋转，就变成**叠加两次**而不是抵消。这正是我们之前 leg jitter bug 的根因。

---

## 三、Blender 没有付与親，要怎么实现

Blender 的骨骼系统只有父子关系 + 约束（constraint）。没有内置的"按系数跟随另一根骨骼旋转"的 native 功能。mmd_tools 的解法是用**三层辅助骨骼**模拟：

```
dummy  (傀儡骨)        ──── 挂在付与親目标下面
  │                         通过父子关系继承目标的 world 旋转
  │ COPY_TRANSFORMS
  ↓
shadow (影子骨)         ──── 挂在另一个合适的位置
  │                         用 COPY_TRANSFORMS 把 dummy 的 pose 复制过来
  │ TRANSFORM
  ↓
X      (真正的骨骼)     ──── 用 TRANSFORM 约束按 influence 缩放 shadow 的旋转
```

### 3.1 三层各自的作用

**第一层：dummy —— 傀儡骨**

- parent = 付与親**目标**骨骼
- 无约束，仅靠父子关系继承目标的 world rotation
- 目的：把"目标骨骼当前的旋转"提取出来，变成 dummy 自己的 pose

**第二层：shadow —— 影子骨**

- parent = 选定的"翻译基准"（通常是 X 的祖先骨骼之一）
- 约束：`COPY_TRANSFORMS` → dummy（POSE 空间，REPLACE）
- 目的：把 dummy 的 pose 搬到 shadow 所在的坐标系。这一步是把 rotation 从"目标的局部空间"翻译到"X 相关的坐标系"，消除 frame-of-reference 差异

**第三层：X 本身**

- 约束：`TRANSFORM`（不是 COPY_ROTATION），source = shadow
- 目的：按 `influence` 系数缩放 shadow 的旋转后叠加到自己身上
- 为什么不用 `COPY_ROTATION`？因为它只支持"复制或加权平均"，不能做负数（`-1.0` 反向）。`TRANSFORM` 支持把 `(from_min, from_max)` 映射到 `(to_min, to_max)`，通过反转区间可以实现 `influence = -1`。

### 3.2 TRANSFORM 约束是怎么表达 influence 的

mmd_tools 用 from/to 区间映射表示系数：

```python
# influence = 1.0 （同向完全跟随）
tf.from_min_x_rot = -pi ; tf.from_max_x_rot = pi
tf.to_min_x_rot   = -pi ; tf.to_max_x_rot   = pi

# influence = -1.0 （反向）—— to 区间反过来
tf.from_min_x_rot = -pi ; tf.from_max_x_rot = pi
tf.to_min_x_rot   = +pi ; tf.to_max_x_rot   = -pi
```

Y、Z 轴同理。区间映射是一个线性插值，反转 `to` 就是乘 `-1`。

---

## 四、腰キャンセル 的实际设置（正确版）

```
                     rest pose 层级
                     ─────────────
                     
全ての親
  └── センター
       └── グルーブ
            └── 腰
                 ├── 下半身                     ← parent 链
                 │    └── 腰キャンセル.L        ← 目标骨骼
                 │         └── 足.L
                 │              └── …
                 │
                 └── _dummy_腰キャンセル.L      ← 挂在 腰 下（付与親目标）
                 
            └── _shadow_腰キャンセル.L          ← 挂在 グルーブ 下（和 腰 同父）
                 │
                 │ COPY_TRANSFORMS(target=_dummy_腰キャンセル.L, POSE→POSE)
```

腰キャンセル.L 上的 TRANSFORM 约束：
```python
tf.target     = armature
tf.subtarget  = "_shadow_腰キャンセル.L"
tf.target_space = 'LOCAL'
tf.owner_space  = 'LOCAL'
tf.map_from = 'ROTATION'; tf.map_to = 'ROTATION'
# from: [-π, π] → to: [+π, -π]（反转 = influence -1）
```

### 每一帧的求值

假设 VMD 给 `下半身` 写了 `(83°, 87°, 41°)` 旋转（某个大幅弯腰动作）：

1. VMD 应用到 下半身 → 下半身 pose 旋转 = (83°, 87°, 41°)
2. dummy parent = 腰（**没**旋转）→ dummy world rotation = identity
3. shadow 通过 COPY_TRANSFORMS 复制 dummy → shadow pose = identity
4. 腰キャンセル 通过 TRANSFORM 拿到 shadow 的旋转 = identity，反向 × -1 还是 identity
5. 腰キャンセル 自己没有被付与親影响 → local rotation 保持 identity
6. 腰キャンセル 继承 下半身 的 parent chain → world rotation 跟随 下半身
7. 足.L 是 腰キャンセル 的子 → **也跟随 下半身** 的旋转

咦？结果"脚跟着下半身动了"？这不正是我们不想要的吗？

**关键细节**：MMD 实际运行 VMD 时，`腰キャンセル` 也会收到一个**自己的** local 旋转，等于 `下半身 的 local 旋转 × -1`。这通过 TRANSFORM 约束把 `shadow 的 delta` 反向作用。但 shadow 取的是 _dummy_ 的 local 旋转（相对于 dummy parent = 腰）。因为 腰 没动，所以 dummy 的 local 旋转 = 下半身 对 腰 的相对 delta = 下半身 的 VMD 旋转。

所以整个等价于：

```
腰キャンセル.local_rotation = -(下半身.local_rotation)
```

于是 parent chain 中：
- 下半身 旋转 +θ
- 腰キャンセル 旋转 -θ
- 两者相乘抵消 → 足.L 的 world 旋转 = 不受 下半身 影响 ✓

这是付与親"祖父技巧"的数学本质：**target 必须是 parent 的 parent（或更上），才能拿到"parent 相对于 grandparent 的 delta 旋转"来做抵消**。

---

## 五、bug 复盘：付与親目标设错成 下半身 会怎样

之前代码 (`preset_operator.py:145` 旧版)：

```python
cancel_pb.mmd_bone.additional_transform_bone = "下半身"   # ← 错
cancel_pb.mmd_bone.additional_transform_influence = -1.0
```

导出 PMX 时 `腰キャンセル左.additionalTransform = (下半身_index, -1.0)`。

mmd_tools 重新导入 PMX 时，**按付与親目标创建 dummy/shadow 骨骼**：

```
_dummy_腰キャンセル.L parent = 下半身   ← 坏！应该是 腰
_shadow_腰キャンセル.L parent = 腰      ← 坏！应该是 グルーブ
```

### 求值流程（错误的）

VMD 给 下半身 写 `(83°, 87°, 41°)` 旋转：

1. 下半身 pose = (83°, 87°, 41°)
2. dummy parent = 下半身 → dummy **继承了** 下半身 的世界旋转 → dummy world = 下半身 world
3. shadow 的 parent = 腰（没动）。shadow COPY_TRANSFORMS POSE REPLACE 从 dummy 拿 → shadow 的 POSE space 被改成 dummy 的完整世界 pose
4. 但 shadow 自己 parent 是 腰，shadow 的 local rotation = inv(腰.world) @ dummy.world = 下半身 的 world（因为 腰 没动）
5. TRANSFORM 把 shadow.local 按 -1 作用到 腰キャンセル → 腰キャンセル 拿到 `(-83°, -87°, -41°)` 的 local rotation
6. 腰キャンセル 通过 parent chain 继承 下半身 的旋转 `(83°, 87°, 41°)`，又加自己的 `(-83°, -87°, -41°)`
7. 两者在 local space 叠加，但是**不是在同一个坐标系内的对齐运算** —— 因为 parent 是 下半身，local 里的反向操作是针对"相对于 下半身 的 delta"，而 shadow 抓取的是"相对于 腰"的 delta

数学上这两个参考系错位了。结果 腰キャンセル 的 world rotation 不是 identity，而是一个**放大且扭曲的错位旋转**。下半身 旋转越大，错位越严重。然后 足.L 通过 IK 计算膝盖位置，在每一帧收到一个剧烈跳变的 chain root → IK 输出也跟着跳 → **腿部狂抖**。

### 实测数据

永劫无间摇香 VMD（295 帧）的 足.L 单帧最大旋转变化：

| | 修复前 | 修复后 | 目标 c2 |
|---|---|---|---|
| 单帧最大旋转 | 166° | 15.2° | 15.3° |
| >30° 抖动帧数 | 176 | 0 | 0 |

一个字段的错误让 176 帧腿部剧烈抖动。

---

## 六、代码位置参考

- **创建 dummy/shadow 骨骼**：`operators/ik_operator.py` `OBJECT_OT_add_mmd_ik` 里的 SHADOW_DUMMY_DEFS / CANCEL_DEFS
- **设置 TRANSFORM 约束**：同上
- **设置 `mmd_bone.additional_transform_bone`**（PMX 导出元数据）：`operators/preset_operator.py` `OBJECT_OT_setup_pmx_attributes`（步骤 8）
- **付与親目标 map**：`ADDITIONAL_TRANSFORM_MAP`（D 骨部分）+ 腰キャンセル 专门分支

## 七、写新骨骼的付与親时的检查清单

1. 付与親 **影响的旋转是哪条路径**：`target_bone → 本骨骼`？
2. 如果 influence = -1（抵消）：target 必须是**祖父或更上**，不能是 parent 自己
3. 在 Blender 里对应的 dummy 会挂在 target 下 —— 如果 target 选错，dummy 会继承错误的父链
4. 导出 PMX 前跑 `setup_pmx_attributes`，之后验证 PMX 里 `additionalTransform` 字段指向正确的骨骼
5. 重导入 PMX，检查 `_dummy_<name>.parent.name` 和 `_shadow_<name>.parent.name` 是否符合预期

验证脚本片段：
```python
import bpy
arm = bpy.data.objects['Converted Test_arm']
for n in ['_dummy_腰キャンセル.L', '_shadow_腰キャンセル.L']:
    b = arm.data.bones.get(n)
    print(f'{n}: parent={b.parent.name if b and b.parent else None}')
# 预期:
# _dummy_腰キャンセル.L: parent=腰
# _shadow_腰キャンセル.L: parent=グルーブ
```

---

## 相关调查记录

- `doc/leg_jitter_investigation.md` —— 完整的 leg jitter 调查过程
- commit `428951c` —— 修复 腰キャンセル 付与親目标的 bug
