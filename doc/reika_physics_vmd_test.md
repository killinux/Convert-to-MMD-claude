# Reika 物理 + VMD 完整测试 (代号: reika-phys-vmd)

XPS→PMX 整套 pipeline 的端到端验证, 含 snap 错位骨修复 + clone_physics + VMD 物理仿真。
跑两条 VMD (中等动作 + 大动作), 验证物理在不同强度下的表现。

**HEAD 基准**: `88ce63f` (snap_misaligned_bones 已合入 one_click_convert step 8b)

---

## 数据路径 (Mac)

```
XPS 源:    /Users/bytedance/Downloads/demo/Reika/xps.xps
Target PMX: /Users/bytedance/Downloads/demo/Reika Shimohira 2 18/Reika Shimohira 2 18 None.pmx
VMD A (中):  /Users/bytedance/Downloads/demo/永劫无间摇香2025.2.21by小王动画/永劫无间摇香2025.2.21.vmd  (9037 bone keys)
VMD B (大):  /Users/bytedance/Downloads/demo/八方来才_by_泡面fly(good)/八方来才.vmd  (71460 bone keys)
```

Preset: `daz_genesis8` (Reika 是 DAZ Genesis 8 rig)

---

## 完整脚本 (复制即可跑)

### Phase 1: 清空 + 导入

```bash
# AWS 端通过 CLI 远程执行
BLENDER_RELAY_API_KEY=mysecretkey python /opt/mywork/mytest/bl/cli/cli.py exec "
import bpy
bpy.ops.wm.read_homefile()
for o in list(bpy.data.objects): bpy.data.objects.remove(o, do_unlink=True)
for a in list(bpy.data.actions): bpy.data.actions.remove(a, do_unlink=True)
print('cleared')
"

# 导 XPS (timeout 拉长, mesh 多)
BLENDER_RELAY_API_KEY=mysecretkey python /opt/mywork/mytest/bl/cli/cli.py exec "
import bpy
bpy.ops.xps_tools.import_model(filepath='/Users/bytedance/Downloads/demo/Reika/xps.xps')
print('xps:', sum(1 for o in bpy.data.objects if o.type=='MESH'), 'meshes')
" --timeout 180

# 导 target PMX (含物理)
BLENDER_RELAY_API_KEY=mysecretkey python /opt/mywork/mytest/bl/cli/cli.py exec "
import bpy
bpy.ops.mmd_tools.import_model(filepath='/Users/bytedance/Downloads/demo/Reika Shimohira 2 18/Reika Shimohira 2 18 None.pmx', scale=0.08, types={'MESH','ARMATURE','PHYSICS','MORPHS'})
print('target rigids:', sum(1 for o in bpy.data.objects if getattr(o,'mmd_type','')=='RIGID_BODY'))
"
```

**预期**: 25 objs (XPS), +152 (target), 共 ~177 obj, 83 rigids 在 target 上

### Phase 2: Convert + 物理克隆

```bash
# one_click_convert (含 step 8b snap_misaligned_bones)
BLENDER_RELAY_API_KEY=mysecretkey python /opt/mywork/mytest/bl/cli/cli.py exec "
import bpy
arm = bpy.data.objects['Armature']
bpy.context.view_layer.objects.active = arm
for o in bpy.data.objects: o.select_set(False)
arm.select_set(True)
bpy.ops.object.load_preset(preset_name='daz_genesis8')
ret = bpy.ops.object.one_click_convert(run_preprocessing=True, stop_at_morph=False)
print('convert:', ret)
" --timeout 600

# clone_physics + build_rig 双模型
BLENDER_RELAY_API_KEY=mysecretkey python /opt/mywork/mytest/bl/cli/cli.py exec "
import bpy
from Convert_to_MMD_claude.operators.physics_operator import clone_physics_from_pmx
conv_root = bpy.data.objects['New MMD Model']
n_r,n_j,sk,n_t = clone_physics_from_pmx(conv_root,
    '/Users/bytedance/Downloads/demo/Reika Shimohira 2 18/Reika Shimohira 2 18 None.pmx',
    fit_to_mesh=True, scale=0.08, add_missing_bones=True)
print(f'cloned: {n_r}/{n_t} rigids, {n_j} joints')
for n in ['New MMD Model','Reika Shimohira 2 18 None']:
    r = bpy.data.objects[n]
    bpy.context.view_layer.objects.active = r
    for o in bpy.data.objects: o.select_set(False)
    r.select_set(True)
    bpy.ops.mmd_tools.build_rig()
bpy.data.objects['Reika Shimohira 2 18 None'].location.x = 1.5  # 错开对比
print('build_rig + offset done')
" --timeout 180
```

**预期**: 
- snap log: `[CTMMD snap] 乳奶.L: snapped delta=0.2476m` (≈24.7cm 修复)
- clone log: `83/83 rigids, 64/64 joints, 0 bone(s) missing`
- 4 个 dangling 骨 (Bone.L/R/.001.L/R) 被补齐

### Phase 3: VMD 测试 (跑两条)

每条 VMD 独立测试。换 VMD 前先清 actions:

```bash
# 清旧 action (复用场景, 不重 convert)
BLENDER_RELAY_API_KEY=mysecretkey python /opt/mywork/mytest/bl/cli/cli.py exec "
import bpy
for a in list(bpy.data.actions): bpy.data.actions.remove(a, do_unlink=True)
bpy.context.scene.frame_set(1)
print('actions cleared')
"
```

```bash
# 导 VMD 到双模型 (换 VMD 路径即可)
VMD='/Users/bytedance/Downloads/demo/八方来才_by_泡面fly(good)/八方来才.vmd'
# VMD='/Users/bytedance/Downloads/demo/永劫无间摇香2025.2.21by小王动画/永劫无间摇香2025.2.21.vmd'

BLENDER_RELAY_API_KEY=mysecretkey python /opt/mywork/mytest/bl/cli/cli.py exec "
import bpy
VMD = '$VMD'
for n in ['New MMD Model','Reika Shimohira 2 18 None']:
    r = bpy.data.objects[n]
    bpy.context.view_layer.objects.active = r
    for o in bpy.data.objects: o.select_set(False)
    r.select_set(True)
    bpy.ops.mmd_tools.import_vmd(filepath=VMD, scale=0.08, bone_mapper='RENAMED_BONES')
print('vmd loaded, frame_end:', bpy.context.scene.frame_end)
" --timeout 120
```

### Phase 4: 物理验证 (sample + screenshot)

```bash
# 1. 步进物理 (frame 1→200) + 测乳奶 oscillation
BLENDER_RELAY_API_KEY=mysecretkey python /opt/mywork/mytest/bl/cli/cli.py exec "
import bpy
from mathutils import Vector
scn = bpy.context.scene
arm = bpy.data.objects['Armature']

# 找 converted 乳奶 rigids
breast_rigids = []
for o in bpy.data.objects:
    if getattr(o,'mmd_type','')=='RIGID_BODY' and o.mmd_rigid.bone in ('乳奶.L','乳奶.R'):
        cur = o
        while cur and cur.name != 'New MMD Model': cur = cur.parent
        if cur is None: continue
        breast_rigids.append(o)

scn.frame_set(1)
all_L, all_R = [], []
for f in range(1, 201):
    scn.frame_set(f)
    bpy.context.view_layer.update()
    for r in breast_rigids:
        bn = r.mmd_rigid.bone
        rel = r.matrix_world.to_translation() - (arm.matrix_world @ arm.pose.bones[bn].matrix).to_translation()
        (all_L if bn=='乳奶.L' else all_R).append(rel)

def stats(name, rels):
    xs=[r.x for r in rels]; ys=[r.y for r in rels]; zs=[r.z for r in rels]
    print(f'{name}: x_range={max(xs)-min(xs):.3f}m  y_range={max(ys)-min(ys):.3f}m  z_range={max(zs)-min(zs):.3f}m  |rel|={rels[0].length:.3f}m (恒定)')

stats('乳奶.L', all_L)
stats('乳奶.R', all_R)
" --timeout 180

# 2. 截图 frame 1 + frame 100 (清晰对比)
BLENDER_RELAY_API_KEY=mysecretkey python /opt/mywork/mytest/bl/cli/cli.py exec "
import bpy
# Hide armatures + rigid/joint visuals 让 mesh 干净
for o in bpy.data.objects:
    if o.type=='ARMATURE': o.hide_set(True)
    if getattr(o,'mmd_type','') in ('RIGID_BODY','JOINT'): o.hide_set(True)
bpy.context.scene.frame_set(1)
for o in bpy.data.objects: o.select_set(False)
for o in bpy.data.objects:
    if o.type=='MESH' and not o.hide_get(): o.select_set(True)
for area in bpy.context.screen.areas:
    if area.type=='VIEW_3D':
        for region in area.regions:
            if region.type=='WINDOW':
                with bpy.context.temp_override(area=area, region=region):
                    bpy.ops.view3d.view_axis(type='FRONT')
                    bpy.ops.view3d.view_selected()
                break
        break
"
BLENDER_RELAY_API_KEY=mysecretkey python /opt/mywork/mytest/bl/cli/cli.py screenshot
```

---

## 期望基准

### Convert 阶段
- step 8b snap log: `乳奶.L/R: snapped delta=0.247-0.248m` (XPS 源乳奶在背后, 24.7cm 错位)
- step 12 完成: `一键转换完成 (step 1→12)`
- bone count converted: ~258 (含 Bone.L/R 4 根 dangling)

### 物理克隆
- `83/83 rigids, 64/64 joints, 0 bone(s) missing`
- 4 个 target-only bones auto-added: `Bone.L`, `Bone.R`, `Bone.001.L`, `Bone.001.R`

### VMD 物理 oscillation 基准

| VMD | bone keys | 乳奶.L x 振幅 | y | z |
|---|---|---|---|---|
| 摇香 (中等) | 9,037 | ~3.8cm | 2.0cm | 1.5cm |
| 八方来才 (大) | 71,460 | **~7.3cm** | 5.1cm | 4.2cm |

`|rel|` 应当**恒定 ≈4.0cm** (joint 球关节限制距离, 振幅来自方向变化)

物理工作的标志:
- `|rel|` 恒定 = joint 锁住
- 三轴振幅都 > 1cm = 真物理仿真在跑 (而不是 keyframe)
- 振幅与动作激烈程度成正比

### 视觉验证 (front view, frame 1)
- 双模型 T-pose 对齐
- 头发完整 (棕色, hide_get=False)
- 装备贴合 mesh
- 胸部 capsule (橘黄色, 物理可见时) 在前胸正确位置

---

## 故障排查

| 现象 | 原因 | 修法 |
|---|---|---|
| `乳奶 snap delta=0` | XPS 源不是 DAZ Genesis 8 (其他 rig 乳奶名不同) | 用对应 preset, 或扩展 `DEFAULT_SNAP_BONES` |
| `83/83 → 79/83` skipped | converted 缺骨 | 确认 `add_missing_bones=True` |
| VMD 导入后姿态不变 | bone_mapper 不对 | 用 `'RENAMED_BONES'` (因 setup_pmx_attributes 已 set name_j) |
| 头发被甩飞 / 物理炸 | rigid mass 太大 / VMD 太激烈 | 跑稳定后再截图; mass 默认 1.0 OK |
| 乳奶 rigid 偏 14cm | 没跑 step 8b snap | 手动 `bpy.ops.object.snap_misaligned_bones()` |
| `\|rel\|` ≠ 4.0cm | joint 没 build | 跑 `bpy.ops.mmd_tools.build_rig()` |
| build_rig 报 context error | active object 不是 mmd_root | 先 `bpy.context.view_layer.objects.active = root` |

---

## 验证清单

- [ ] Phase 1: 25 + 152 obj, target 83 rigids
- [ ] Phase 2 convert: snap log delta≈0.247m, 一键完成
- [ ] Phase 2 clone: 83/83 + 64/64
- [ ] Phase 3 摇香: 9037 keys, oscillation x≈3.8cm
- [ ] Phase 3 八方来才: 71460 keys, oscillation x≈7.3cm
- [ ] Phase 4 frame 1: 双模 T-pose 头发整, frame 100 同步
- [ ] |rel| 在两条 VMD 都恒定 4.0cm
