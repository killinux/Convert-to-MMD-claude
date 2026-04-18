# Morph Synthesis Session Handoff — 2026-04-18

**给下一个 Claude:这份文档是本次 session 的完整交接。读完后你应当能立即 continue 工作,不需要从零重建 context。**

---

## TL;DR

- **Goal**: Convert_to_MMD_claude 转换后 `vertex_morphs = 0`,用户要生成 19 条标准 MMD 表情 morph,**全自动,无 artist 手动**
- **当前状态**: **Path D (程序化) 成功 19/19 条**,5 个 mesh 协同 (face + 双睫毛 + 眉毛 + 眼球)
- **HEAD commit** (Convert_to_MMD_claude repo): `cc3d7b6`
- **核心代码**: `experimental/morph_transfer_poc.py`
- **前 3 条 path (A/B/C) 全部失败**,复盘在 `doc/morph_transfer_paths_2026_04_18.md`
- **下一步**: user 要求"表情检查观测工具"(新 P0)、operator 化(P1)、~~补 ん(P2)~~ ✅ 已完成、Reika 跨模型(P3)

---

## 本 session 做了什么

### Phase 1-3: 跨 mesh transfer 全失败

| 路径 | 原理 | 结果 | Commit |
|---|---|---|---|
| **A** | TPS + IDW + Jacobian | upper lip offset 被 nose-region 稀释 → 撅嘴 | `a77e898` `233f8ad` |
| **B** | Sumner per-tri affine | 未尝试 (复杂度太高) | — |
| **C** | Blender SurfaceDeform + BVH + ray_cast | 上嘴唇暴力翻起 mesh tear | `9a9ec6a` `7e71e7b` `8f45eee` |

关键教训(每条都犯过):
1. **"数据 max offset 量级对"** 不代表视觉对 — 撅嘴/前突/翻唇的 max offset 都能 12mm
2. **必须 side-by-side 对比 template vs source 视觉**,不能只看单张 source
3. 不要相信 close-up zoom —zoom 太近会穿到 mesh 内部造成 "eyeball 穿透" 错觉

详细复盘在 `doc/morph_transfer_paths_2026_04_18.md`(路径 A/B/C/D/E 全对比)。

### Phase 4: Path D 程序化 (成功)

**原理**:不做跨 mesh transfer,直接用 source(Inase XPS)自身的 vertex group + 手工公式计算 per-vert offset。

**决策点**: user 明确选 **全自动路径**,不走 sculpt 半自动(Path E 备选)。

**核心代码**: `experimental/morph_transfer_poc.py`

```python
# 主入口
mt.bake_all_for_inase(face_mesh, eyelash_meshes, eyebrow_mesh, eyeball_mesh)

# 切换 slider 测试 (必须 synced 版本,别用 manual set)
mt.set_morph_synced([face, lash1, lash2, brow, eyeball], 'あ', 1.0)
```

**19 条 morph 覆盖**(MMD 标准全量):
- **嘴系 5**: あ/い/う/え/お ✅
- **嘴闭 1**: ん ✅ (commit `cc3d7b6`, 1.5mm 挤压)
- **嘴扩 2**: にやり / 激怒 ✅
- **眼皮 3**: まばたき / ウィンク / ウィンク右 ✅
- **眼扩 3**: 笑い / びっくり / じと目 ✅
- **眉系 5**: 困る / 怒り / 真面目 / 上 / 下 ✅

**5 mesh 协同**(Inase 特点):
- `24_0002-Object003` (5042 verts) — 主 face,所有 18 条
- `24_0004-Object004` (225 verts) — 睫毛 1,眼皮 3 + 眼扩 3
- `24_0007-Object007` (226 verts) — 睫毛 2,同上
- `7_0003-Object004` (704 verts) — 眉毛,眉系 5
- `24_0006-Object006` (484 verts) — 眼球,**Y+6mm recede** for まばたき/ウィンク/ウィンク右/笑い

---

## 关键坑 (必读,不要踩)

### 1. Template 选错毁整 session

**Purifier Inase 18 作 template (错)**:
- 它的 19 条是 **bone_morph** 不是 vertex_morph
- 'あ' bone_morph 只 Jaw 4.8° 旋转 + 嘴角 5.58mm
- bake 出来 shape key max 7.5mm — **template 本身就不是标准张嘴**
- 所以前两条 path 即使算法对也传递不出"大张嘴"

**YYB Miku v1.02 作 template (对)**:
- 路径 `/Users/bytedance/Downloads/demo/YYB式初音ミクver1.02/YYB式初音ミクv1.02.pmx`
- 110 vertex_morphs,'あ' max 13.61mm,标准大张嘴
- BowlRoll file/52777,免密下载

**教训**: Template 选择必须先 probe 数据(vertex_morph 数量 + 'あ' max offset ≥ 13mm),再动算法。

### 2. Blender 3.6.21 SurfaceDeform bind op bug

```python
bpy.ops.object.surfacedeform_bind(modifier='_morph_sd')
# 返回 {'FINISHED'} 但 sd.is_bound 永远 False
```

**绕过方案**: 自己写 BVH + barycentric 代替(已实现于 `transfer_morph_barycentric`)。但**最后证明**这条路仍然不 work (mesh tear),所以放弃。

### 3. 下眼皮不够覆盖眼球

**症状**: まばたき 时 face mesh eyelid 完全下来了,但**眼球底部从下方穿透**露白。

**Root cause** (verified by data):
- Inase face mesh 下眼皮 vg 最低 vert `z=1.6116`
- **眼球 mesh z 底 `z=1.6084`** — 低 3.2mm
- face mesh 在眼球底区域**没有 vert 可动**
- 不管 lower eyelid vg 位移多大都无效

**Fix** (`bake_eyeball_recede`):
- Eyeball mesh `24_0006` 加同名 shape key `Y+=6mm` (后退 into socket)
- 4 个闭眼类 morph 都必须: まばたき / ウィンク / ウィンク右 / 笑い
- **MMD 真实制作里也是这么做的**

**Known side effect** (✅ 已修复 commit `1eb2dbe`): 之前单眼 ウィンク 两只 eyeball 都后退。现在 `bake_eyeball_recede(side='left'|'right'|'both')` + `EYEBALL_SIDES` 映射,ウィンク 只后退 model-left (232 verts, x>0), ウィンク右 只后退 model-right (252 verts, x<0)。

### 4. set_morph_synced 必须用 (slider 漂移 bug)

**症状**: user 看到眼睛"还有瑕疵",其实是测试时 `24_0007` 残留上个 morph 的 slider (`ウィンク右=1 + じと目=1` 两者都活)。

**Fix**: 每次测试必须用 `mt.set_morph_synced(all_meshes, name, value)`,它会**先 reset 所有 mesh 的所有非 basis slider**,再 set target morph。

**写 operator 时必须内置这个逻辑**。

### 5. Inase 眉毛材质淡 → 对称 morph 视觉弱

眉毛 vg 权重 avg 0.3,加 max peak 10mm → 实际可见 3mm。Inase 眉毛 hair mesh 颜色淡,对称位移(上/下/真面目)脑自动 normalize → 视觉对比度低。

**Fix**: ×2-3 倍 amplitude (commit `16518ae`: 上 +10→+15mm, 下 -10→-15mm)。现在**下**显著(凶相),**上**仍 subtle。

**非对称 morph (困る / 怒り)** 视觉对比强,不需要这么大幅度。

### 6. 不要相信 close-up screenshot 的 "eyeball 穿透"

Zoom `view_distance < 0.03` 时摄像机几乎进到 mesh 内部,会从 face mesh 后方看到 eyeball mesh → 以为是 bug 其实是 view 角度错觉。**必须用 front ortho 0.08-0.12 view_distance** 正常距离。

---

## 文件 / Function / Commit 索引

### 代码

**主脚本**: `experimental/morph_transfer_poc.py`(session 初期作 PoC,保留)

关键 functions:
```python
# 通用 per-vertex offset 生成器
bake_programmatic_morph(src_mesh, morph_name, recipe)

# 18 条 recipe 字典
INASE_RECIPES  # dict of {morph_name: {vg_tuple: (x_mm, y_mm, z_mm)}}

# 5 mesh 编排,一键所有
bake_all_for_inase(face_mesh, eyelash_meshes, eyebrow_mesh, eyeball_mesh)

# 眼球 recede helper
bake_eyeball_recede(eyeball_mesh, morph_name, back_mm=6.0)
bake_eyeball_morphs_for_wink(eyeball_mesh)  # 批量 4 条

# 测试时必须用,防 slider 漂移
set_morph_synced(meshes_list, morph_name, value)

# Recipe 命名常量
LIP_LOWER, LIP_UPPER, JAW, CORNER_L, CORNER_R, CORNER_BOTH
EYELID_UPPER_L/R, EYELID_LOWER_L/R
BROW_L_INNER/MID/OUTER, BROW_R_*, BROW_ALL, BROW_INNER_BOTH, BROW_OUTER_BOTH
```

### Commit timeline (本 session, Convert_to_MMD_claude repo)

```
16518ae  Tune 5 weak morphs (にやり/激怒/真面目/上/下) — 当前 HEAD
9d19a56  Add set_morph_synced helper
95119f7  Add 5 more morphs (にやり/激怒/笑い/びっくり/じと目)
a9c6845  Tune brow amplitudes
158d667  Add bake_all_for_inase orchestrator (5 meshes)
f575f8d  Path D: eyebrow recipes 困る/怒り/真面目/上/下
8769af6  bake_eyeball_recede (解决下眼皮不够覆盖问题)
0b1641b  Eyelid lower +6→+9mm
30c5020  Eyelid upper -8/lower +6 asymmetric
7ee2d0e  Mouth recipes tune (い/う/え/お amplitude)
ee8d126  Path D generic bake_programmatic_morph + 5 mouth recipes
7f8e7a0  Path D: programmatic per-mesh 'あ' synthesis
803bbf8  Doc: record path E (sculpt) as future fallback
6605849  Record path C failure + path D plan
9a9ec6a  Path C: use .location+.scale instead of matrix_world (NaN fix)
8f45eee  Path C: ray_cast normal projection
7e71e7b  Path C: manual BVH+barycentric
bd14f20  Record 4 path options + path A failure
233f8ad  Path A: Sumner-style inverse TPS + Jacobian
a77e898  Path A: TPS first-pass
75f8de5  Add morph_transfer_poc.py (initial path A)
```

### 文档

- `doc/morph_transfer_paths_2026_04_18.md` — 4 条 path 对比 + A/B/C 失败复盘 + path D 原理
- `doc/morph_post_mortem_2026_04_18.md` — 前次 session(3 条方案 clone_bone/bake_transfer/XPS_recipe)失败复盘
- `doc/morph_session_handoff_2026_04_18.md` — **本文档** (session 交接)
- `TODO.md` P3 section — path D operator 化计划

### 测试资产

- **Source**: Inase XPS `/Users/bytedance/Downloads/demo/inase (purifier)_lezisell-A/xps.xps`
- **Template**: YYB Miku v1.02 `/Users/bytedance/Downloads/demo/YYB式初音ミクver1.02/YYB式初音ミクv1.02.pmx`
- **Ground truth**: Purifier Inase 18 PMX `/Users/bytedance/Downloads/demo/Purifier Inase 18/Purifier Inase 18 None.pmx`(作对比用,非实际 template)
- **Saved blend**: `/Users/bytedance/Downloads/morph_poc.blend`

---

## 快速重启 checklist (下次 session 必读)

### Step 1: pull 最新代码
```bash
# AWS side
cd /opt/mywork/mytest/Convert_to_MMD_claude && git pull
cd /opt/mywork/mytest/bl && git pull  # blender-relay 仓库

# Mac side (通过 exec)
BLENDER_RELAY_API_KEY=mysecretkey python cli/cli.py exec "
import subprocess
subprocess.run(['git', '-C', '/Users/bytedance/Library/Application Support/Blender/3.6/scripts/addons/Convert_to_MMD_claude', 'pull'])
"
```

### Step 2: Blender 加载测试 scene

如果 Blender scene 已存 `morph_poc.blend`(本 session 最后保存),load 即可。
如果从零:
```python
# 通过 cli.py exec
import bpy
bpy.ops.xps_tools.import_model(filepath='/Users/bytedance/Downloads/demo/inase (purifier)_lezisell-A/xps.xps')
bpy.ops.mmd_tools.import_model(filepath='/Users/bytedance/Downloads/demo/YYB式初音ミクver1.02/YYB式初音ミクv1.02.pmx', scale=0.08)
```

### Step 3: 运行 path D

```python
import sys
sys.path.insert(0, '/Users/bytedance/Library/Application Support/Blender/3.6/scripts/addons/Convert_to_MMD_claude/experimental')
import morph_transfer_poc as mt
import bpy

face = bpy.data.objects['24_0002-Object003_1.0_16.0_16.0']
lash1 = bpy.data.objects['24_0004-Object004_1.0_16.0_16.0']
lash2 = bpy.data.objects['24_0007-Object007_1.0_16.0_16.0']
brow = bpy.data.objects['7_0003-Object004_0.1_16.0_16.0']
eyeball = bpy.data.objects['24_0006-Object006_1.0_16.0_16.0']

mt.bake_all_for_inase(face, [lash1, lash2], brow, eyeball)
# 18 条 shape key 生成在 5 mesh 上

# 测试某条
mt.set_morph_synced([face, lash1, lash2, brow, eyeball], 'あ', 1.0)
```

### Step 4: 重读本文档 "关键坑" 章节

---

## 下一步 TODO

### ~~🆕 P0: 面部表情检查/观测工具~~ ✅ A + B + C 全部完成

- **Tool C** (commit `4b7188d`): `screenshot_all_morphs` + `generate_morph_html_report` → Mac `/tmp/morph_verify/index.html`。
- **Tool B** (commit `c7c36e3`): `verify_all_morphs(meshes)` 按 `INASE_MORPH_SPECS` (max_mm 上下限 + moved_verts 下限) 报违规。当前 19/19 pass。
- **Tool A** (commit `c7c36e3`): `MORPH_OT_verify_modal` 交互式 modal operator。用法:
  ```python
  mt.register_verify_ops()
  mt.start_verify_modal(meshes)  # meshes[0] 必须是 face mesh
  # 然后在 Blender 3D viewport 里按键: O=OK, X=Issue, N=Skip, ESC=Quit
  ```
  每按一次自动切到下一条,结束在 console 打报告。

**需求**:
1. **人工观测**: 用户能一条一条过每个 morph,判断视觉是否 OK
2. **自动快速测试**: Claude 能 programmatic 验证,不依赖人看每张截图

**建议设计**:

#### 工具 A: UI-driven 观测
- Convert_to_MMD_claude addon 新 operator `OBJECT_OT_verify_morphs`
- 按钮 "检查表情" — 点击后:
  - 循环所有已 bake 的 shape key
  - 每条 set slider=1.0 via `set_morph_synced`, 停留 1 秒(让 viewport 刷新)
  - 在一个小 popup panel 显示当前 morph 名 + [OK] / [有问题] button
  - 用户点 [OK] 继续下一条,点 [有问题] 标记并记录到列表
- 结束后输出 "18 条通过,0 条有问题" 或列出问题条目
- 实现 ~100 行,用 `bpy.ops.wm.window_new` or modal operator

#### 工具 B: 自动数据检查
- Function `verify_morph_data(src_mesh, morph_name, expected_spec)`:
  ```python
  expected_spec = {
      'あ': {
          'max_mm_range': (3.0, 8.0),        # 最大位移合理区间
          'moved_verts_min': 200,             # 至少 200 verts 动
          'affected_regions': {'mouth': True, 'nose': False, 'eye': False},  # 零污染 check
          'direction_hints': {'lower_lip_z': 'negative'},  # 下唇向下
      },
      ...
  }
  ```
- 自动跑所有 18 条,报告不符合 spec 的:
  - max 位移超出 expected range
  - 嘴类 morph 影响到 z>1.6 区(眼区污染)
  - 上/下唇 Z 方向错反
- 不用人眼,CI-friendly

#### 工具 C: Batch screenshot compare
- Function `screenshot_all_morphs(out_dir)`:
  - 对每条 morph, synced set 1.0, screenshot front ortho 固定 view
  - 输出 `/tmp/morph_verify/{morph_name}.png`
- 用户拿这些图一眼扫一遍,标记出错的
- 配合 `/doc/morph_reference_YYB.md` 给每条 morph 画 expected 形态示意

**推荐实施顺序**: C (最快出成果) → B (自动 regression) → A (UI 集成)。

C 可以直接改 session 里已有的 `OUT=/tmp/pathD_v2; for morph ...` bash loop 加 HTML report。

### P1: Operator 化 (已在 TODO.md P3 记录)

- 搬 `experimental/morph_transfer_poc.py` 相关函数到 `operators/morph_operator.py` + `presets/morph_recipes_inase.py`
- 新 operator `OBJECT_OT_generate_mmd_morphs_programmatic`
- UI 按钮在 option2「物理+表情」tab
- 自动 detect 5 mesh(按 vg 命名)
- 必须用 `set_morph_synced` 切换 slider

### ~~P2: 补 ん 到 19/19~~ ✅ 完成 (commit `cc3d7b6`)

初版用 handoff 给的 0.5mm 数值 (commit `9311ef5`) 实测**视觉零感知** —
Inase mesh 上 `max=0.50mm verts>0.5mm=0`。同 eyebrow 材质淡教训,上调 ×3 到 1.5mm 可见。

最终 recipe:
```python
'ん': {
    LIP_LOWER: (0, 0, +1.5),
    LIP_UPPER: (0, 0, -1.5),
    CORNER_L:  (-1.5, 0, 0),
    CORNER_R:  (+1.5, 0, 0),
},
```

测试数据: `max=1.50mm, 472 verts moved`。视觉 subtle 但可见(嘴唇挤压变薄 + 嘴角内收)。

### P3: Reika (DAZ) 跨模型

Reika XPS vg 命名**完全不同** (e.g. `lBrowInner` vs Inase `head eyebrow left 1`)。
需 `DAZ_RECIPES` preset,和 Inase 的 recipe 结构一样但 vg 映射不同。
参考 TODO.md P0 "面部骨清理支持 DAZ 命名"。

### ~~P4: 单眼 eyeball recede 优化~~ ✅ 完成 (commit `1eb2dbe`)

实现: `bake_eyeball_recede` 加 `side='both'|'left'|'right'` 参数,
`EYEBALL_SIDES = {'ウィンク':'left', 'ウィンク右':'right', 'まばたき':'both', '笑い':'both'}`,
`bake_eyeball_morphs_for_wink` 自动查表。Inase 眼球 mesh 天然以 x=0 对称分割 (232+252 verts, 无共享)。
视觉验证: 单眼 wink 时睁着那只眼球前凸饱满,不再后陷。

### P5: 眼球 morph 细节遗留 (2026-04-18, 回头再调)

P4 单眼 wink 主要问题已修,但 user 报告"眼球还是有问题"。未具体定位。待 P0 工具做好后系统性回看。

可能方向(下次排查参考):
- **笑い**: 当前 `back_mm=6.0` 和 まばたき 一样,crescent smile-eyes 可能希望 recede 量更小(只露月牙状眼球不要太后陷)
- **びっくり**: eyelid 上下各 ±3/-2mm,可能视觉不够惊讶,考虑 ×1.5
- **じと目**: eyelid 上 -5mm / 下 +2mm,narrow 效果 OK 但对比 target 参考图可能还要调
- **眼皮 shape** 本身(不是眼球): face mesh / 睫毛的 `まばたき` upper -8 / lower +9mm 是否最佳

修复入口: `experimental/morph_transfer_poc.py` `INASE_RECIPES` 的 eye 类条目 + `bake_eyeball_morphs_for_wink` 的 `back_mm`。

---

## 最后的话 (对下一个 Claude)

**Post-mortem 本身是这个项目最重要的文档**(3 份加起来):
- `doc/morph_post_mortem_2026_04_18.md` — 前次 session 踩的 3 条路
- `doc/morph_transfer_paths_2026_04_18.md` — 本 session 4 条 path 对比
- `doc/morph_session_handoff_2026_04_18.md` — 本文档

**不要**:
- 跳过读文档直接 code
- 假设算法对就 claim 成功 — 必须视觉 + 对照 template 验证
- 一次扩 19 条再测 — 必须 1 条端到端过了再扩
- 信任 close-up view (view_distance<0.03 会穿透)
- 在 test 里手动 set slider — 一律用 `set_morph_synced`

**要**:
- 先 side-by-side template vs source 视觉对比
- 数据指标(max mm, region distribution)只是 sanity check,不代表 pass
- 每次 tune 参数后 rebake + 重截图
- commit 信息写清"why",不光"what"(未来 grep 容易)
- 用户说"X 有问题" 优先相信用户,反复检查而不是 defend

祝好运 🫡
