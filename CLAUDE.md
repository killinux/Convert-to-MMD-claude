# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A Blender addon (Python package) that converts armature bone structures from various formats (Mixamo, VRM, DAZ, etc.) to MMD (MikuMikuDance) format. It requires Blender 3.0+ and optionally depends on the `mmd_tools` Blender addon for the final conversion step,要做一个通用的任何xps都能转成pmx的工具

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
`ui_panel.py` — single panel `OBJECT_PT_skeleton_hierarchy` drawn in the View3D sidebar.

Two tabs via `my_enum`:
- **骨骼映射** (option1): preset selector, bone mapping fields, import/export, action buttons
- **骨骼清理** (option2): utility operators for removing unweighted bones and merging single-child bones

### Operators (`operators/`)

| File | Key operators | Key behavior |
|------|-----------|--------------|
| `bone_operator.py` | rename_to_mmd, complete_missing_bones | 骨骼重命名 + 补全层级 |
| `twist_operator.py` | complete_twist_bones, split_upper/forearm_twist_weights | 位置识别 twist 候选骨 + VG 交换 + 梯度权重分配 |
| `leg_operator.py` | complete_d/hip_cancel_bones, assign_weights (5.1-5.8) | D骨 + 腰キャンセル + 统一权重分配 |
| `pose_operator.py` | align_arms/fingers_to_reference, fix_forearm_bend | rest pose 方向对齐（烘焙到 rest） |
| `preset_operator.py` | setup_pmx_attributes, use_mmd_tools_convert | fixed_axis + lock_rotation + name_j + mmd_tools convert |
| `ik_operator.py` | add_mmd_ik | 足IK + つま先IK 创建 + constraints |
| `collection_operator.py` | create_bone_group | 骨骼集合分组 |
| `face_operator.py` | cleanup_face_bones | XPS 面部细骨合并到頭 |
| `physics_operator.py` | setup_physics, extract_physics_template | 物理模板导入导出 |
| `clear_unweighted_bones_operator.py` | clear_unweighted_bones, merge_single_child | 清理工具 |

### Presets (`presets/`)
JSON files mapping property names to bone names for common skeleton formats. `canonical_arm_dirs.json` 存储参考手臂方向用于 fallback 对齐。

### Workflow order (完整 pipeline)
```
可选前置 (rename 之后):
  fix_forearm_bend → align_arms_to_reference → align_fingers_to_reference

主流程 (UI 按钮顺序):
  1.  rename_to_mmd              2.  complete_missing_bones
  2.1 complete_twist_bones       3.  complete_d_bones
  4.  complete_hip_cancel_bones  4.5 cleanup_face_bones
  5.  assign_weights (含 5.1-5.8, 包括 twist 梯度分配)
  6.  add_mmd_ik                 7.  create_bone_group
  8.  setup_pmx_attributes       使用mmdtools转换格式
  9.  setup_physics (可选)
```

### Mode switching
Many operators switch Blender modes internally. `complete_missing_bones` and `add_ik` switch to EDIT mode. `add_ik` then switches to POSE mode to add constraints. Be careful when editing these operators that mode transitions happen in the correct order.

## 姿态偏差排查顺序

遇到转换后模型与目标姿态不一致时，严格按以下顺序排查，不要跳步：

1. **方向偏差？** → 查 rest pose bone direction（`bone.matrix_local` Y/Z 轴），用 align 对齐
2. **旋转行为不对？** → 查 `lock_rotation`、`constraints`，对比目标
3. **控制范围不对？** → 查 vertex group 顶点数，看是否挂反或缺失
4. **以上都排除后才考虑权重** → 优先用数学方法（梯度分配），不手动调

**不要轻易切权重**。直接改权重容易引入新问题且难以回退。

注意：`Bone.roll` 只能在 Edit Mode 下访问，Object/Pose Mode 下用 `bone.matrix_local.to_3x3().col[2]`（Z 轴）代替。

## Debugging rule: rotate parent, watch child follow

**任何"mesh 跟着骨头动得不对"类的 bug, 第一步必须用 ground truth 验证: 在 pose mode 手动旋转父骨, 看子骨是否按预期跟随**。不要先看权重数据。

理由: 在 MMD 体系里, 一个骨能不能在 viewport 里产生预期变形, 取决于两个独立层:

1. **bone evaluation chain (constraint / driver)**: 子骨能不能跟随父骨/付与親源骨旋转。这个层是 mmd_tools 创建的 `_shadow_*` / `_dummy_*` 骨 + TRANSFORM constraint 链。如果链断了, **即使权重 100% 正确, mesh 也不动**。
2. **vertex weight (skinning)**: 哪些 vert 跟哪根骨, 各占多少权重。

**强制诊断顺序**:
1. L4 命名: bone.name 全扫一遍, 确认 VMD 能找到骨
2. L1 几何: bone.head_local / x_axis 比对 target rest pose
3. L2 评估: 在 pose mode 直接旋转父骨, 看子骨是否跟随
4. L3 蒙皮: 最后才看权重

**根因**: `mmd_tools.convert_to_mmd_model()` 只设 mmd_bone 元数据, 不创建 viewport constraint。本项目在 `OBJECT_OT_use_mmd_tools_convert` 末尾显式调用 `apply_additional_transform` (commit `c834b5c`)。

## Remote Development (AWS + Mac Blender)

- **代码位置（AWS）**：`/opt/mywork/mytest/Convert-to-MMD-claude/`
- **开发流程**：AWS 修改 → push → Mac pull → Blender reload
- **远程测试**：
  ```bash
  cd /opt/mywork/mytest/bl
  BLENDER_RELAY_API_KEY=mysecretkey python cli/cli.py exec "import bpy; ..."
  BLENDER_RELAY_API_KEY=mysecretkey python cli/cli.py screenshot
  ```

## File sync (Windows 注意事项)

`operators/` 下的文件含有中文字符串（日文骨骼名、中文注释）。在 Windows 上同步到 Blender AppData 时：

**正确做法**：用项目根目录的同步脚本：`python sync_to_blender.py`

**禁止用 PowerShell 操作含中文的 UTF-8 文件**：PowerShell 默认 GBK 编码会损坏 UTF-8 文件。

## 通用行为准则 (Karpathy Guidelines)

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

### 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

### 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

Source: https://github.com/forrestchang/andrej-karpathy-skills
