# Morph Transfer 路径复盘 (2026-04-18)

**给下一个 Claude 会话 / 未来的我**: 面部表情跨 mesh 迁移有四条主流路径。本文记录每条路径的原理、已踩的坑、未踩但预期的坑,避免重复试错。

## 目标回顾

**任务**: 给任意 XPS 源(如 Inase)自动生成 MMD 标准 19 条 vertex_morph(あ/い/う/え/お/まばたき/笑い...),从一个 "template mesh with morphs" 传递到 "source mesh without morphs"。

**约束**:
- 必须无 target PMX 也可用(源是 XPS)
- 形状对 + 周围零污染 (严格视觉标准)
- 两边 mesh 几何差异大(不同 character、不同拓扑、不同脸型比例)

## 路径 A: TPS + IDW + Jacobian (Sumner-lite) — ❌ 已证失败

**原理**:
1. 两边各放 N 个解剖 landmark (eye corners, nose tip, mouth corners, chin)
2. TPS biharmonic warp: landmark-driven deformation `tpl_space → src_space`
3. Per src vert: inverse-warp to tpl space → KDTree find nearest tpl verts → IDW-blend their offset → transform via local TPS Jacobian → write src offset

**已尝试 (commit `a77e898` → `233f8ad`)**:
- Purifier Inase 18 作 template (bone_morph): template 本身 'あ' 极温和 (7mm),不代表标准 MMD
- YYB Miku v1.02 作 template (110 vertex_morphs): template 'あ' 标准大张嘴 (13.6mm max)
- Forward warp 版: upper lip Z = -0.65mm (远低于 YYB 的 -1.90mm)
- Inverse TPS + Jacobian 版: upper lip Z = -1.05mm (+61% 改善,仍低)
- **视觉失败**: 两版结果都是"撅嘴"(lip pucker),**非**张嘴

**失败根因**:
1. TPS 在 non-landmark 区域是 scalar-per-axis 插值,不保几何一致性
2. 两边脸型 Y 轴 (depth) 差异大,Jacobian 各向异性把 Y offset 放大
3. IDW blend 多个 tpl verts offset 时,upper lip vert 可能被 nose-region offset 稀释
4. SRC lower lip Y+6.6mm (向后) 过大,挤压嘴唇形成 pucker 而非 open

**教训**:
- TPS+IDW+Jacobian 是学术 deformation transfer 的"简化版",但对强几何差异的脸不够
- **数据指标 OK 但视觉失败**的情况反复出现 → 不要相信 mag/region 数据,**必须视觉验证**
- Side-by-side tpl vs src at same slider 是唯一靠谱的 verification

**这条路径不建议再尝试**,除非愿意做 Sumner 2004 full per-triangle affine transfer (300+ 行,复杂)。

## 路径 B: Sumner 2004 Deformation Transfer — ⚠️ 未尝试,复杂

**原理**: 建立 template ↔ source 的 triangle-to-triangle 对应;对 template 每个三角面计算 deformation gradient (3x3 affine transform);把该 gradient 应用到对应 source triangle。

**实现要点**:
- 需要 template-source correspondence map (每个 src triangle 对应哪个 tpl triangle)
- Solve linear system 重建 deformed src vertex positions
- 典型实现 ~300-500 行 numpy

**预期坑**:
- Correspondence map 本身是研究难题 (non-rigid registration)
- 两边 mesh triangle 数差 10x+ 时,1-to-many map 效果存疑
- **未尝试,但学术证明可行**

## 路径 C: Blender Surface Deform Modifier — ⏳ 当前尝试

**原理**: Blender 内建 SurfaceDeform modifier 能把 mesh A 的 verts bind 到 mesh B 的 surface (通过 barycentric coords + normal projection)。B 任意变形 → A 自动跟随。

**实现步骤**:
1. Align YYB mesh 到 Inase face 同一位置(uniform scale + translate,用 eye+nose landmarks)
2. Inase face mesh 加 SurfaceDeform modifier, target = YYB mesh
3. Bind (在两边都 neutral 时)
4. 对每条 morph: YYB slider=1.0 → depsgraph evaluate Inase → 读变形后 vert 位置 → 写 shape key → reset slider
5. Remove/disable modifier

**预期优点**:
- 30 行代码,不用写 TPS/IDW/Jacobian
- Blender C 代码,bind 质量高
- 工业界 Wrap3 的 Blender 简化版

**预期坑**:
- **Alignment**: YYB face 必须移到和 Inase face 同位置 + 同尺度,否则 SD bind 到 YYB 其他部位 (耳/发)
- **Triangle flow**: 两边 mesh 拓扑差大时,SD bind 的 triangle 对应可能错
- **Inner mouth**: YYB 有口腔内部 geometry (齿/舌),SD 可能 bind 到错误的 "前后面"
- **Shape key source**: SD bind target mesh 的 evaluated state,shape key 必须 evaluate 到 mesh 才生效
- **"Falloff"/"Strength"** 参数需调

**如果失败,症状预期**:
- Bind 失败 (0 verts bound) → alignment 问题
- 嘴唇 bind 到鼻 → alignment 偏
- 形变量级对,但有 glitch 区 → triangle 拓扑 mismatch

## 路径 D: 程序化 Landmark 位移 — ⏸ Fallback

**原理**: 完全放弃 template 转移,直接在 source 上按 anatomy landmark + 经验公式计算 vertex offset。例: 'あ' = (下嘴唇 verts 向下 8mm + 嘴角 verts 向外 2mm)。

**优点**: 完全可控,不依赖 template, 不依赖 mesh 配准
**缺点**: 每条 morph 都要手工编公式,复杂表情类 (笑い/困る/にやり) 难以公式化
**Post-mortem 推荐过**: 简单 morph (あ/い/う/え/お/まばたき/ウィンク) 可以走这条,复杂的放弃或手雕

## 不要再走的坑

1. ❌ 不要把 Purifier Inase 18 当 template (bone_morph based,'あ' 仅 5° jaw 旋转,不是标准张嘴)
2. ❌ 不要用 forward TPS warp + KDTree on warped verts (upper-lip offset 会被 nose-region 稀释)
3. ❌ 不要相信 "max offset 量级对" 就 claim success (撅嘴和张嘴的 max offset 都可以 10-15mm)
4. ❌ 不要用粗估 landmark 位置做精细 transfer (± 5mm 误差在嘴区已致命)
5. ❌ 不要一次跑 19 条再报告 — 1 条端到端失败,其他不必跑
6. ❌ 不要只看 template 或只看 source 截图,**必须 side-by-side 对比**
7. ❌ 不要在 transfer 成功前做 pipeline 集成 (operator / UI)

## 验证 checklist (Phase 1 端到端 1 条必做)

在 claim "transfer works" 前必须满足:
- [ ] Template 自身 'あ=1.0' 截图: 视觉上是**大张嘴椭圆**
- [ ] Source transfer 后 'あ=1.0' 截图
- [ ] Side-by-side 对比图: source 形态和 template 一致(open mouth, not pucker)
- [ ] 上/下唇 Z 位移差异: src 应 ≥ template (规模按脸比例),**方向一致**
- [ ] Upper lip Z 位移: src ≥ template (tpl 1.9mm 时 src 也应 ≥ 1.9mm,不是 1mm)
- [ ] 嘴区外 (眼/鼻/眉) 无明显变形 (每 axis < 0.5mm)
- [ ] 侧面截图: 嘴张开纵向轮廓清晰

## Cross-ref

- Related: `doc/morph_post_mortem_2026_04_18.md` — 之前三条路线 (clone bone / bake & transfer / XPS native recipe) 失败复盘
- Code: `experimental/morph_transfer_poc.py` — 路径 A 已实现,失败但保留供参考
- HEAD `233f8ad` (failed A with inverse TPS)
