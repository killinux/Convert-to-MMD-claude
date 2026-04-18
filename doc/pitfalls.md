# 踩坑指南 (Morph + 转换流程)

**目的**: 记录已尝试、已证明**不行**的方案 + 背后的原因,避免下次重复踩同样的坑。

每次发现新的"行不通"的做法,把它追加到这里。格式:
- **方案名** (commit / 日期)
- **原理**: 一句话讲思路
- **失败表现**: 视觉 / 数据上怎么错的
- **根因**: 为什么错
- **替代**: 现在用什么方案

---

## Morph 合成 / 传递(Path A/B/C vs D)

### 背景: 为什么会有这么多失败方案

初版 UI 曾有「表情 Morph ①→②→③」三连按钮,许多人误以为是**三种独立方案**,其实是 **同一方案的 3 个步骤**:

| 步骤 | 做什么 | 文件 | 状态 |
|---|---|---|---|
| ① `clone_face_bones_from_target` | 从 target PMX 克隆 `Jaw Bone / QQ*` 等**驱动骨**到源模型 | `face_operator.py` | 本身能用,但**对 Path D 冗余** |
| ② `clone_morphs_from_target` | 克隆 target 的 **bone_morph / material_morph / group_morph** (不碰 vertex_morph) | `morph_operator.py` | 本身能用,但**对 Path D 冗余** |
| ③ `bake_and_transfer_morphs` | KDTree 近邻把 target vertex 偏移**传到**源 mesh | `morph_operator.py` | **视觉错,已弃用** |

Path D (程序化合成,现在的 ④ 按钮) **完全不走这条路** — 不需要 target PMX,直接用源 mesh 自己的 vertex group + 公式化 recipe 合成 19 条标准表情。

2026-04-18 彻底清理:①②③ 代码+按钮全删,只留 ④ + 3 个验证工具。

---

### ❌ Path A — TPS + IDW + Jacobian transfer (commit `a77e898` / `233f8ad`)

- **原理**: 拟合 thin-plate-spline 从 tpl landmark → src landmark,用 IDW 混合 tpl offset,本地 Jacobian 把方向从 tpl 空间变到 src 空间
- **失败表现**: 'あ' 张嘴时**上唇偏移被鼻区稀释** → 撅嘴畸形,不是张嘴
- **根因**: IDW 用 k=4 混合近邻 tpl vert 的 offset,但**鼻区 vert 也在 k 近邻里**,它们的 offset 接近 0 → 稀释了上唇本该有的大偏移。加 face mask 无效(mask 粒度太粗)。
- **替代**: 放弃跨 mesh transfer,改用 Path D 程序化合成

### ❌ Path B — Sumner per-triangle affine deformation transfer

- **原理**: Sumner 2004 的三角形仿射变换传递算法 (每三角一个 3x3 仿射矩阵)
- **失败表现**: 未真跑,复杂度远高于 Path A 收益未见得更好
- **不做原因**: 算法复杂,A 已证基本思路(per-vert offset 混合)视觉不对;per-tri 也绕不开跨 mesh 拓扑不一致的根问题

### ❌ Path C — Blender SurfaceDeform + BVH + ray_cast (commit `9a9ec6a` / `7e71e7b` / `8f45eee`)

- **原理**: 用 Blender 内置 Surface Deform modifier (或手写 BVH+barycentric 复刻) 把 src mesh 绑定到 tpl 表面,激活 tpl 的 shape key 读 deformed src mesh
- **失败表现**: **上嘴唇暴力翻起,mesh tear** (撕裂)
- **根因**:
  1. Blender 3.6.21 `surfacedeform_bind` op 有 bug,返回 `{'FINISHED'}` 但 `sd.is_bound` 永远 `False`
  2. 手写 BVH 版本: src 上唇 vert 绑到 tpl 嘴唇三角,但 tpl 嘴唇厚度、贴合方向和 src 不一致,张嘴时 tpl 嘴唇的 normal 方向把 src 上唇翻起来
- **替代**: Path D

### ❌ KDTree 近邻 transfer (旧 ③ 按钮, 2025 实现)

- **原理**: head-local 空间里用 KDTree 找 k 最近邻 tpl vert,加权平均 tpl offset 应用到 src
- **失败表现**: 同 Path A — offset 被近邻稀释,视觉粘糊
- **根因**: 和 Path A 同类 — 近邻加权天然会把局部的大变形摊薄成全局平均
- **替代**: Path D

### ✅ Path D — 程序化 per-mesh 合成 (commit `7f8e7a0` 起, 当前方案)

- **原理**: 不做 transfer。用**源模型自己的 vertex group**(Inase XPS `head lip lower*` 等)+ 手工 recipe (每条 morph 定义 vg → 毫米级 xyz offset),批量烘焙成 shape key
- **为什么对**: 源 mesh 自己的 vg 天然精准命中嘴唇/眼皮/眉毛区,不需要跨 mesh 插值 → 无稀释无 tear
- **代价**: 需要**知道源模型的 vg 命名惯例**。Inase XPS 是标准 XPS-Canon 命名,已有 recipe (`INASE_RECIPES`)。DAZ / Reika 命名不同,未来要做新 preset。

---

## Morph 模板选择

### ❌ Purifier Inase 18 当 template (2026-04-18 early)

- **错在哪**: 它的 19 条"表情"是 **bone_morph 不是 vertex_morph** — 'あ' 只让 Jaw 转 4.8° + 嘴角 5.58mm,bake 成 shape key max 只有 7.5mm。**template 本身视觉张嘴就不够**。
- **教训**: 选 template 前必须 probe 数据 — vertex_morph 数量 + 'あ' max offset ≥ 13mm 才能算"标准大张嘴"
- **正确 template**: YYB Miku v1.02 (`/Users/bytedance/Downloads/demo/YYB式初音ミクver1.02/`),110 vertex_morph,'あ' max 13.61mm。BowlRoll file/52777 免密下载

(注: Path D 其实根本不需要 template,这一节只针对未来再用 transfer 时参考)

---

## 视觉判断的陷阱

### ❌ 相信 close-up zoom 判断"眼球穿透"

- **表现**: zoom 到 `view_distance < 0.03` 时看到 "eyeball 从 face 后方露出",以为是 bug
- **真相**: 摄像机已经穿进 face mesh 内部,从背面看 eyeball → 角度错觉,不是 bug
- **纠正**: 固定用 **front ortho 0.08-0.12 view_distance** 判断

### ❌ 只看"数据 max offset 对就以为视觉对"

- **表现**: 撅嘴 / 翻唇 / 大张嘴 max offset 都能算到 12mm,数据指标都 pass
- **纠正**: 必须 **side-by-side template vs source 视觉对比**,max mm 只是 sanity check

### ❌ `bpy.ops.screen.screenshot_area` 没 context override 静默失败

- **表现**: 文件只有 243 字节,空 PNG
- **替代**: 用 `bpy.ops.render.opengl(write_still=True)` + `temp_override(area=...)`,或直接 cli.py 的 screenshot 命令

---

## Slider / Shape key 测试

### ❌ 手动 `mesh.data.shape_keys.key_blocks['X'].value = 1.0` 切 morph

- **问题**: 多 mesh 协同 (face + 睫毛 + 眉毛 + 眼球) 时,上一条 morph 的 slider 没归零,两条 morph 叠加成看起来像第 3 条的样子 → 误以为当前 morph 有 bug
- **例**: 测 じと目 时 ウィンク右 的 slider 还在 1.0,`24_0007` 双 morph 叠加 → 以为 じと目 眼皮有 bug
- **正确做法**: 用 `set_morph_synced(meshes, name, value)` — 先清掉每个 mesh 所有非 basis slider 再 set target

### ❌ 眼球单侧 wink 两只眼都后退 6mm

- **表现**: ウィンク (model-left wink) 时,model-right 眼球也跟着 Y+=6mm 后陷,睁着那只眼看起来空洞
- **根因**: `bake_eyeball_recede` 无差别对所有 eyeball verts 加 offset
- **修复** (commit `1eb2dbe`): 加 `side='left'|'right'|'both'` 参数 + `EYEBALL_SIDES` 表。Inase 眼球 mesh 以 x=0 干净对称分割(232 + 252 verts, 无共享)

### ❌ 弱视觉 morph 只给 "理论合理" 的毫米数 (commit `9311ef5` 初版 ん)

- **表现**: ん morph 最大 offset 0.5mm,实际肉眼零感知 (`verts>0.5mm=0`)
- **根因**: Inase 嘴唇/眉毛材质对比度低,0.5mm 位移视觉上完全看不到
- **规则**: 弱视觉 morph 的 amplitude **至少 ×2-3 倍** 理论值。ん 从 0.5mm 提到 1.5mm 后可见(commit `cc3d7b6`)
- **参考**: 眉毛 morph 同理 — Inase 眉毛材质淡,对称 morph (上/下) 需要 ×3 才够

---

## 自动检测 mesh

### ❌ 眉毛 mesh 同时含 eyelid vg → 按 `has_brow AND NOT has_eyelid` 漏掉

- **表现**: `find_inase_meshes` 返回 None,brow 槽位空
- **根因**: Inase 眉毛 mesh (`7_0003`) 有 11 个 vg,既含 `head eyebrow*` 也含 `head eyelid*` (眼皮延伸到眉区)
- **修复** (commit `33cd69a`): 按优先级/特异性排序,`has_brow AND NOT has_lip` 即可,不排除 eyelid

### ❌ YYB Miku template 被误判成眼球

- **表现**: `find_inase_meshes` 把 YYB 整个脸 mesh 认成 eyeball,因为它有 まばたき shape key + 无 Inase 脸 vg
- **修复** (commit `bc08499`): 加 `len(vg_names) < 10` 过滤,template 通常 vg 上百个

### ❌ 牙齿 mesh 被误判成 face

- **表现**: 干净重测时 `find_inase_meshes` 把 `24_0005` (tooth) 当成 face → 19 条 morph 全烘在牙齿上,真 face (`24_0002`) 没 shape key。视觉上脸完全不动
- **根因**: 牙齿 mesh 为了跟着嘴唇动,也 rig 了 `head lip*` vg。旧检测 `if has_lip: face = o` 把牙齿当 face,且迭代顺序让 24_0005 覆盖 24_0002
- **修复** (2026-04-18): face 要求**同时有 lip + eyelid + eyebrow** 三类 vg。只有真 face mesh 三者全含,牙齿 / 睫毛 / 眉都只占其一

### ❌ 一键转换后 ④ 合成 morph 找不到 mesh

- **表现**: 干净 Blender → 导 XPS → 一键转换 (1→11) → 切 option2 点 ④ → `find_inase_meshes` 返回 NONE,报"未找到 Inase 5 个脸部 mesh"
- **根因**: step 6 `cleanup_face_bones` **把 `head lip*`/`head eyelid*`/`head eyebrow*` vg 合并到 頭 + 删除源骨** → Path D recipe 依赖的 vg 全没了
- **次要根因**: 旧版 `find_inase_meshes` 用 `まばたき` shape key 探测 eyeball,但新 scene 还没 bake 过 morph,探测必然失败
- **修复** (2026-04-18 后续):
  1. `find_inase_meshes` 改用**眼骨 vg** (`目.L`/`目.R` 或 XPS 原名 `head eyeball *`) 探测 eyeball,不依赖 shape key
  2. `one_click_convert` 的 pipeline **在 step 5 和 step 6 之间插入 `synth_vertex_morphs`**,保证 face vgs 还在时完成 bake
- **规则**: Path D 合成 morph 必须**在 cleanup_face_bones 之前**运行。若用户自己拆步骤跑,注意这个顺序

---

## 怎么维护这份文档

- 每次发现新的"做错了"的方案(无论是算法、UI、API 用法),**当场追加到这里**
- 格式统一:方案名 (commit) → 原理 → 失败表现 → 根因 → 替代
- 原因 / 根因部分**写清楚 "为什么错"**,不只是"不 work" — 下次别人才能判断相似的做法会不会一样错
- 这不是历史记录,是**活的指南**。如果某个"错"后来被证明其实只是 param 调错了(不是根本错),也要回来纠正
