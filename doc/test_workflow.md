# XPS→PMX 转换测试流程

从空 Blender 到并排对比的完整端到端测试。

## 测试文件

| 文件 | 路径 (Mac) |
|------|-----------|
| XPS 源模型 | `/Users/bytedance/Downloads/demo/inase (purifier)_lezisell-A/xps.xps` |
| 目标 PMX | `/Users/bytedance/Downloads/demo/Purifier Inase 18/Purifier Inase 18 None.pmx` |
| VMD 动作 | `/Users/bytedance/Downloads/demo/永劫无间摇香2025.2.21by小王动画/永劫无间摇香2025.2.21.vmd` |
| 预设名 | `xna_lara_Inase`（**不是** `mmd_japaneseLR`） |

## 环境准备

1. **AWS 端**: `cd /opt/mywork/mytest/bl && sh aws_server.sh start`
2. **Mac 端**:
   - `cd /Users/bytedance/work/mytest/bl && git pull`
   - Blender 打开 → N 面板 → BlenderMCP → Start MCP Server
   - 另开终端: `cd /Users/bytedance/work/mytest/bl && sh mac.sh`

## 测试步骤

### 1. 导入 XPS + 加载预设

```python
import addon_utils
addon_utils.enable('XNALaraMesh-master')
bpy.ops.xps_tools.import_model(filepath='/Users/bytedance/Downloads/demo/inase (purifier)_lezisell-A/xps.xps')
arm = [o for o in bpy.data.objects if o.type == 'ARMATURE'][0]
bpy.context.view_layer.objects.active = arm
arm.select_set(True)
bpy.ops.object.load_preset(preset_name='xna_lara_Inase')
```

### 2. 执行转换流程 (Step 1~8)

逐步执行，避免一次性跑导致超时（Step 2 耗时较长，需要单独执行）：

```python
# Step 1
bpy.ops.object.rename_to_mmd()

# Step 2（单独执行，耗时 ~30s）
bpy.ops.object.complete_missing_bones()

# Step 2.1 ~ 4.5（可以合并执行）
bpy.ops.object.complete_twist_bones()
bpy.ops.object.complete_d_bones()
bpy.ops.object.complete_hip_cancel_bones()
bpy.ops.object.cleanup_face_bones()

# Step 5 ~ 8 + 转换（可以合并执行）
bpy.ops.object.assign_weights()
bpy.ops.object.add_mmd_ik()
bpy.ops.object.create_bone_group()
bpy.ops.object.setup_pmx_attributes()
bpy.ops.object.use_mmd_tools_convert()
```

### 3. 导入目标 PMX

```python
bpy.ops.mmd_tools.import_model(
    filepath='/Users/bytedance/Downloads/demo/Purifier Inase 18/Purifier Inase 18 None.pmx',
    scale=0.08
)
```

### 4. 给两个模型加载 VMD

```python
from mmd_tools.core.model import Model as MMDModel
vmd = '/Users/bytedance/Downloads/demo/永劫无间摇香2025.2.21by小王动画/永劫无间摇香2025.2.21.vmd'

for root_name in ('New MMD Model', 'Purifier Inase 18 None'):
    arm = MMDModel(bpy.data.objects[root_name]).armature()
    for o in bpy.data.objects: o.select_set(False)
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.mmd_tools.import_vmd(filepath=vmd, scale=0.08)
```

### 5. Build rig + 并排对比

```python
# Build rig（激活物理/IK 约束）
for root_name in ('New MMD Model', 'Purifier Inase 18 None'):
    root = bpy.data.objects[root_name]
    for o in bpy.data.objects: o.select_set(False)
    root.select_set(True)
    bpy.context.view_layer.objects.active = root
    bpy.ops.mmd_tools.build_rig()

# 并排放置
bpy.data.objects['Purifier Inase 18 None'].location.x = 0.8

# 缩放转换模型匹配目标身高（约 0.953）
bpy.data.objects['New MMD Model'].scale = (0.953, 0.953, 0.953)

# 跳到有动作的帧
bpy.context.scene.frame_set(50)
```

## 注意事项

- **预设选择**: 必须用 `xna_lara_Inase`，不是 `mmd_japaneseLR`。后者是 MMD 日文目标名，用于已转换完的模型
- **超时**: CLI exec 和 bridge 的 timeout 均需 ≥120s（已在 `cli/cli.py` 和 `bridge/bridge.py` 中修改）
- **XPS 插件**: 重启 Blender 后 factory_settings 会禁用 XPS 插件，需 `addon_utils.enable('XNALaraMesh-master')`
- **PMX import scale**: 目标 PMX 导入时 `scale=0.08`，VMD 也用 `scale=0.08`
- **刚体错位**: 如果目标模型刚体错位，执行 `clean_rig()` + `build_rig()` 恢复

## CLI 快速测试命令

```bash
# AWS 端直接执行
BLENDER_RELAY_API_KEY=mysecretkey python cli/cli.py exec "代码"
BLENDER_RELAY_API_KEY=mysecretkey python cli/cli.py screenshot
```
