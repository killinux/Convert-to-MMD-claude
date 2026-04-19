# 刚体通用化 Session Handoff — 2026-04-19

## TL;DR (下次接续先读这个)

**完成**: Tier 1 (target PMX 克隆) + Tier 3 (PMXEditor-style 自动生成发型) 都实现并测过, Reika 83/83 rigids + 64/64 joints 从 target 克隆到位。

**✅ 对齐 bug 已修 (2026-04-19 续, HEAD `000cebf`)**: 用户报"刚体和身体没对齐" — 根因是 `_pmx_rigid_to_entry` 直接存 PMX world 坐标, apply 时没考虑 target/converted 模型的骨头位置差异。修法: entry 改存 `rigid_local_loc = rigid_world - target_bone_world` 这种 bone-local 偏移, joint 改存 `joint_local_to_a`, apply 时用 `dst_bone_world + local_loc` 重新锚定。验证 (Reika None.pmx 重克隆 83/83 + 64/64): local_loc 偏差 0/83, 视觉刚体完全贴合身体, avg 中点偏差 9.8cm → 0.9cm (剩 6 个 >5cm 是 bone 长度不同导致 midpoint 算出位置不一样, 但相对 head 的偏移 100% 保留 target 数据)。

**HEAD**: `000cebf` (本地 push 完, Mac 已 pull)

**Plan 原档**: `/root/.claude/plans/mmd-tools-pmxeditor-radiant-sky.md`

**设计文档**: `doc/physics_generalization_plan_2026_04_19.md` (本次 session 设计+进度)

---

## 已完成工作 (commits in order)

| HEAD | 内容 |
|------|------|
| `dc6f835` | fit_to_mesh: per-bone mesh picker (fix _find_body_mesh 选到 pubes 的 bug) |
| `bf20365` | strand mesh 过滤 (coverage<2 body bones 的 strand mesh 不做 thickness reference) |
| `891f81a` | fit_to_mesh log 阈值 5mm → 2mm |
| `ff20cf9` | **Tier 1**: `clone_physics_from_pmx` — 读 target PMX → 归一化 `左X → X.L` → 复用 apply_physics 路径 |
| `ec835f5` | **Tier 3**: `auto_chain_physics` — PMXEditor 经验公式 (CAPSULE len=bone, r=length×0.15, mass=0.5×0.8^depth, angle 梯度 10°→30°) |
| `c700515` | Tier 3 detection 修正 — skip `_shadow_`/`_dummy_`, 扩展 CANONICAL_BODY_BONES (全宽数字 fingers + 肩P/ダミー/両目/足先EX/足IK親/操作中心) |
| `0115fb9` | Tier 3 加 `anchor_bones` 白名单 (默认 `頭` 仅发型, 可扩展到 `下半身,手首.L` 等) |
| `42a1c93` | Tier 1 加 `_create_missing_target_bones` — target 引用的骨若 converted 没有, 自动从 target 读 head/tail/parent 建 edit bone (用于 dangling accessory 如 Bone.L/R 挂饰) |
| `4e47808` | edit mode 上下文修: 入 EDIT 前 unhide + deselect-all + select armature + set active; 出 EDIT 后 restore |
| **`650f232`** | **关键修复**: `_BONE_WEIGHT_ALIASES` 定义顺序 — `_mesh_bone_coverage` 作 default 参数引用它, 但原放在 60 行之后, 导致 blend 重启时 addon 模块 import NameError, operator 消失。移到前面 |
| `34ddbf7` | doc 更新 Tier 1 最终 83/83 |

## 关键 API / 文件路径

### `operators/physics_operator.py` 主模块

- `JP_SIDE_PREFIX_MAP` / `_normalize_pmx_bone_name()` — 左X ↔ X.L
- `CANONICAL_BODY_BONES` — 完整 MMD body + finger (含全宽数字 `０１２３`)
- `_is_internal_helper_bone(name)` — 检测 `_dummy_*` / `_shadow_*`
- `_BONE_WEIGHT_ALIASES` — D-bone / twist 别名映射 (**必须放在 _find_body_mesh 之前**)
- `_find_body_mesh(mmd_root)` — 按 bone coverage score 选 body mesh
- `_find_best_mesh_for_bone(mmd_root, bone_name)` — per-bone 选 mesh + strand 过滤
- `_fit_rigid_to_bone_verts(...)` — shrink-only, 90 分位点

**Tier 1 克隆**:
- `_pmx_rigid_to_entry(rigid, model, scale)` / `_pmx_joint_to_entry(...)`
- `_apply_cloned_physics(dst_root, data)` — 跳过 global_scale, 直接用 world_matrix
- `_create_missing_target_bones(dst_arm, model, scale)` — 拓扑补骨
- `clone_physics_from_pmx(dst_root, pmx_path, add_missing_bones=True, fit_to_mesh=True)`
- `OBJECT_OT_clone_physics_from_pmx` (file picker)

**Tier 3 自动生成**:
- `DEFAULT_AUTO_ANCHORS = frozenset(['頭'])` 默认只做发型
- `_bone_world_midpoint(arm, bone)` / `_bone_world_rotation_yxz(arm, bone)`
- `_detect_dynamic_chains(dst_root, arm, min_chain_length=2, anchor_bones=None)`
- `auto_generate_chain_physics(dst_root, anchor_bones, radius_ratio, root/leaf_angle_deg, ...)`
- `OBJECT_OT_auto_chain_physics` (props: anchor_bones 逗号分隔字符串)

### UI
`ui_panel.py` 物理 box 里已有 2 个新按钮:
- "🎯 从目标 PMX 克隆刚体"
- "💇 自动生成动态骨链刚体"

`TODO.md` P4 指向 `doc/physics_generalization_plan_2026_04_19.md`

---

## ⚠️ 未解决: 对齐问题 (下次 session 首要任务)

### 症状
用户反馈: "你建的刚体和身体没对齐啊"
视觉截图显示 rigid body + joint 都偏移到头部右上方, 不贴合 body/hair 实际位置。

### 当前怀疑的根因

`_pmx_rigid_to_entry` 把 PMX rigid 的位置处理成**世界坐标**:

```python
loc = Vector(rigid.location).xzy * scale     # PMX Y-up → Blender Z-up xzy swap
rot = Vector(rigid.rotation).xzy * -1
rigid_world_mat = Matrix.Translation(loc) @ Euler(rot,'YXZ').to_matrix().to_4x4()
```

然后 `_apply_cloned_physics` 直接把 world_matrix 传给 `createRigidBody`, 依赖"target PMX 和 converted 模型同 world 坐标系 + 同 scale"。

**问题可能出在**:
1. Target PMX rigid.location 是 PMX unit (需 * 0.08), 但当 target PMX 作者在 PMX 里用了不同 scale 保存时, 这个公式不对
2. 或者: target PMX 的"世界原点"和 converted Reika 的世界原点不一致 (比如 target 整体平移/旋转过)
3. 或者: target 和 converted 的**骨骼 rest pose 位置差异**导致 rigid 挂在 bone 上但 bone 位置不同

### 正确做法 (参考 apply_physics 原逻辑)

原 `apply_physics` 做法:
```python
# extract 时保存 LOCAL matrix (rigid world @ bone_world_inv)
sb_mat = _bone_world_rest(src_arm, bname)
rigid_local_mat = sb_mat.inverted() @ sr.matrix_world

# apply 时用 dst bone world @ local
db_mat = _bone_world_rest(dst_arm, bname)
new_mat = db_mat @ rigid_local_mat
```

这样 rigid 位置跟随 dst 骨的 rest pose, body 比例不同也 OK。

**Tier 1 应该也这样做**: 先读 target PMX 骨位置 + rigid 位置, 算出 `rigid_local = bone_rest.inv() @ rigid_world`, 然后 apply 时用 `dst_bone_rest @ rigid_local`。

### 修方案草案

改 `_pmx_rigid_to_entry`:
1. 加参数 `target_bone_world` (从 target PMX 算出来的 bone world matrix)
2. 算 local = target_bone_world.inverted() @ rigid_world
3. entry 里存 local_matrix 而不是 world_matrix

改 `_apply_cloned_physics`:
1. 读 dst bone rest matrix
2. new_world = dst_bone_rest @ local_matrix

从 target PMX 算 bone world matrix:
- PMX bones 的 `.location` 是世界坐标 (已验证: `Bone.L` loc=(1.09, 14.82, -1.63) 映射到 blender world ~ (0.087, -0.13, 1.186))
- 按 xzy * scale 转到 Blender 坐标
- 构造 identity rotation (bone 的 roll 信息只用于 pose, rest 位置由 head 定义)
- world_mat = Translation(bone_head_blender_coord)

对于 rotation: target PMX rigid.rotation 本身是相对**世界 YXZ Euler**, 不是相对骨, 所以 local rot = rigid.rotation @ inv(bone.rot) — 但因为 bone rest rot 通常简单 (align y axis), 这步可能只需处理平移。

### 验证方法

下次 session 第一步:
```python
import bpy
root = bpy.data.objects['New MMD Model']
# 看第一个 Bone.L 刚体的实际位置
for o in bpy.data.objects:
    if getattr(o,'mmd_type','')=='RIGID_BODY' and o.mmd_rigid.bone == 'Bone.L':
        print('Bone.L rigid world:', o.matrix_world.to_translation())
        arm = bpy.data.objects['Armature']
        print('Bone.L bone head world:', arm.matrix_world @ arm.data.bones['Bone.L'].head_local)
        # Expected: rigid world ≈ bone midpoint, capsule oriented along bone Y
        break
```

预期: rigid 位置应该和 bone 位置大致一致 (差距 < 0.1m), 且和 mesh 实际挂饰位置重合。若差距很大 → 确认是坐标换算错, 按上述方案改。

---

## 场景当前状态 (Blender 里保留)

- 场景: Reika 完整 pipeline (1→12) + VMD + 83 rigids (target 克隆) + 4 新骨 Bone.*
- HEAD at `34ddbf7`
- mmd_tools build_rig 未执行, 需要时 bpy.ops.mmd_tools.build_rig()
- 备份 blend: `/tmp/reika_s3_complete.blend` (但**没有** 83 rigids, 这是 morph 阶段备份)

## Plan Follow-ups (次要)

Plan 文件 `/root/.claude/plans/mmd-tools-pmxeditor-radiant-sky.md` 有 Tier 1/2/3 完整路线。除对齐 bug 外, 已完成。

后续 follow-ups (非紧急):
- 裙摆/袖口 anchor 实测 (需有裙摆的 XPS)
- 其他 XPS 模型验证 (Mixamo/VRoid)
- 清理 Reika 场景 / export PMX regression baseline

## 常用命令

```bash
# AWS 端开发
cd /opt/mywork/mytest/Convert_to_MMD_claude
git status / git log --oneline -10

# Mac 同步
BLENDER_RELAY_API_KEY=mysecretkey python /opt/mywork/mytest/bl/cli/cli.py exec "
import subprocess
r = subprocess.run(['git','-C','/Users/bytedance/Library/Application Support/Blender/3.6/scripts/addons/Convert_to_MMD_claude','pull','--ff-only'], capture_output=True, text=True)
print(r.stdout.strip())
"

# Reload addon after Mac pull
BLENDER_RELAY_API_KEY=mysecretkey python /opt/mywork/mytest/bl/cli/cli.py exec "
import sys, bpy
try: bpy.ops.preferences.addon_disable(module='Convert_to_MMD_claude')
except: pass
for k in list(sys.modules.keys()):
    if k.startswith('Convert_to_MMD_claude'): del sys.modules[k]
bpy.ops.preferences.addon_enable(module='Convert_to_MMD_claude')
print('op ok:', hasattr(bpy.ops.object, 'clone_physics_from_pmx'))
"

# Screenshot
BLENDER_RELAY_API_KEY=mysecretkey python /opt/mywork/mytest/bl/cli/cli.py screenshot
```

## 已知陷阱 (踩过的坑)

1. **Default argument 定义顺序**: Python 在 def 时就 eval default values, 所以 `_BONE_WEIGHT_ALIASES` 必须在用它当 default 的 `_mesh_bone_coverage` 之前定义。Blend 重启时 addon 模块 fresh import 会暴露 NameError, 但已 cache 的 Blender session 感觉不到
2. **bpy.ops 在 bg thread 里不工作**: Context 是 thread-local, 必须 main thread。exec 120s timeout 用 `threading.Thread` 绕不过 bpy.ops 的 context missing
3. **EDIT mode 前**: deselect-all + select armature + set active + unhide, 任一缺失 `mode_set.poll()` 就 fail
4. **PMX load**: `mmd_tools.core.pmx.load(path)` 在 main thread 只需 1s, 之前观察到 "90s" 是 thread 里调 bpy (卡 context)
5. **Blender 启动后 addon 看似 enabled 但未 load**: `'Convert_to_MMD_claude' in sys.modules == False` 时 bpy.ops 虽 hasattr=True (cache) 但调用报 "could not be found". 需 disable + `del sys.modules` + enable 强制 re-import
