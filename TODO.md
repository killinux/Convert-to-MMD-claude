# TODO

## 目标：通用 XPS → MMD 转换插件

长期目标是把这个插件做成任意 XPS 模型都能一键转 MMD，而不仅限于 XNA Lara Inase。
当前已验证格式：XNA Lara（Inase）+ DAZ Genesis 8（Reika）。

---

## P0 — 通用化剩余工作

### 面部骨清理支持 DAZ 命名

- **`cleanup_face_bones`** 当前只识别 XNA Lara 的 `head xxx` 前缀（`head eyebrow/eyelid/lip/mouth/nose/tongue/cheek/jaw`）
- DAZ 模型用完全不同的命名：`lBrowInner/lBrowMid/lBrowOuter`、`lEyelidUpper/Lower/Inner/Outer`、`lCheekUpper/Lower`、`lLipCorner/LipUpperOuter/LipBelowNose`、`BelowJaw/Chin/LipBelow` 等
- Reika 转换后有 81 根 DAZ 面部骨残留，全部混在骨列表里
- 方案：
  1. 扩展前缀识别（加 DAZ 命名）
  2. 或改用 parent-based 识别：所有 parent=頭（DAZ 里是 `head`）的末端小骨 + 有 < 某阈值顶点权重 = 面部细骨
  3. 或读 preset 的 `head_bone` 字段找头骨，递归扫其子树

### 通用辅助骨保留策略

- 当前 `PRESERVE_HELPER_KEYWORDS` 硬编码 `xtra02/04/08/08opp/muscle_elbow`（Inase XPS 专用）
- DAZ 的 ThighTwist/ShldrTwist/ForearmTwist 没有 `unused ` 前缀，自动跳过 Phase 5.1（无意中达到保留效果）
- 想要通用：
  - 检测原则：若骨 parent 是 MMD 标准骨 && 不是 MMD 标准名 && 有权重 → 默认保留
  - 移除硬编码关键字
  - 需要确保 Inase 4 根 xtra 骨仍保留

### 更多模型格式验证

- 已验证：XNA Lara（Inase）、DAZ Genesis 8（Reika）
- 未验证：Mixamo、VRoid、Unity Humanoid、Bip_001 3ds Max、iClone
- Presets 目录里有 20+ preset 但大多没实测
- 每种格式至少跑一次 + target PMX 对比 + VMD 动作测试

---

## P1 — 上半身后续

- **ダミー.L/R**: MMD 标准的手首末端配饰挂点骨 (parent=手首, 长度~1.2x 手长)。
  无动作影响, 只给配饰/物品用。XPS 无对应源, 需要创建空骨。优先级低, 有动作
  需求后再做。
- **乳奶1.L/R (第二节)**: 当前只 rename `boob left/right 1` → `乳奶.L/R`。
  XPS 有 `boob left/right 2` 作为第二节, 目标 PMX 没有对应骨但有独立运动。
  是否把第二节 rename 成 `乳奶1.L/R` 需要验证是否能在 MMD 里正确变形, 可能
  需要物理 joint 配合。
- **乳奶骨的位置识别版本**: 目前 `boob/breast left/right 1` 是硬编码名字 rename。
  其他 XPS 模型 (Daz/Poser 等) 可能用不同名字。可以加位置识别: 扫描
  parent ∈ {上半身2, 上半身1} + 胸部区域 + 有权重 的骨。

## P2 — 下半身 / 腿

- **腿部 twist 系统**: target PMX 没有腿部 twist 骨 (标准 MMD 也很少有),
  但有些模型会加 (DAZ 有 ThighTwist/ShinTwist)。当前完全不处理，靠保留机制 work。
- **足IK親**: target 有 `足IK親.L/R` (parent=全ての親, 控制 `足ＩＫ` 的父骨),
  现在 `add_mmd_ik` 只创建 `足ＩＫ` 和 `つま先ＩＫ`, 没创建 `足IK親`。
- **脚趾细分骨 (BigToe/SmallToe)**:
  - Inase XPS 源没有 — TODO 可以从 target 克隆
  - Reika DAZ 源有 lBigToe/lBigToe_2 + lSmallToe1~4 + _2 — 可以映射到 MMD 标准的脚趾骨
  - 需要位置识别 + rename 方案

## P3 — 表情 / morph

- **面部表情检查/观测工具 (2026-04-18 新, 必做)**:
  - 需求: user 能一条一条过每个 morph 判断视觉 OK;Claude 能 programmatic 快速验证
  - 三种工具,按难度升序实施:
    - **C (batch screenshot report)**: 批量截每个 morph 1.0 状态,输出 HTML 或图片 grid,人工扫一遍。最快上手,~50 行 bash/python
    - **B (auto data check)**: `verify_morph_data(mesh, name, expected_spec)` 检查 max_mm/moved_verts/region_distribution 是否符合 spec,不用人眼,CI-friendly
    - **A (UI modal operator)**: Blender addon 按钮,循环 slider=1.0 + 弹窗 [OK/有问题],用户点按记录结果
  - 关键实现点:
    - 必须用 `set_morph_synced` 切换 slider (见 `experimental/morph_transfer_poc.py`)
    - 固定 view_location + view_distance + ortho 保证截图可对比
    - 为每条 morph 准备 expected spec (嘴/眼/眉不同 region check)
  - 参考: `doc/morph_session_handoff_2026_04_18.md` "P0 面部表情检查工具" 章节

- **路径 D operator 化 (进行中, 2026-04-18)**:
  - 已实现: `experimental/morph_transfer_poc.py` 
    - `bake_programmatic_morph(src_mesh, morph_name, recipe)`  
    - `bake_eyeball_recede(eyeball_mesh, ...)` 眼球 Y+6mm 缩进 socket (必需)
    - 8 条 recipe 跑通: あ/い/う/え/お/まばたき/ウィンク/ウィンク右
  - TODO operator 化:
    - 新 operator `OBJECT_OT_generate_mmd_morphs_programmatic` 放 `operators/morph_operator.py`
    - 搬 recipes 到 `presets/morph_recipes_inase.py` (future DAZ preset 同路径加)
    - UI: option2「物理+表情」tab → 新 Morph Generation section,按钮 [生成 8 条标准 morph]
    - 自动 detect face mesh (vg 含 "head lip") + eyeball mesh (vg/name 命中)
    - Optional: gain slider (0.5x-2x)
  - 已知 side effect: ウィンク/ウィンク右 时两眼 eyeball 都 Y+6 后退,需要 X 过滤改到只退对应侧
  - 扩展方向: 眉系 5 条 (困る/怒り/真面目/上/下)、嘴扩 (にやり/激怒)、眼扩 (笑い/びっくり/じと目)
  - 参考: `doc/morph_transfer_paths_2026_04_18.md`

- **bone / material / group morph 克隆 operator**（方案 3）— **已实现 2026-04-18**
  - `operators/morph_operator.py` `clone_morphs_from_target`
  - UI: option2「物理+表情」tab → 表情 Morph → 从 target 克隆
  - 设计文档 + 踩坑记录: `doc/morph_clone_plan.md`
  - Smoke test 通过 (target PMX 导两次, 19/19 bone morph 克隆)
- **方案 A: 补面部驱动骨 operator** — **已实现 2026-04-18**
  - `operators/face_operator.py` `clone_face_bones_from_target` (`OBJECT_OT_clone_face_bones_from_target`)
  - 枚举 target bone_morphs 引用的骨, 过滤出 source 缺失的, 用 DFS 收集完整父链 (topological order)
  - Edit mode 下创建骨: 头尾用相对父骨的偏移复制, roll 用 `align_roll(target.matrix_local.col[2])`
  - 拷 mmd_bone 字段: name_j, name_e, is_tip, transform_order, is_controllable, local_axes, fixed_axis
  - UI: option2「物理+表情」tab → ① 补面部驱动骨, 先跑 ① 再跑 ②
- **方案 B: bake bone_morph → vertex_morph proximity transfer** — **已实现 2026-04-18**
  - `operators/morph_operator.py` `bake_and_transfer_morphs` (`OBJECT_OT_bake_and_transfer_morphs`)
  - 对每条 target bone_morph 临时 pose armature, 读 evaluated mesh 算 per-vert 位移
  - 用 head-relative 坐标 + 身高归一化 scale 建 KDTree, 按 k-最近 + inverse-distance 加权把 offset 传到 source 各 mesh 的 shape key
  - 注册为 mmd_root.vertex_morphs, 跟随 PMX 导出
  - UI: option2 tab → ③ bake+传 vertex morph
  - 默认阈值 2cm, k=3, min_magnitude 0.1mm
- **Inase 实测 (2026-04-18)**: 19/19 morph 传完
  - 缩放 target→src 自动测出 0.0797 (target 18m vs src 1.5m)
  - あ 2527 src verts, 笑い 4082, まばたき 1957 等
  - 嘴/眼/眉位移方向正确, 最大位移 ~5mm (跟 target 几何等比缩放后合理)
- **vertex morph 生成**（方案 2，仍 TODO）
  - 识别「眼睛」/「嘴」顶点
  - 利用 XPS 面部细骨驱动 shape key 录制
  - 再从 shape key 建 MMD vertex morph
  - 当前转换后 vertex_morphs = 0
- **uv morph 克隆**（TODO）
  - 按 vertex index 走, topology 不同不能直接克隆
  - 需要 proximity-based transfer

## P4 — 物理

- **通用物理模板**:
  - 当前只有 Inase 模板
  - 需要从更多 target PMX 提取模板
  - 可能需要体型参数化（身高/胸围/腰围缩放）

- **刚体通用化分层方案 (进行中, 2026-04-19)** — 详细设计见
  [`doc/physics_generalization_plan_2026_04_19.md`](./doc/physics_generalization_plan_2026_04_19.md)
  - 3 层 fallback: Tier 1 从 target PMX 克隆, Tier 2 Inase 模板 (已有),
    Tier 3 PMXEditor 经验公式自动生成动态骨链 (发型/裙摆/尾巴)
  - Reika 实测: 当前 21 rigid, target PMX 有 83, 缺口全部发型
  - HEAD `891f81a`: fit_to_mesh 已修 (per-bone mesh pick + strand 过滤 + log 2mm 阈值)
  - 下一步: 实现 `clone_physics_from_pmx` (Tier 1), 再补 `auto_chain_physics` (Tier 3)

## P5 — 代码 / 工具

- **operators/ 拆分**: 当前 `bone_operator.py` 里塞了 rename + complete
  + 两个 convert helper, 可以拆成 rename / structure / convert 三个文件。
- **preset 格式 v2**: 加上开关 (是否创建 twist sub, 是否创建 ダミー 等),
  目前只有 bone name 映射。
- **单元测试**: 给 twist_operator 写个能离线跑的 pytest, mock 一个简易 XPS
  骨架, 验证候选识别 + 分配算法。
- **已知 bug 清理**: 见 `doc/known_issues.md` BUG-01 ~ BUG-10

---

## 已完成

### 2026-04-13
- Lower Body Cleanup 从绝对阈值 `D >= 0.1` 改为相对比较 `D > lower_w`（commit `06ebdc0`）
  - Reika 胯部权重恢复 +1857 verts
  - Inase 无 regression
  - 符合「不切权重」原则
- 新增 `doc/hip_leg_fix_methods.md`：L4→L1→L2→L3 诊断顺序 + 可用方法 + 踩坑记录

### 2026-04-12
- pelvis helper bones 不再 reparent 到 腰（commit `746d78e`）
- 通用化重构 P0/P1：shadow/dummy 委托 mmd_tools，体高比例化，canonical A-pose fallback
- DAZ Genesis 8 preset + 完整 pipeline 验证（Reika）

### 2026-04-11
- `apply_additional_transform` 1 行修复 Inase 上臂 twist（commit `3a6ea0c`）
- 骨架对齐 target 完整迭代（10 commit）
- 上半身 twist 系统重写（位置识别）
- 死代码清理 -1930 行

---

## 已知残留差异（不需要修）

- **Reika**：96/206 cosmetic 差异（name_e + lock_loc 全是 Hair 骨），parent 差异 0，非 cosmetic 差异 0
- **Inase**：7/116 差异（1 个 足IK親.L 是 target PMX 自身 bug，其余是 name_e）
- mesh 密度差异（xtra 权重占比低 2.7% vs target 15.1%）不是 bug，是拓扑不同

参考：`doc/hip_leg_fix_methods.md` 的「踩过的坑」章节
