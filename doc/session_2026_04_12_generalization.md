# 2026-04-12 会话记录：通用化重构 + DAZ 模型实测

## 今日改动总览

### 1. 代码去重：shadow/dummy 委托 mmd_tools
- `ik_operator.py` 删除 ~100 行手动创建 shadow/dummy 骨 + TRANSFORM/COPY_TRANSFORMS 约束的代码
- 改由 `mmd_tools.apply_additional_transform()` 在 `use_mmd_tools_convert` 步骤统一创建
- mmd_tools 对方向一致的骨对（如 D 骨）会优化为直接约束，跳过 shadow/dummy 中间层

### 2. P0 通用化：硬编码偏移 → 体高比例

**核心思路**: `阈值 = 体高 × 比例系数`

`leg_operator.py`:
- 新增 `_body_height()` 辅助函数
- `HIP_TOLERANCE`: 0.05 → `body_h * 0.037`
- `UPPER_BODY_FLOOR`: 0.07 → `body_h * 0.052`
- `stray_threshold`: 0.25 → `body_h * 0.185`
- `_guess_side`: ±0.01 → `body_h * 0.007`
- `UPPER3_HEAD_Z`: 硬编码 1.3118 → 从实际 `上半身3` 骨骼位置读取
- `UPPER3_BLEND_START_Z`: 硬编码 1.2725 → 从 `上半身2.tail` 读取

`bone_operator.py`:
- 新增 `body_height` / `spine_len` / `ctrl_bone_len` 从实际骨骼计算
- 控制骨（センター/グルーブ/腰/肩P/肩C/ダミー）全部按比例定位
- 脊椎 fallback 全部基于 `spine_len` 比例

### 3. P1 通用化：去除 Inase 特定依赖

- `canonical_arm_dirs.json`: Inase 手臂方向 → 标准 MMD A-pose (45° 对称)
- `twist_operator.py`: `TWIST_BONE_LENGTH` 0.082 → `seg_len * 0.48` 比例
- `pose_operator.py`: `_find_arm_chain()` 从 2 种格式扩展到 6 种（XNA Lara / DAZ / Mixamo / VRM / Unity / MMD）

### 4. DAZ Genesis 8 模型支持

- 新增 `presets/daz_genesis8.json` 骨骼映射
- `bone_map_and_group.py` 新增 `upper_body3_bone` / `neck1_bone` key
- DAZ preset 映射: chestUpper→上半身3, neckUpper→首1, lPectoral/rPectoral→乳奶
- `rename_to_mmd` 新增 lPectoral/rPectoral → 乳奶 自动 rename

### 5. T→A pose 转换

- `_find_arm_chain()` 支持 DAZ 命名 (lShldrBend/lForearmBend/lHand)
- 无参考模型时使用标准 A-pose canonical fallback
- Reika T-pose 模型成功转换 42° 到 A-pose，mesh 正确跟随

### 6. DAZ 模型 twist/权重 bug 修复

**手指变形修复** (`twist_operator.py`):
- DAZ 的 lCarpal1-4 被误识别为前臂 twist 候选 → 加入兄弟骨排除逻辑
- 排除条件: 段终端骨的兄弟中「自身有子骨的」（Carpal 有手指子骨，真正 twist 骨是叶骨）

**胯部变形修复** (`leg_operator.py`):
- ThighTwist 骨的权重被 stray 修复误移 → stray 排除列表加入 `thightwist` / `thigh_twist`

**胯部辅助骨 reparent** (`bone_operator.py`):
- DAZ 的 Vagina/Rectum/Labia 等骨从 `下半身` reparent 到 `腰`
- 限制条件: Z <= 下半身.head（只移动胯部骨，不动胸部骨）
- 跳过 `unused` 开头和 `boob` 的骨（XPS 辅助骨保持原始 parent）

---

## Inase 基准验证

所有改动后 Inase 回归测试通过:
- Scale = 0.8364
- Diffs = 7/116（6 个 hair name_e + 1 个 足IK親 parent，全是已知项）
- 足D.L = 297 verts
- 4 xtra PRESERVE 保留
- VMD 动作一致，脚 IK 正常

---

## 遗留问题

### Reika (DAZ Genesis 8) 胯部轻微撕裂
- **现象**: 大腿弯曲时胯部交界处有轻微变形/撕裂
- **原因**: DAZ 模型用 Vagina(7848v)/Rectum(3474v)/Labia 等十几个胯部骨做精细权重过渡，MMD 只有 下半身+足.L/R，没有对应机制
- **已做**: reparent 到腰改善了一部分，但固有差异无法完全消除
- **不能切权重**（CLAUDE.md 原则），所以胯部骨权重保留原样
- **可能改进方向**: 未来可考虑在 assign_weights 中为 DAZ 胯部骨创建 additional_transform 约束，让它们部分跟随腿部旋转

### DAZ 面部骨清理
- `cleanup_face_bones` 的前缀匹配（`head eyebrow/eyelid/lip/...`）不覆盖 DAZ 命名（`lBrowInner/lEyelidUpper/rNostril` 等）
- 目前 DAZ 面部骨全部保留（176 个非标准 deform 骨），parent 正确（跟着頭/lowerJaw 动），不影响功能但增加文件大小
- 可扩展 face_operator 支持 DAZ 面部骨前缀

### 通用 XPS→PMX 还需要做的
- **更多模型测试**: 目前只测了 XNA Lara (Inase) 和 DAZ Genesis 8 (Reika)，需要更多 XPS 格式验证
- **Mixamo / VRM preset**: 已在 `_find_arm_chain` 中预留了命名支持，但还没创建对应 preset JSON
- **通用物理模板**: 目前只有 Inase 提取的物理模板，需要按体高缩放的通用模板
- **脚趾细分骨**: XPS 源没有 BigToe/SmallToe，但 Reika 的 DAZ 模型有（lBigToe/lSmallToe1-4），可以映射

---

## 今日 commits

| commit | 内容 |
|--------|------|
| `065ae3b` | 删除 shadow/dummy 手动创建，委托 mmd_tools |
| `c0eb91f` | P0: 硬编码偏移改体高比例 |
| `14ca01a` | P1: canonical fallback 改标准 A-pose + twist 骨长比例 |
| `49b5529` | 通用化重构文档 |
| `4fae427` | DAZ Genesis 8 preset |
| `16b36ce` | 手臂链检测支持 6 种命名格式 |
| `424b4cf` | 修复 DAZ 手指/胯部变形 |
| `e732150` | 修复 Carpal 兄弟排除（用子骨检测） |
| `49da078` | 精细化排除：只排除有子骨的兄弟 |
| `29669a0` | DAZ preset 补全 chestUpper/neckUpper/Pectoral |
| `057efd9` | 胯部辅助骨 reparent 到腰 |
| `b93733b` | reparent 限制: 只移动 Z<=下半身 的骨 |
| `e7ff463` | reparent 跳过 unused/boob 骨 |

---

## 下次会话继续

1. **验证 Inase 无回归** — 已确认 7/116 diffs，和基准一致
2. **Reika 胯部改进** — 考虑用 additional_transform 让胯部骨部分跟随腿部
3. **更多 XPS 模型测试** — 找 Mixamo 或其他格式验证
4. **DAZ 面部骨清理扩展** — 支持 DAZ 命名格式
5. **通用物理模板** — 按体高缩放的标准刚体/关节
