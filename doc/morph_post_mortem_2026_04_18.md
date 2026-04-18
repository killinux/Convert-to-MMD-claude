# Face Morph Generation 复盘 (2026-04-18)

**给下一个 Claude 会话**：这份文档记录了本次面部表情生成功能的完整尝试过程、具体错误、隐含假设以及后续建议。开始新设计前请先读完。

## 背景与目标

**原始需求**：Convert_to_MMD_claude 把 XPS 模型转换成 MMD 后，转换结果 `vertex_morphs = 0` 完全没表情。用户希望转完就有标准 MMD 表情（あ/い/う/え/お/まばたき/笑い/ウィンク 等 19 条）。

**约束条件**（用户后期明确）：
- 要支持**任意 XPS 源**，不能只支持 Inase
- **大多数 XPS 没有对应 target PMX**，不能强依赖 target
- XPS 源的 rig 能力因 format 而异（XNA Lara / DAZ / Mixamo / VRoid 等）

## 尝试过的三条路线

### 路线 1：`clone_face_bones_from_target`（方案 A）

**思路**：target PMX 的 bone_morph 引用的面部骨（Jaw Bone / QQ*1-51）在 source 转换模型不存在（被 `cleanup_face_bones` Step 9 删除合并到 頭），需要先把这些骨从 target 克隆过来。

**实现**：DFS 找缺的骨 + 父链 → edit mode 创建骨（head/tail 用相对 parent 的 offset 复制，roll 用 `align_roll(target.matrix_local.col[2])`）→ 拷 mmd_bone 元数据。

**结果**：代码 work — 19/19 bone morph 克隆成功、PMX 导出往返保留、mmd_tools 的 TRANSFORM 约束链建立后 slider → dummy_armature → 真 armature 链路完整、`あ=1.0` 实测 Jaw Bone 旋转到 `(0.999, 0.042, 0, 0)` 完全对。

**为什么用户看不到视觉效果**：
- 转换后 source mesh 没有权重绑到新补的骨（因为 `cleanup_face_bones` Step 9 已经把面部权重全合并到 頭 了）
- 骨 rotation 发生，但没 vert 跟随 → 视觉上嘴/眼不动

**代码**: `operators/face_operator.py` `OBJECT_OT_clone_face_bones_from_target`（仍在仓库，commit `365bdfe`）

---

### 路线 2：`bake_and_transfer_morphs`（方案 B）

**思路**：对每条 target bone_morph 临时 pose target armature → `evaluated_get(depsgraph).data` 拿变形后 vert 位置 → 计算 per-vert offset → 用 KDTree 做 proximity match 把 target vert offset 传到 source vert 的 shape key。

**实现**：head-local 世界坐标 + 按身高归一化 scale + 1cm 距离阈值 + k=3 近邻 inverse-distance 加权 + min_offset_magnitude 过滤。

**看起来成功的状态**：
- 自动算出 target→src scale ≈ 0.0797
- 19/19 morph 传完，面部 mesh 每个 morph 产生 100~600 verts 位移
- 最大位移 ~5-14mm 合理范围
- `あ` 在 face mesh 上最大位移的 vert 方向 `(+0.002, +0.002, -0.005)` — Z 向下、Y 向前，**理论上对的**

**实际视觉失败**：
- 用户截图看 `う=1.0` 时，整张脸变形怪异、眼睛也被拖动变形
- 深入调查发现：**source 和 target 的 頭 骨锚点在解剖上不是一个位置**
  - Source (XNA Lara Inase) 頭 骨 head 在 Z=1.524（下巴级），面部 mesh 在 Z=1.526-1.724（全在頭上方）
  - Target (Purifier Inase 18 PMX) 頭 骨 head 在 Z=1.492（头顶级），jaw-weighted vert 在 Z=1.452-1.489（在 頭 下方）
- 两边"头相对世界空间"的几何分布完全错位 → source 嘴 vert 在 head-relative Z≈+0.03，target 嘴 vert 在 head-relative Z≈-0.04 → KDTree 找不到对应点或找错点
- Scale 还有二次陷阱: target 默认 import scale=1.0（~18m 高，PMX 原生单位），source XPS ~1.5m（Blender 米），两边量纲差 12 倍；得改 target 为 scale=0.08 import 才对齐

**代码**: `operators/morph_operator.py` `OBJECT_OT_bake_and_transfer_morphs`（仍在仓库，commit `ec32e7f`）

---

### 路线 3：XPS face bone recipe（未落地）

**思路**：XPS 源自带 ~28 根面部细骨（`head eyebrow/eyelid/lip/mouth/nose/jaw/cheek *`），不依赖 target。按 per-format preset 定义"MMD morph 名 → XPS 面部骨 pose 列表"的 recipe，bake 成 shape key 注册为 vertex_morph。

**规划过**但**没完整实施**，只做了探索性验证：

**已验证有效**：
- `head jaw` X+20° rotation → 嘴漂亮张开（"あ" 的基础）
- jaw 单骨能做 あ/あ２/え/お 系列的嘴开合

**验证失败**：
- 眼皮 `head eyelid upper left/right` X 轴旋转 45° → 眼睛中间闭了两端开（**pivot 几何问题**：单骨 pivot 在内角，rotation 让 tail 移动最多、head 不动，中间 verts 按线性插值，最后效果是中间位移最大、两端几乎不动）
- 尝试 90° 旋转 / Z 轴旋转 / translation + rotation 组合 / L/R mirror — 都做不到均匀闭眼
- L/R mirror 不是简单 Z 符号反转（取决于 rigger 约定，可能 X/Y/Z 都要反），手写 quaternion 基本靠猜

**结论**：Inase XPS 的 rig 每眼只有 1 根 eyelid upper + 1 根 eyelid lower，rigger 设计意图可能只是给简单 lip-sync，不是全套 MMD 标准表情。**单骨 rotation 物理上做不到均匀闭合**，这是 rig 的局限不是代码问题。

---

## 我犯的错（按 Karpathy 原则对照）

### 违反原则 1 (Think Before Coding)：没说出来的隐含假设

| 假设 | 实际情况 |
|---|---|
| target 和 source 的 頭 骨在解剖上同位置 | ❌ target 頭 在头顶，source 頭 在下巴 |
| target 默认 import scale 和 source 一致 | ❌ test_workflow 里 target 用 scale=1.0（原始 PMX 单位）做骨骼对比，source XPS 用默认 ~1.5m |
| quaternion 可凭直觉算出轴 + 角度 | ❌ 每根 XPS 骨的 local axis 方向不统一，凭感觉猜是摸黑 |
| L/R 对称 = Z 分量镜像 | ❌ 取决于 rigger 约定，X/Y/Z 都可能要反 |
| XPS 每侧 1 根眼皮骨能完整闭眼 | ❌ 单骨 rotation 几何上做不到 |
| 19 个标准 MMD morph 都可自动生成 | ❌ 复杂情感类（笑い/にやり/困る）没有单一几何规则 |

### 违反原则 4 (Goal-Driven Execution)：没定义 success criteria

没问用户 "视觉通过的判断标准是什么"：
- 嘴张开多少 mm 算过？
- 眼闭上 100% 闭 vs 80% 算过？
- 其他区允许被污染多少？
- 19 个 morph 全必须 vs 5 个够用？

结果每次改完截图才发现不对，浪费 10+ 回合。

### 违反原则 3 (Surgical Changes)：方向飘移

- 方案 A → 发现无视觉 → 做方案 B → 发现对不齐 → 做 recipe → 发现骨不够 → 准备做程序化
- 每次遇到 L3/L4 级问题就换 L1 级方案，没深入挖 root cause
- 用户多次要拉回来问"到底是哪个问题"

### 违反原则 2 (Simplicity First)：过度 scope

用户说"任意 XPS 都支持"时，我立即想做 19 条 morph × 多骨 recipe × 多格式 preset，**没先问"最小可用集是什么"**。实际上 VMD 最常用的也就 5-8 个 morph，一张 嘴 + 一对 眼皮就覆盖 80% 场景。

---

## 技术踩坑（具体可复用）

### mmd_tools API

1. **`BoneMorphData.bone` / `MaterialMorphData.material` 是 virtual StringProperty**
   - getter/setter 经 `FnModel(prop.id_data).armature()`
   - operator 上下文里对新 `.add()` 的 PropertyGroup 调 setter 会**静默失败**（在 operator 外手动赋值却能成功）
   - **Fix**: 预先用 `FnBone(pose_bone).bone_id` / `FnMaterial(mat).material_id` 算好，用 dict 写 `dst_off["bone_id"] = N` bypass RNA setter

2. **Operator 不能用 `PointerProperty(type=bpy.types.Object)` 做 kwarg**
   - Blender 会报 `TypeError: keyword "xxx" unrecognized`
   - **Fix**: 改 `StringProperty` 存对象名 + UI 用 `layout.prop_search(self, 'name', bpy.data, 'objects')`

3. **`Model.meshes()` 返回 `.placeholder`（mmd_tools internal mesh）**
   - 传 morph 时会污染它的 shape keys，破坏 bone morph slider bind
   - **Fix**: 过滤 `_is_user_mesh = not obj.name.startswith('.')`

### Blender armature + depsgraph

1. **`addon_disable + addon_enable` 不会从磁盘 reload 模块**
   - sys.modules 缓存旧 class，即使 git pull 了新代码，registered class 还是旧的
   - **Fix**: `for n in [k for k in sys.modules if k.startswith('Convert_to_MMD_claude')]: del sys.modules[n]` 后再 enable

2. **`hide_viewport=True` 的 armature 停止 pose-to-mesh 求值**
   - 截图时为了显示干净，我把所有 armature `hide_viewport=True`，后续 `evaluated_get` 读到的是 basis，不是变形后
   - **Fix**: bake 前 `arm.hide_viewport = False`；或用 `bpy.context.scene.frame_set()` 强制 depsgraph rebuild

3. **设 pose → 读 evaluated mesh 的正确顺序**
   ```python
   pb.rotation_quaternion = (...)
   bpy.context.view_layer.update()              # 必须在 get depsgraph 之前
   dep = bpy.context.evaluated_depsgraph_get()  # 拿到更新后的 depsgraph
   em = mesh.evaluated_get(dep).data            # 读变形后 mesh
   ```

4. **未知污染态**：本次后段出现过 target armature 即使设 Jaw Bone 90° 旋转，mesh 也纹丝不动。fresh import 恢复正常。可能跟 `mmd_tools.build_rig()` / `morph_slider_setup(type='BIND')` 的残留 TRANSFORM constraint 有关；具体根因没查清。**建议：跑 bake 前 fresh 导入或至少 delete .placeholder / .dummy_armature**。

### Scale 陷阱

1. **target PMX 默认 import scale**：
   - `scale=1.0` → PMX 原生单位（~18m 高）
   - `scale=0.08` → MMD 标准换算到 Blender 米（~1.5m 高）
   - test_workflow.md memory 里用 scale=1.0 做骨骼对比，但做 morph 时要 **scale=0.08 重 import**
   - 否则两边量纲差 12 倍，KDTree 距离阈值完全没意义

2. **scale 归一化**：如果非要混用，要 `tgt_to_src_scale = src_body_height / tgt_body_height` 乘到 offset 和 position 上；但不如两边 import 时就对齐

### MMD 骨锚点不是解剖通用

1. `頭` 骨 head 位置在不同 PMX 里可以是下巴、是头顶、是脖子根 — 不是统一约定
2. `目.L` 骨位置相对更稳定（是眼球骨，位置必须在眼睛中心）→ **更可靠的解剖 landmark**
3. `Jaw Bone` 是 XPS target-PMX 专用名，不是 MMD 标准骨
4. 跨模型做 proximity 对齐前**必须先验证两边的 anchor bone 在解剖上是否一致**

### XPS 面部骨 rig 局限

1. Inase XPS 每眼只有 1 根 upper + 1 根 lower eyelid，单骨 rotation 做不到均匀闭合
2. 复杂表情（鼓腮、撅嘴、歪嘴、惊愕）rig 里根本没有骨支持
3. **rig 能力要在开工前 probe**：检查 source mesh 里 "eye/lip/brow" 相关 vertex group 的顶点数和骨数量，判断能支持什么级别的表情

---

## 给下一轮的建议

### 开工前（不动代码）必做

1. **跟用户定 success criteria**
   - 必须做哪几个 morph 才算"可用"？
   - 单个 morph 的视觉通过标准是什么？（嘴开 X mm / 眼闭 X%）
   - 对污染的容忍度？（允许脸颊稍微跟随吗？）
   - 有无 target 两种场景各什么标准？

2. **写决策树**
   ```
   if 有 target PMX:
     if 同拓扑 (相同 vert 数): clone vertex_morph by index        # 理想
     elif 异拓扑: 方案 B (proximity transfer, 需 scale 对齐)      # 已实现但方案不够健壮
   else (无 target):
     if source 有丰富面部骨 (rig 支持): 方案 recipe                # 本次失败, 但 あ 系 work
     else (rig 简陋 / 无面骨): 程序化 landmark 公式 or sculpt assist  # 未尝试
   ```

3. **先 probe rig 能力**：新场景头一件事是查 source mesh 的面部 vertex groups 和骨结构，判断能做哪个级别。不要假设。

### 推荐路径（按难度升序）

1. **最简可行**：只做 あ/あ２/え/お 四条嘴系 morph（`head jaw` 单骨 X+rotation 可靠 work），明告用户其他未实现
2. **加眼睛**：まばたき / ウィンク / ウィンク右 走"程序化 vertex 位移"路径（landmark=目.L/R, 公式=按距离衰减推向眼中线），不碰 XPS 面部骨 quaternion 坑
3. **加情感（可选）**：笑い/にやり/困る 等复杂表情——要么 Surface Deform 桥接预制 template，要么 addon 提供 sculpt mode 跳转让用户手工雕

### 不要做的事（血泪教训）

- ❌ 不要手写 19 × 多骨 quaternion 硬凑，凭"理论应该"直觉大概率是错
- ❌ 不要跨尺度 + 跨锚点做 proximity transfer 而不先检查两边坐标对齐
- ❌ 不要同一回合叠加多个方案 (A + B + C)，一次一个，跑通可视觉验证再继续
- ❌ 用户说"都变形了" = **L2 级 root cause 信号**，别继续调参数，停下来怀疑方法本身
- ❌ 不要对未验证的假设做 scope 级别决策（例："XPS 面骨能做全 19 morph" 是假设，不是事实）

### Karpathy 4 原则的具体映射

- **Think Before Coding**: 每个 morph 先单独在 Blender 手动测骨 pose 能不能做出预期形状，再进 pipeline。**probe 一次比写 500 行废代码划算**
- **Simplicity First**: 能 5 个 morph 解决就不上 19；能不碰骨 pose 就用程序化位移
- **Surgical Changes**: 一次一方案，跑通视觉验证再继续；不是 A → B → C 叠加
- **Goal-Driven**: "嘴开多少像素算 pass" 这种具体 criteria 先拍板

---

## 当前仓库状态（给下一个 Claude 上下文）

**HEAD**: `ec32e7f` (Convert_to_MMD_claude)

**已实装代码**（都在仓库里，可用 / 可拆）：
- `operators/face_operator.py` `OBJECT_OT_clone_face_bones_from_target` — 从 target 补面部骨（方案 A）
- `operators/morph_operator.py` `OBJECT_OT_clone_morphs_from_target` — 克隆 bone/material/group morph
- `operators/morph_operator.py` `OBJECT_OT_bake_and_transfer_morphs` — bake + KDTree proximity transfer（方案 B）
- UI: option2「物理+表情」tab 有 ①②③ 三个按钮

**未实装**：
- XPS native recipe 方案只有设计（见 `doc/morph_clone_plan.md` 旧版，plan mode 里写过计划）
- 程序化 landmark 位移方案未尝试
- Surface Deform 桥接未尝试

**测试文件路径**（Mac 端）：
- Inase XPS: `/Users/bytedance/Downloads/demo/inase (purifier)_lezisell-A/xps.xps`
- Inase target PMX: `/Users/bytedance/Downloads/demo/Purifier Inase 18/Purifier Inase 18 None.pmx`
- Reika XPS (DAZ): `/Users/bytedance/Downloads/demo/Reika/xps.xps`
- Reika target PMX: `/Users/bytedance/Downloads/demo/Reika Shimohira 2 18/Reika Shimohira 2 18 None.pmx`
- VMD: `/Users/bytedance/Downloads/demo/永劫无间摇香2025.2.21by小王动画/永劫无间摇香2025.2.21.vmd`
- Preset: `xna_lara_Inase` / `daz_genesis8`

**开场先做**：
- Clear Blender 场景或 fresh import，避免 `.placeholder / .dummy_armature` 污染
- 读 `CLAUDE.md`（项目级）+ `doc/morph_clone_plan.md`（旧 plan）+ 本文档

**最重要的一条**：**不要相信我这个 Claude 当时说"成功了"**。我本次说过好几次"19/19 成功"，但实际视觉效果不对。每次都要用户自己截图看才发现。下次用户看到结果再算数，别自己宣布成功。
