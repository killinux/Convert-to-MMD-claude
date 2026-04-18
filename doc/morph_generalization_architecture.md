# Morph 合成通用化架构 (未实施, 设计中 — 2026-04-18)

## 目标

让 **任意 XPS 源模型** 都能 Path D 程序化合成 19 条标准 MMD 表情，不只是 Inase。

## 当前状态 (HEAD `bc130ee`)

- **骨骼 pipeline 完全通用**: Inase (XNA Lara) 和 Reika (DAZ Genesis 8) 都能跑通 step 1→12,
  converted PMX 的骨骼、权重、VMD 姿态都与 target 对齐
- **面部骨清理通用** (commit `bc130ee`): cleanup_face_bones 改成 walk `頭` subtree + keep list, Reika 81 残留 → 0
- **morph 合成**: 只 Inase 能 work。DAZ 跑 `synth_vertex_morphs` 会 CANCEL (DAZ 无 `head lip*` vg 系列)
  - `experimental/morph_transfer_poc.py::INASE_RECIPES` 硬编码 XPS Inase vg 名
  - Reika 转出的 PMX: 0 vertex_morphs, 0 bone_morphs

## 已排除的方案 (不要再走)

见 `doc/morph_post_mortem_2026_04_18.md` 完整踩坑:

- **Path A** (clone face bones from target): 骨被克隆但无权重绑 → 视觉无变化
- **Path B** (KDTree proximity bake+transfer): 源/目标锚点对不齐, 嘴 morph 拖到眼睛
- **Path C** (eyelid quaternion 手写): 几何上不可能凭直觉算准

Path D (programmatic per-mesh formulas) 是唯一成功路径, Inase 19/19 验证通过。

## 下一步要做的: Path D 通用化

核心思路: **把 recipe 从硬编码 vg 名抽成 semantic slot**, 每个 rig 提供 `slot → vg_names` 映射。

### 1. Semantic slot 定义

面部区域按"功能"而非"命名"描述:

| Slot | 含义 | 备注 |
|------|------|------|
| `lip.upper.{L,M,R}` | 上唇左/中/右 | M = middle (中间一小块) |
| `lip.lower.{L,M,R}` | 下唇左/中/右 | |
| `lip.corner.{L,R}` | 嘴角 | |
| `eyelid.upper.{L,R}` | 上眼皮 | |
| `eyelid.lower.{L,R}` | 下眼皮 | |
| `brow.{inner,mid,outer}.{L,R}` | 眉 | 3 段 × 2 侧 |
| `jaw` | 下颌 | single (没 L/R) |
| `cheek.{L,R}` | 颊 | POC 可省 |
| `eyeball` | 眼球 mesh 本体 | 无 vg, 用 recede helper |

通配 `.*` 支持 "一次写多个" (`lip.lower.*` = L+M+R)。

### 2. Rig adapter (每格式一份映射)

新文件 `experimental/morph_rigs.py`:

```python
XPS_INASE_MAP = {
    'lip.upper.L': ['head lip upper left'],
    'lip.upper.M': ['head lip upper middle'],
    'lip.upper.R': ['head lip upper right'],
    'lip.lower.L': ['head lip lower left'],
    'lip.lower.M': ['head lip lower middle'],
    'lip.lower.R': ['head lip lower right'],
    'lip.corner.L': ['head mouth corner left'],
    'lip.corner.R': ['head mouth corner right'],
    'eyelid.upper.L': ['head eyelid upper left'],
    'eyelid.upper.R': ['head eyelid upper right'],
    'eyelid.lower.L': ['head eyelid lower left'],
    'eyelid.lower.R': ['head eyelid lower right'],
    'brow.inner.L': ['head eyebrow left 1'],
    'brow.mid.L':   ['head eyebrow left 2'],
    'brow.outer.L': ['head eyebrow left 3'],
    'brow.inner.R': ['head eyebrow right 1'],
    'brow.mid.R':   ['head eyebrow right 2'],
    'brow.outer.R': ['head eyebrow right 3'],
    'jaw': ['head jaw'],
    'cheek.L': ['head cheek left 1'],
    'cheek.R': ['head cheek right 1'],
    # 'eyeball' 不在 vg map 里, 由 mesh detection 提供
}

DAZ_G8_MAP = {
    # DAZ 比 XPS 分得更细, 合并 Inner+Outer 代表 L/R
    'lip.upper.L': ['lLipUpperInner', 'lLipUpperOuter'],
    'lip.upper.M': ['LipUpperMiddle'],
    'lip.upper.R': ['rLipUpperInner', 'rLipUpperOuter'],
    'lip.lower.L': ['lLipLowerInner', 'lLipLowerOuter'],
    'lip.lower.M': ['LipLowerMiddle'],
    'lip.lower.R': ['rLipLowerInner', 'rLipLowerOuter'],
    'lip.corner.L': ['lLipCorner'],
    'lip.corner.R': ['rLipCorner'],
    'eyelid.upper.L': ['lEyelidUpper', 'lEyelidUpperInner', 'lEyelidUpperOuter'],
    'eyelid.upper.R': ['rEyelidUpper', 'rEyelidUpperInner', 'rEyelidUpperOuter'],
    'eyelid.lower.L': ['lEyelidLower', 'lEyelidLowerInner', 'lEyelidLowerOuter'],
    'eyelid.lower.R': ['rEyelidLower', 'rEyelidLowerInner', 'rEyelidLowerOuter'],
    'brow.inner.L': ['lBrowInner'],
    'brow.mid.L':   ['lBrowMid'],
    'brow.outer.L': ['lBrowOuter'],
    'brow.inner.R': ['rBrowInner'],
    'brow.mid.R':   ['rBrowMid'],
    'brow.outer.R': ['rBrowOuter'],
    'jaw': ['lowerJaw'],
    'cheek.L': ['lCheekUpper', 'lCheekLower'],
    'cheek.R': ['rCheekUpper', 'rCheekLower'],
}

RIG_MAPS = {
    'xps_inase': XPS_INASE_MAP,
    'daz_g8':    DAZ_G8_MAP,
    # 未来扩展: mixamo / vroid / bip_001 / ...
}
```

### 3. Recipe 重写成 slot 形式 (共享一份)

```python
UNIVERSAL_RECIPES = {
    'あ': {
        'jaw':           (0,  1, -3),
        'lip.lower.*':   (0,  2, -5),
        'lip.corner.*':  (0,  0, -2),
        'lip.upper.*':   (0,  0, +0.5),
    },
    'い': {
        'lip.corner.L':  (+8, 0, 0),
        'lip.corner.R':  (-8, 0, 0),
        'lip.lower.*':   (0,  0, +1),
        'lip.upper.*':   (0,  0, -1),
    },
    # ... 其余 17 条同理, 参照现有 INASE_RECIPES 直译
}
```

通配展开规则:
- `lip.lower.*` → `lip.lower.L + lip.lower.M + lip.lower.R`
- `brow.*.L` → `brow.inner.L + brow.mid.L + brow.outer.L`
- `brow.*.*` → 全部 6 个

### 4. 改 bake 函数

```python
def bake_programmatic_morph(src_mesh, morph_name, recipe, rig_map):
    """recipe 用 slot 名; rig_map 把 slot 展开成 vg_names."""
    expanded = {}
    for slot_pattern, offset in recipe.items():
        slots = _expand_slot_pattern(slot_pattern)  # 通配展开
        vg_names = []
        for slot in slots:
            vg_names += rig_map.get(slot, [])
        if vg_names:
            expanded[tuple(vg_names)] = offset
    # 往下复用现有逻辑
    ...
```

### 5. Rig 自动检测

```python
def detect_rig():
    """扫描 scene 里所有 mesh 的 vg 签名, 猜 rig 类型."""
    all_vgs = set()
    for o in bpy.data.objects:
        if o.type == 'MESH':
            all_vgs |= {vg.name for vg in o.vertex_groups}
    if 'head lip lower middle' in all_vgs:
        return 'xps_inase'
    if 'LipLowerMiddle' in all_vgs:
        return 'daz_g8'
    return None
```

### 6. Mesh 角色泛化

Inase 5 mesh (face/lash×2/brow/eyeball) vs DAZ 4 mesh (face/mouth/lashes/eyes), **结构不同**。改成按角色检测:

```python
MESH_ROLES = {
    'primary_face': '有 lip+eyelid+brow 大部分 vg (脸皮)',
    'mouth_interior': '只 lip 无 eyelid/brow (齿/舌 mesh, DAZ 有独立)',
    'eyelashes': '只有 eyelid vg',
    'eyebrow': '只有 brow vg (Inase 独立, DAZ 无)',
    'eyeball': '只 eye bone vg, vg 总数 < 5',
}
```

`find_meshes_by_role(rig_map)` 用 rig_map 里的 slot 反查 vg, 按规则分桶。返回 `{role: [mesh, ...]}`, 允许 role 为空 (DAZ 的 eyebrow = [])。

### 7. bake 分发器

```python
def bake_all_universal(meshes_by_role, rig_map, recipes=UNIVERSAL_RECIPES):
    # primary_face 吃全部 recipe
    for m in meshes_by_role.get('primary_face', []):
        bake_recipes(m, recipes, rig_map)
    # mouth_interior 吃 mouth subset (DAZ 的 teeth mesh 也要唇形)
    mouth_subset = {n: r for n, r in recipes.items() if n in MOUTH_MORPH_NAMES}
    for m in meshes_by_role.get('mouth_interior', []):
        bake_recipes(m, mouth_subset, rig_map)
    # eyelashes 吃 eyelid subset
    eyelid_subset = {n: r for n, r in recipes.items() if n in EYELID_MORPH_NAMES}
    for m in meshes_by_role.get('eyelashes', []):
        bake_recipes(m, eyelid_subset, rig_map)
    # eyebrow (如果存在)
    brow_subset = {n: r for n, r in recipes.items() if n in BROW_MORPH_NAMES}
    for m in meshes_by_role.get('eyebrow', []):
        bake_recipes(m, brow_subset, rig_map)
    # eyeball recede (不用 rig_map)
    for m in meshes_by_role.get('eyeball', []):
        bake_eyeball_morphs_for_wink(m)
```

### 8. 修改 synth operator

```python
def execute(self, context):
    rig = detect_rig()
    if rig is None:
        self.report({'ERROR'}, "未识别 rig 类型, 需要在 morph_rigs.py 加 map")
        return {'CANCELLED'}
    rig_map = RIG_MAPS[rig]
    meshes_by_role = find_meshes_by_role(rig_map)
    if not meshes_by_role.get('primary_face'):
        self.report({'ERROR'}, "未找到 primary_face mesh")
        return {'CANCELLED'}
    bake_all_universal(meshes_by_role, rig_map, UNIVERSAL_RECIPES)
    ...
```

## 实施顺序 (2026-04-18 晚 S1+S2+S3 完成)

1. **文档 + push 本次完成点** (本文档 + HEAD `bc130ee`) — 这样回滚点明确 ✅
2. **refactor Path D 成 slot-based**, Inase 回归零变化 ✅ HEAD `7591eca`
3. **加 DAZ_G8_MAP + Reika POC**: 嘴 5 条 (あ/い/う/え/お) + まばたき ✅ HEAD `bf823e0`
4. **验证**: Reika XPS → synth → 截图 → 肉眼确认 5 条嘴 + 闭眼 OK ✅ (9 条抽检正常)
5. **补 DAZ 剩余 13 条**: 调参数, 用批量截图 (Tool C) 校验 ✅
   — 实际无需补: UNIVERSAL_RECIPES 里 19 条全部 rig-agnostic, Reika 一次 bake 全通过
   — Tool B Spec 19/19 pass; Tool C 抽检 9 条语义正确 (あ嘴开/い横开/う噘/眨眼/眉动)
6. **完整 pipeline export 验证** ✅ HEAD `0538433`
   — 跑完 step 7→12, mmd_root 注册 19 vertex_morphs
   — 新增 `apply_morph_categories`: 8 MOUTH + 6 EYE + 5 EYEBROW (不再全 OTHER)
   — PMX export 9.91 MB, 14/14 抽检 morph 名在 binary 内
   — VMD 导入 OK: 9037 bone frames + 73 morph frames, まばたき 峰值 frame 46 视觉闭眼正确
7. **加 Mixamo/VRoid**: 按需 — 未做

## S2/S3 实测数据

- Reika DAZ brow (`上`/`下`) max 15.0mm, 比 Inase (9.6mm) 偏夸张
  — 原因: DAZ eyelid/lip 每 slot 多 sub-vg (UpperInner/UpperOuter) sum+clamp 到 1.0
  — 影响: 实际 VMD 帧很少用 1.0, 0.3-0.7 区间效果自然, 不 block 使用
  — 如需调: `DAZ_G8_MAP` eyelid/brow slot 保留主 vg 去掉 sub (建议 #2, 保持 sum 语义)
- mouth_interior (4_Mouth) 不 bake 仍看起来正常: 张嘴时牙齿静态保留, 与 MMD 标准一致
- VMD 动画绑定正确: 18 个 morph fcurve 名字全部匹配 mmd_root.vertex_morphs

## 未决

- **坐标系**: XPS 导入的 Inase 用 +Y = 向后 (facing -Y)。DAZ XPS 导入是否同? Reika 实测 armature Y 轴方向正确 (腕.L 对齐过), 应同。但 recipe 里 ±Z 是上下, ±Y 是前后, 可能需要小幅调参
- **mm 偏移单位**: DAZ 和 XPS scale 是否一致? Inase body_h ~ 1.6m, Reika body_h 实测未验证但转换后 scale ratio 正常, 猜测相同 scale
- **Cheek**: POC 先不用, 后期如需 "ふくらむ" 类 morph 再加
- **Brow mesh (DAZ 无)**: 眉 morph 直接 bake 在 primary_face 上 (DAZ 的 Face mesh 有 brow vg)
- **Mouth interior (DAZ 特有)**: Inase 的 teeth mesh 也 rig 到 lip, 但没必要 bake 嘴形 morph (牙齿不跟唇动)。要不要给 DAZ 的 `4_Mouth` 也 bake? 取决于 mesh 顶点是否跟嘴唇一起动画, **实测再说**

## 相关文件

- `experimental/morph_transfer_poc.py` — 当前 Path D 实现 (待 refactor)
- `operators/morph_synth_operator.py` — operator wrapper
- `doc/morph_post_mortem_2026_04_18.md` — Path A/B/C 失败复盘
- `doc/morph_session_handoff_2026_04_18.md` — Inase Path D 成功细节
- `doc/morph_transfer_paths_2026_04_18.md` — 所有失败路径记录

## 测试文件路径 (Mac)

- Inase XPS: `/Users/bytedance/Downloads/demo/inase (purifier)_lezisell-A/xps.xps`
- Inase target: `/Users/bytedance/Downloads/demo/Purifier Inase 18/Purifier Inase 18 None.pmx`
- Reika XPS: `/Users/bytedance/Downloads/demo/Reika/xps.xps`
- Reika target: `/Users/bytedance/Downloads/demo/Reika Shimohira 2 18/Reika Shimohira 2 18 None.pmx`
- VMD 共用: `/Users/bytedance/Downloads/demo/永劫无间摇香2025.2.21by小王动画/永劫无间摇香2025.2.21.vmd`

## 恢复点 (本次 session 成果)

- HEAD `bc130ee`: cleanup_face_bones 通用化, Reika 81 → 0 残留, Inase 回归 OK
- HEAD `247287a`: fix toggle_rigid_visibility (用 mmd_root flag 而非 hide_viewport)
- HEAD `7c51fe9`: one_click_convert 加 stop_at_morph 选项 (部分 1→6 给 morph 验证)
- HEAD `be74ed3`: UI 加 mesh → parent armature walk, 选 mesh 时 panel 不消失
- HEAD `bc130ee` 是 morph 通用化之前的稳定 checkpoint — 回滚用这个
- HEAD `7591eca` S1: slot-based Path D, Inase bit-identical
- HEAD `bf823e0` S2: DAZ_G8_MAP + detect_rig signature
- HEAD `0538433` S3: `apply_morph_categories` post-convert, Reika 完整 pipeline + PMX + VMD 验证通过
