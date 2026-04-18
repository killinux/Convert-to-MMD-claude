# Convert to MMD — Blender Addon

把 XPS / 其他格式的骨骼模型自动转成 MMD (MikuMikuDance) 可用的 PMX 格式。
骨骼重命名 / 补骨 / 权重 / IK / 物理 / 表情 morph **一条流水线**。

## 主要功能

- **骨骼重命名 + 补骨**: XPS 命名 → MMD 日文命名,自动补全扭转骨 / D 骨 / 腰キャンセル
- **权重分配**: 面部细骨合并到头,辅助骨权重按规则迁移到主骨
- **IK + PMX 属性**: 自动建 MMD IK 链,设置 PMX 导出需要的骨属性
- **物理**: 加载物理模板,胸部 rigid body 自动对齐
- **表情 Morph (Path D 程序化合成)**: 不需要 target PMX,直接用源 mesh 的 vertex group + 公式化 recipe 合成 19 条标准 MMD 表情 (あ/い/う/え/お/ん/まばたき/ウィンク/笑い/困る/怒り …)
- **表情验证**: 自动 spec 校验 + 批量截图 HTML 对比 + Blender 内交互式逐条过

## 依赖

- **Blender 3.0+**
- **mmd_tools** (同时启用) — <https://github.com/UuuNyaa/blender_mmd_tools>
- **XPS Tools** (导入 XPS 模型用) — <https://github.com/johnzero7/XNALaraMesh>

## 安装

1. 下载本仓库 zip 或 `git clone`
2. Blender `Edit → Preferences → Add-ons → Install...` 选 zip / 目录
3. 搜 "Convert to MMD" 勾选启用
4. 确认 `mmd_tools` 也启用了

## 使用流程

3D viewport `N` 面板 → `Convert to MMD` tab。顶部两个选项卡:

### 选项卡 1: 骨骼映射

主转换流程 (step 1→11):

```
预处理 (可选, 折叠) → 可选 align_arms / align_fingers / fix_forearm
①骨骼结构:   1.重命名  2.补全缺失  3.扭转骨  4.D骨  5.腰キャンセル
②清理+权重:  6.清理面部细骨  7.分配权重 (一键)
③IK+属性:    8.添加MMD IK  9.创建骨骼集合  10.设置PMX属性
④转换+物理:  11.使用mmd_tools转换  12.加载物理模板
```

**一键转换**: 点顶部 `🚀 一键转换 (1→11)` 按钮从 step 1 跑到 11。

**高级/调试** (折叠): step 7 的内部阶段可单独重跑 (unused→主骨 / 腰キャン清空 / 下半身清理 等),骨骼命名 .L/.R ↔ 左/右 互转。

### 选项卡 2: 物理 + 表情

- **胸部物理**: `应用胸部 rigid (乳奶.L/R)` — 要先跑过步骤 12 拿到锚点
- **刚体编辑**: 显示/隐藏所有刚体 (单个 rigid 用 MMD tab 的 Rigid Body 编辑)
- **表情 Morph**: `合成 19 条标准 MMD morph (Path D)` — 自动检测 5 个脸部 mesh (face / 双睫毛 / 眉 / 眼球),按 recipe 烘焙 19 条 shape key
- **表情 Morph 验证**:
  - `自动 Spec 校验` — 数据层面 19 条过/挂,CI-friendly
  - `批量截图 + HTML 对比` — 写 `/tmp/morph_verify/index.html`,Safari 打开分组看
  - `交互式逐条过` — 3D viewport 里按 `O=OK / X=Issue / N=Skip / ESC=Quit` 键盘翻卡片

## 典型转换流程 (XPS → PMX)

```
1. Blender 里 XPS Tools 导入 .xps 模型
2. Convert to MMD N面板 → 选项卡 1 → 选 XPS preset (xna_lara 等) → 🚀 一键转换
3. 切到选项卡 2 → 合成 19 条 morph → 自动 Spec 校验 (19/19 pass)
4. mmd_tools → Export MMD File → 保存 .pmx
```

## 文件结构

```
__init__.py                       # addon 注册入口
ui_panel.py                       # N 面板 UI
bone_map_and_group.py             # 骨骼映射表
bone_utils.py                     # 骨骼工具函数
operators/
    bone_operator.py              # 重命名 / 补骨
    collection_operator.py        # 骨骼集合
    face_operator.py              # 清理面部细骨
    ik_operator.py                # IK 链
    leg_operator.py               # 腿 / D 骨 / 权重分配 (多阶段)
    morph_synth_operator.py       # Path D 合成 + 验证工具 (ABC)
    physics_operator.py           # 物理模板 / 胸部 rigid
    pose_operator.py              # rest pose 对齐 / A-Pose 转换
    preset_operator.py            # 预设导入导出 / 一键转换
    twist_operator.py             # 扭转骨 + 权重渐变
experimental/
    morph_transfer_poc.py         # Path D 核心逻辑 (dev iteration)
presets/                          # 骨骼映射 JSON (xna_lara / daz / mixamo 等)
doc/
    pitfalls.md                   # ★ 踩坑指南 — 做错的方案全记录
    morph_session_handoff_*.md    # Morph 开发 session 交接
    morph_transfer_paths_*.md     # 4 条 morph transfer path 对比
    xps_unused_bones.md           # XPS 109 根骨全去向
```

## 开发 / 调试

代码修改在 AWS 端,commit + push,Mac 端 `git pull` 同步。**不要直接在 Mac 改代码**。
详见 `/opt/mywork/mytest/bl/CLAUDE.md` (Blender Remote Bridge 架构)。

核心 morph recipe 在 `experimental/morph_transfer_poc.py` 的 `INASE_RECIPES`,
每条 morph 形如:
```python
'あ': {
    JAW:         (0,  1, -3),     # vg → (x_mm, y_mm, z_mm)
    LIP_LOWER:   (0,  2, -5),
    CORNER_BOTH: (0,  0, -2),
    LIP_UPPER:   (0,  0, +0.5),
},
```

想给新模型(DAZ / Reika)做 recipe 就拷一份 + 换 vg 名字,细节见 `doc/morph_session_handoff_2026_04_18.md`。

## 文档指南

| 文档 | 何时读 |
|---|---|
| `doc/pitfalls.md` | **遇到 morph / transfer 相关问题先读**。所有已知的"做错了"方案 + 根因 |
| `doc/morph_session_handoff_2026_04_18.md` | 继续做 morph 相关工作的必读交接 |
| `doc/morph_transfer_paths_2026_04_18.md` | 4 条 cross-mesh transfer 方案对比 (Path A/B/C/D) |
| `doc/xps_unused_bones.md` | XPS 109 根骨骼的完整去向追踪 |
| `doc/TODO.md` | 待做项 / 已完成项 |
| `CLAUDE.md` | Claude Code 用的项目记忆 (流程约定 / 姿态偏差排查顺序) |

## 常见问题

**找不到 mmd_tools 插件**
→ Preferences → Add-ons 搜 "MMD Tools" 勾选启用,版本 ≥ 0.5.0

**骨骼位置偏移**
→ Object Mode 选骨架按 `Ctrl+A` apply transform;检查骨骼轴向:左右向骨 X 向前,上下向骨 X 向右

**一键转换中途失败**
→ 在"高级/调试"里找对应阶段单独重跑 (如 step 7 分配权重失败可只重跑 phase1/2/3...)

**合成 morph 按钮显示"未找到 Inase 5 个脸部 mesh"**
→ 当前 recipe (`INASE_RECIPES`) 是按 Inase XPS 的 vg 命名写的 (`head lip lower middle` 等)。不同源模型命名不同,需要新写 recipe preset (见 `experimental/morph_transfer_poc.py` 末尾 + `doc/morph_session_handoff_*.md`)

**morph 烘焙完但视觉不对**
→ 读 `doc/pitfalls.md` 「视觉判断的陷阱」和「Slider / Shape key 测试」两节,最常见是 slider 漂移(用 `set_morph_synced` 切,不要手动 set)和把 close-up 穿透当 bug

## License

随仓库。
