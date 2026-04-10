# 腿部抖动/反转问题调查记录

**日期**: 2026-04-08（更新 2026-04-10）
**状态**: 部分解决 — 下半身动作能对应上目标了，但仍有抖动需继续调查

---

## 2026-04-10 更新

### 关键发现 1: VMD scale 必须匹配模型 scale

导出 PMX 时必须 `scale=12`（用户确认这是 MMD 标准尺度）。导出后再导入测试时：

- `import_model(scale=12)` — 把 PMX 还原到 12 倍尺寸（与目标 PMX 同尺度）
- `import_vmd(scale=1)` — **必须用 1，不能跟 export 的 12**

如果 VMD 用 scale=12 加载，IK 位移（足ＩＫ.location）会被乘 12，目标位置跑到几百米外，IK 解算彻底乱掉，看起来"下半身动作没对应上"。这是上次调查时被忽略的关键。

验证方法：在同一帧上对比 c2 / c3 的 `pose.bones['足ＩＫ.L'].location`，如果倍数关系明显（12x）就是 scale 问题。

### 关键发现 2: 足首 tail 修复生效

上次的 tail 指向 つま先 修复让 足首 朝向差从 **11.7° → 2.07°**。

### 关键发现 3: 腰骨骼朝向偏 20°

`operators/bone_operator.py:182` 中 腰 的定义：

```python
"腰": {"head": Vector((0, upper_body_head.y + 0.1, upper_body_head.z - 0.12)),
       "tail": Vector((0, upper_body_head.y, upper_body_head.z))}
```

方向 (0, -0.1, 0.12) 给出与 +Z 夹角 **39.8°**，目标 PMX 是 **19.4°**，差 20.4°。这个差异会通过 下半身→腰キャンセル→足 链传到腿部 rest pose，影响 IK 解。

### 关键发现 5: PMX 导出/导入破坏 dummy/shadow parent

**症状**: c3 腿部 IK 在 ~176 帧上剧烈抖动（单帧 50-160° 跳变），c2（同样的 VMD）只有 0 帧抖动。

**根因**: PMX 导出 → 重新导入后，`_dummy_腰キャンセル.L` 和 `_shadow_腰キャンセル.L` 的 parent 被改坏：

| | 原版 Armature（步骤6 创建后） | c2 (target PMX) | c3 (重导入的 PMX) |
|---|---|---|---|
| `_dummy_腰キャンセル.L` parent | 腰 ✓ | 腰 ✓ | **下半身 ✗** |
| `_shadow_腰キャンセル.L` parent | グルーブ ✓ | グルーブ ✓ | **腰 ✗** |

错误的 dummy parent 使 dummy 继承了 下半身 的旋转，shadow 复制后 TRANSFORM 约束把这个旋转作用到 腰キャンセル.L，导致整条腿在下半身大旋转的帧上完全乱套。

**测试**: 在原版 Armature（pre-export）上加载同一段 VMD，单帧 >30° 抖动只有 **4 帧**（c2 是 0 帧），重导入的 c3 是 **176 帧**。所以 PMX roundtrip 把抖动放大了 ~40 倍。

**问题源头**: mmd_tools 导入 PMX 时根据 PMX 的 付与親 元数据重建 dummy/shadow 骨骼，但选择的 parent 与原版不同。c2 的源 PMX 在导入时给出了正确的 parent，我们导出的 PMX 不行 — 可能是 步骤8 `setup_pmx_attributes` 中 `additional_transform_bone` 设置不对，或缺了某些 PMX 属性。

**下次继续方向**:
1. 比较 c2 PMX 文件和我们导出的 PMX 文件中 腰キャンセル 的 付与親/parent_bone 字段
2. 或者在 步骤6 之后强制再校正 dummy/shadow parent
3. 剩余的 4 帧抖动是真实的几何/IK 问题，需要单独查（可能是腿长比例 1.127 vs 1.034）

### 关键发现 4: 腿部骨骼位置在 armature space 偏移 0.3-0.6m

| 骨骼 | rot_diff | pos_diff |
|---|---|---|
| 腰 | 20.38° | 1.20m |
| 下半身 | 0° | 0.34m |
| 腰キャンセル.L | 0° | 0.47m |
| 足.L | 1.4° | 0.47m |
| ひざ.L | 1.1° | 0.52m |
| 足首.L | 2.8° | 0.59m |

c3 整条腿在 armature space 中比 c2 偏后 0.4m、偏上 0.26m。下次重点查 步骤2 中 上半身/下半身 head 的来源（`upper_body_head`）。

---


---

## 症状

执行 1-8 步 → mmd_tools 转换 → 导出 PMX → 重新导入 → 导入 VMD 动作后：
- 腿部在某些帧**抖动**（一抖一抖的）
- 部分帧腿**反向弯曲**
- 上半身动作基本正确

## 已排除的原因

| 检查项 | 结果 |
|--------|------|
| name_j 匹配 | OK — 步骤8 已设置 左/右 格式 |
| 付与親（D骨跟随） | OK — 步骤8 已设置 additional_transform |
| 骨骼层级（parent chain） | OK — 和目标 PMX 完全一致 |
| IK 约束 | OK — ひざ IK chain=2, 足首 IK chain=1, 和目标一致 |
| LIMIT_ROTATION | OK — ひざ X轴 0~180°, 和目标一致 |
| IK limit (use_ik_limit) | OK — 和目标一致 |
| bone roll | OK — 全部 0°, 和目标一致 |
| センター方向 | OK — 已修复为 head.z > tail.z (朝下) |
| 模型朝向 | OK — 面朝 -Y (MMD 标准) |
| mmd_ik_toggle | OK — 全程 IK=ON, 无切换 |
| VMD quaternion 数据 | OK — C3 和 C2 的 pose quaternion 完全一致 |

## 确认的根因

### 1. 骨骼 rest pose 朝向差异

足首.L 的 rest pose matrix 和目标 PMX 差 **11.7°**。已修复 tail 指向つま先，但重新导入后需要再验证差异是否减小。

```
骨骼         朝向差异
足.L         -1.3° (minor)
ひざ.L        1.0° (minor)
足首.L       -11.7° ← 已修复 tail 指向，待验证
腕.L        -13.1° (手臂，另外的问题)
ひじ.L       -16.7° (手臂，另外的问题)
センター       0.0° (OK)
上半身         0.0° (OK)
下半身         0.0° (OK)
```

### 2. 骨骼比例差异

```
           上腿长    下腿长    总长     比例(上/下)
C3(XPS):   5.557    4.930    10.486   1.127
C2(目标):  5.171    5.002    10.172   1.034
```

XPS 模型上腿偏长、下腿偏短。同一个 IK 目标位置在不同比例的骨架上会产生不同的膝盖角度。

### 3. FK 验证

禁用 IK 约束后只用 FK 旋转，腿部姿势**完全错乱**（膝盖飞出、腿折叠）。说明 VMD 的 FK 旋转值也是为目标 PMX 的 rest pose 朝向设计的，直接用在我们的骨架上效果不对。

**结论**: 这不是插件 bug，而是 **XPS 模型骨骼和标准 MMD 模型骨骼的 rest pose 朝向/比例差异**，属于动作重定向（retarget）问题。

## 下次继续的方向

### 方向 A: 减小 rest pose 差异（推荐先试）

调整步骤2中骨骼的 head/tail 位置，让 rest pose 的 matrix_local 尽量接近目标 PMX。重点关注：

1. **足首.L/R**: tail 已改为指向つま先，需验证差异是否从 11.7° 减小
2. **腕.L/R 和 ひじ.L/R**: 13°-17° 的差异，可能需要调整 tail 位置

验证方法：
```python
# 在 Blender console 运行
import bpy
from math import degrees
c3 = bpy.data.objects['408-1_arm']  # 重新导入的 PMX
c2 = bpy.data.objects['Purifier Inase 18 None_arm']  # 目标
for name in ['足.L', 'ひざ.L', '足首.L', '腕.L', 'ひじ.L']:
    diff = c2.data.bones[name].matrix_local.to_3x3().inverted() @ c3.data.bones[name].matrix_local.to_3x3()
    d = [degrees(a) for a in diff.to_euler()]
    print(f'{name}: ({d[0]:.1f}°, {d[1]:.1f}°, {d[2]:.1f}°)')
```

### 方向 B: VMD retarget

导入 VMD 时根据新骨架的比例重新计算 IK 位置和 FK 旋转。这需要：
1. 读取 VMD 原始数据
2. 将 IK 位置按照新骨架比例缩放
3. 将 FK 旋转按照 rest pose 差异补偿

复杂度较高，但效果最好。

### 方向 C: 匹配目标骨骼位置

在步骤2中，不使用 XPS 的原始骨骼位置，而是把关节位置调整为和目标 PMX 相同的比例。代价是 mesh 变形可能不精确（因为关节位置变了但 mesh 顶点没变）。

## 场景结构参考

```
Collection 2 — 目标 PMX (Purifier Inase 18 None_arm, 263 bones) — VMD 效果正确
Collection 3 — 转换后导入的 PMX (408-1_arm, 163 bones) — VMD 腿部抖动
Collection 4 (xps) — 原始 XPS (Armature, 109 bones)
```

## 关键代码位置

- 步骤2 骨骼位置定义: `operators/bone_operator.py` → `complete_missing_bones` → `bone_properties` 和 `limb_defs`
- 步骤8 PMX 属性: `operators/preset_operator.py` → `OBJECT_OT_setup_pmx_attributes`
- IK 创建: `operators/ik_operator.py` → `OBJECT_OT_add_ik`
- D骨: `operators/leg_operator.py` → `OBJECT_OT_complete_d_bones`
