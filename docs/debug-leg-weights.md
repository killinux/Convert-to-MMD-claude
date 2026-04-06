# 大腿权重 & D骨权重问题排查指南

## 整体流程

```
5.2  unused 骨骼 → 主骨（左足/右足）
5.1  主骨（左足/右足） → D骨（足D.L/足D.R）
```

**顺序不能反**：5.2 必须在 5.1 之前执行，否则 D骨只有原始权重，大腿上部会缺失。

---

## 排查步骤

### 第一步：检查顶点数是否合理

在 Blender 系统控制台或通过 MCP 执行：

```python
import bpy
arm = bpy.data.objects.get('Armature')
meshes = [o for o in bpy.data.objects if o.type == 'MESH' and o.parent == arm]

for vg_name in ['左足', '右足', '足D.L', '足D.R', '下半身']:
    count = sum(
        1 for mesh in meshes
        for v in mesh.data.vertices
        for g in v.groups
        if mesh.vertex_groups.get(vg_name) and
           g.group == mesh.vertex_groups[vg_name].index and g.weight > 0.01
    )
    print(f"{vg_name}: {count}")
```

**正常预期**：
- `左足` / `右足`：5.1 执行后应为 0（权重已复制到 D骨）
- `足D.L` / `足D.R`：两侧数量应大致对称（差距不超过 20%）
- `下半身`：臀部+骨盆区域，数量合理（几百到一两千）

**异常信号**：
| 现象 | 可能原因 |
|------|---------|
| `足D.L` 远少于 `足D.R` | 某个 unused 骨骼没有合并到 `左足` |
| `足D.R` 数量异常大 | 臀部顶点误入了 `右足`，再被 5.1 复制到 `足D.R` |
| `下半身` 顶点很少 | 臀部顶点被错误分到腿骨 |

---

### 第二步：检查 unused 骨骼是否都处理了

```python
for b in arm.data.bones:
    if b.name.startswith('unused'):
        vcount = sum(
            1 for mesh in meshes
            for v in mesh.data.vertices
            for g in v.groups
            if mesh.vertex_groups.get(b.name) and
               g.group == mesh.vertex_groups[b.name].index and g.weight > 0.01
        )
        print(f"{b.name:<40} use_deform={b.use_deform}  verts={vcount}")
```

**正常预期**：所有 unused 骨骼的 `use_deform=False`，`verts=0`

**异常信号**：
- `use_deform=True` + `verts>0`：5.2 没有处理这根骨骼
- 查看 5.2 日志里的 `[SKIP]` 行，看原因

---

### 第三步：检查 Z 高度分布（臀部顶点是否误入腿骨）

```python
for vg_name in ['足D.R', '足D.L', '下半身']:
    zones = {'Z>1.07(臀)': 0, '1.0-1.07(髋关节)': 0, 'Z<1.0(大腿)': 0}
    for mesh in meshes:
        vg = mesh.vertex_groups.get(vg_name)
        if not vg: continue
        mat = mesh.matrix_world
        for v in mesh.data.vertices:
            for g in v.groups:
                if g.group == vg.index and g.weight > 0.01:
                    wz = (mat @ v.co).z
                    if wz > 1.07: zones['Z>1.07(臀)'] += 1
                    elif wz > 1.0: zones['1.0-1.07(髋关节)'] += 1
                    else: zones['Z<1.0(大腿)'] += 1
    print(f"\n{vg_name}: {zones}")
```

**正常预期**：
- `足D.R` / `足D.L` 的 `Z>1.07` 数量应该很少（接近 0）
- `下半身` 的 `Z>1.07` 应该是主要部分

---

## 常见问题和对应参数

| 问题 | 检查位置 | 对应参数/常量 |
|------|---------|-------------|
| unused 骨骼没被处理 | 5.2 日志 `[SKIP]` | `DISTANCE_THRESHOLD`（默认 0.15m）|
| 臀部顶点进了腿骨 | Z分布检查 | `HIP_TOLERANCE`（默认 0.05m）|
| 某骨骼应整体给指定目标 | `FORCED_TARGETS` | `pelvis → 下半身` |
| 某骨骼需要按区域拆分 | `SPLIT_BONES` | `xtra08, xtra08opp` |
| 超阈值骨骼需人工处理 | 5.2 日志末尾 `⚠️` 汇总 | 加入 `FORCED_TARGETS` 或手动绘制 |

---

## 关键常量速查（leg_operator.py 顶部）

```python
DISTANCE_THRESHOLD = 0.15   # 质心距阈值，超过则跳过自动处理
HIP_TOLERANCE      = 0.05   # 腿骨Z上限容差：顶点Z > 腿骨头Z+0.05 时排除腿骨
FORCED_TARGETS     = {...}   # 强制整骨转移：骨骼名含关键字 → 直接给指定目标
SPLIT_BONES        = {...}   # per-vertex拆分名单：跨越两个区域的骨骼才加这里
PHASE2_TARGETS     = {...}   # 5.2 可接收权重的候选骨骼白名单（主骨，不含D骨）
LOWER_BODY_TARGETS = {...}   # 5.4 迷路权重修复的候选骨骼白名单
```

---

## 本模型（XPS xna_lara_Inase）的 unused 骨骼对应关系

| unused 骨骼 | 处理方式 | 目标骨骼 |
|------------|---------|---------|
| `unused bip001 pelvis` | FORCED | `下半身` |
| `unused bip001 xtra08` | SPLIT (per-vertex) | `下半身`（臀）+ `左足`（大腿） |
| `unused bip001 xtra08opp` | SPLIT (per-vertex) | `下半身`（臀）+ `右足`（大腿） |
| `unused bip001 xtra04` | WHOLE | `左足` |
| `unused bip001 xtra02` | WHOLE | `右足` |
| `unused bip001 xtra07` | SKIP（超阈值，需人工） | 建议 `上半身3`（腋下支撑） |
| `unused bip001 xtra07pp` | SKIP（超阈值，需人工） | 建议 `上半身3`（腋下支撑） |
| `unused bip001 l/r foretwist` | WHOLE | 前臂骨骼 |
| `unused muscle_elbow_l/r` | WHOLE | 肘部骨骼 |
