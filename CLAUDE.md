# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A Blender addon (Python package) that converts armature bone structures from various formats (Mixamo, VRM, DAZ, etc.) to MMD (MikuMikuDance) format. It requires Blender 3.0+ and optionally depends on the `mmd_tools` Blender addon for the final conversion step.

## Development

This is a Blender addon — there is no build step, test runner, or package manager. Development workflow:

1. Symlink or copy the repo directory into Blender's addons folder, or zip and install via Blender Preferences > Add-ons > Install.
2. After code changes, reload the addon in Blender: Preferences > Add-ons > find "Convert to MMD" > disable then re-enable, or use the Reload Scripts command (`F3` > "Reload Scripts").
3. Errors appear in Blender's system console (Window > Toggle System Console on Windows).

To test the addon, open Blender with an armature object selected and use the "Convert to MMD" panel in the 3D View sidebar (N-panel).

## Architecture

### Entry point
`__init__.py` — registers/unregisters all Blender classes, defines the preset `EnumProperty` and its update callback, and dynamically registers `bpy.types.Scene` string properties (one per MMD bone) via `register_properties()`.

### Core data
- `bone_map_and_group.py` — two data structures:
  - `mmd_bone_map`: dict mapping Python property names (e.g. `"left_upper_arm_bone"`) to MMD Japanese bone names (e.g. `"左腕"`). This is the single source of truth for which bones exist.
  - `mmd_bone_group`: list of bone group dicts used when creating bone collections in Blender.

- `bone_utils.py` — low-level bone helpers: `create_or_update_bone()` (works in EDIT mode), `set_roll_values()`, `apply_armature_transforms()`. Also defines `DEFAULT_ROLL_VALUES` for standard MMD bone roll angles.

### UI
`ui_panel.py` — single panel `OBJECT_PT_skeleton_hierarchy` drawn in the View3D sidebar. Contains inner layout helper functions (`add_bone_row_with_button`, `add_symmetric_bones_with_buttons`, `add_finger_bones_with_buttons`) that render prop_search fields paired with fill-from-selection buttons. Also contains `OBJECT_OT_load_preset` operator.

Two tabs via `my_enum`:
- **骨骼映射** (option1): preset selector, bone mapping fields, import/export, action buttons (rename → complete → add IK → create groups → mmd_tools convert)
- **骨骼清理** (option2): utility operators for removing unweighted bones and merging single-child bones

### Operators (`operators/`)
Each file is a self-contained operator module:

| File | Operators | Key behavior |
|------|-----------|--------------|
| `preset_operator.py` | export/import preset, fill-from-selection, mmd_tools convert | `get_bones_list()` derives the scene property list from `mmd_bone_map` |
| `bone_operator.py` | rename to MMD, complete missing bones | Rename reads scene props → renames edit bones; complete works in EDIT mode and hard-codes bone hierarchy/positions relative to existing bones |
| `ik_operator.py` | add MMD IK | Creates 6 IK bones (足IK親, 足ＩＫ, つま先ＩＫ for each side) in EDIT mode, then switches to POSE mode to add IK/rotation-limit/damped-track constraints |
| `collection_operator.py` | create bone group | Uses `mmd_bone_group` data to create Blender bone collections |
| `pose_operator.py` | convert to A-pose | Rotates shoulder/arm bones from T-pose to A-pose |
| `clear_unweighted_bones_operator.py` | clear unweighted bones, merge single-child bones | Cleanup utilities |

### Presets (`presets/`)
JSON files mapping property names to bone names for common skeleton formats (Mixamo, VRM, DAZ, XNA, etc.). Loaded by `OBJECT_OT_load_preset` and the preset EnumProperty.

### Workflow order
The intended user workflow matches the UI button numbering:
1. Select preset or manually map bones in the UI
2. **1. 重命名为MMD** — rename bones to MMD Japanese names
3. **2. 补全缺失骨骼** — create/fix hierarchy bones (全ての親, センター, グルーブ, 腰, IK parents, etc.)
4. **3. 添加MMD IK** — add IK bones and constraints
5. **4. 创建骨骼集合** — assign bones to named collections
6. **使用mmdtools转换格式** — call `mmd_tools.convert_to_mmd_model()` (requires separate mmd_tools addon)

### Mode switching
Many operators switch Blender modes internally. `complete_missing_bones` and `add_ik` switch to EDIT mode. `add_ik` then switches to POSE mode to add constraints. Be careful when editing these operators that mode transitions happen in the correct order.

## Remote Development (AWS + Mac Blender)

本插件可通过 Blender Remote Bridge 进行远程开发和测试：

- **代码位置（AWS）**：`/opt/mywork/mytest/Convert-to-MMD-claude/`
- **Blender 运行在**：公司内网 Mac 上，插件已安装
- **开发流程**：
  1. 在 AWS 上修改插件代码
  2. 用户在 Mac 上 pull 最新代码
  3. Blender 中重新加载插件即可生效
- **远程测试**：通过 Blender Remote Bridge 执行 Python 代码和截图
  ```bash
  cd /opt/mywork/mytest/bl/cli
  BLENDER_RELAY_API_KEY=mysecretkey python cli.py exec "import bpy; ..."
  BLENDER_RELAY_API_KEY=mysecretkey python cli.py screenshot
  ```
- **不需要**从 AWS 推送文件到 Mac，用户自行 pull

## File sync (Windows 注意事项)

`operators/` 下的文件含有中文字符串（日文骨骼名、中文注释）。在 Windows 上同步到 Blender AppData 时：

**正确做法**：用项目根目录的同步脚本：

```
python sync_to_blender.py
```

这个脚本同步所有 `.py` 和 `presets/*.json`，并自动清除 `__pycache__`。

**禁止用 PowerShell 操作含中文的 UTF-8 文件**：
- `Add-Content` / `Set-Content` 在中文 Windows 默认用 GBK，会把 UTF-8 文件写坏
- `Get-Content | Set-Content -Encoding UTF8` 也不行——读取阶段已经用 GBK 解码，写出的是二次损坏的内容
- 即使加 `-Encoding UTF8`，PowerShell 写出的是带 BOM 的 UTF-8，Python 会报 `SyntaxError: invalid non-printable character U+FEFF`
