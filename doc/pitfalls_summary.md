# 项目核心踩坑总结

本文档是 Convert_to_MMD_claude 跨多个 session 踩过的**结构性坑**的精简总结 — 不覆盖 Path D morph 相关(见 `morph_path_d_lessons.md`),聚焦在骨骼系统 / 物理 / pipeline 层。每条坑含 root cause、修法、transferable lesson。详细现场在各专题文档。

---

## 1. 腰キャンセル 付与親 target — 腿抖动 176 → 4 帧

**症状**:转换后的模型用同一条 VMD 播放,下半身(尤其腿)出现单帧 >30° 的旋转跳变,176 帧抖动。

**Root cause**:
- Step 8 `setup_pmx_attributes` 把 `_dummy_腰キャンセル.L` 的 `additional_transform_bone` 设成了**父骨 `下半身`**,应该是**祖父骨 `腰`**。
- PMX export 后 mmd_tools 重建 dummy/shadow 链时从这个字段读 parent,结果 dummy 继承了 `下半身` 的大幅旋转 → 通过 TRANSFORM constraint 传到 `腰キャンセル` → 下半身运动被反向放大抵消到腿上。

**Fix**(commit `428951c`,2026-04-10):一行改动
```python
cancel_pb.mmd_bone.additional_transform_bone = "腰"   # was "下半身"
```

**Lesson**:**付与親(additional transform)的 target 是"用谁的运动来抵消/复制",不是 parent**。腰キャンセル 的语义是"取消腰的旋转",所以 target 必须指向腰,不是自己挂的父骨下半身。metadata 一个字段错,mmd_tools 在 PMX 重导时会还原出整条错误的 constraint 链,视觉后果在几帧后才爆发。

**Detail**: `doc/leg_jitter_investigation.md`, `doc/mmd_additional_transform_mechanism.md`

---

## 2. Twist / D-bone 无效 — shadow 链没建

**症状**:XPS→MMD 转换后,旋转 `腕.L` 时 `腕捩1/2/3` 完全不动,看起来像 weight 没绑(但 weight 其实正确)。

**Root cause**:
- `mmd_tools.convert_to_mmd_model()`(XPS→MMD 用的路径)**不** auto-build shadow/dummy constraint chain。
- 只有 `mmd_tools.import_model()`(直接导 PMX 用的)会建。
- 所以转出来的 armature 骨位/weight/metadata 全对,但 constraint 层是空的,twist bone 是"死骨"。

**Fix**(commit `c834b5c`,2026-04-11):在 `OBJECT_OT_use_mmd_tools_convert.execute()` 末尾加一行
```python
bpy.ops.mmd_tools.apply_additional_transform()
```
验证:`腕捩.L` 旋 90° 后三根子 twist 应为 25.4°/49.1°/70.7°(不是 0)。

**Lesson**:**L3(weight) 之前先查 L2(constraint chain)**。Mesh 不动有多层可能原因:
- L1:骨位不对 → 骨旋转方向异常
- L2:constraint 没建或参数错 → 子骨无继承(本坑)
- L3:weight 错 → 骨动了 mesh 不跟
- L4:vertex group 挂错骨(腕↔腕捩 交换等)

顺序不能反。看 mesh 不动就去切 weight 最容易南辕北辙。

**Detail**: `doc/twist_debugging_lessons.md`(MECE 诊断框架), `doc/mmd_additional_transform_mechanism.md`

---

## 3. D-bone(肩P/腕捩P 等)COPY_ROTATION space 错

**症状**:D-bone 加了 constraint 也 apply 了 additional_transform,但主骨旋转时 D-bone 不跟。

**Root cause**:COPY_TRANSFORMS 用 LOCAL space 对 D-bone 无效,它要 POSE space(commit `b3f71bd`)。之后又从 COPY_TRANSFORMS 改成 COPY_ROTATION 更精准(commit `4c29d0a`)。

**Lesson**:Blender constraint 的 space 参数不是 UI 装饰,LOCAL/POSE/WORLD 语义差异巨大,跨 space 不等价。尤其 `COPY_*` 族,空间选错等于没加。

**Detail**: commit log + `doc/mmd_additional_transform_mechanism.md`

---

## 4. Rigid body 位置偏移(远离 mesh)

**症状**:从 target PMX clone 物理到转换模型后,刚体和 joint 整体漂移到头顶上方,不贴 mesh。

**Root cause**:`_pmx_rigid_to_entry()` 存的是**世界坐标**。apply 时默认 target 和转换模型骨位一致,但实际不一致,offset 被当成绝对位置使。

**Fix**(commit `000cebf`,2026-04-19):改成存**骨相对 offset**
```python
rigid_local_loc = rigid_world - target_bone_world
# apply:
applied_loc = dst_bone_world + rigid_local_loc
```
对齐误差 avg 9.8cm → 0.9cm。

**Lesson**:**skeletal deformation 里 ground truth 是骨,不是 world**。任何要跨模型迁移的附属物(rigid/joint/constraint),存 bone-local 是默认,存 world 是坑。

**Detail**: `doc/physics_generalization_plan_2026_04_19.md`, `doc/physics_handoff_2026_04_19.md`

---

## 5. Rest pose 方向对齐 — VMD 重定向的无声杀手

**症状**:同一条 VMD,转换模型播放出来手臂角度和目标 PMX 不一致,尤其肩肘位。腿 IK 解算后膝盖角度也偏。

**Root cause**:XPS 骨架是游戏优化过的,骨位/比例/骨向都和 MMD 标准模型不同。VMD 帧数据是基于目标 rest pose 编码的,rest pose 一旦偏,IK solver 解出来就和原作者意图不同。

**Mitigation**:Step 2 `complete_missing_bones` 里调整 tail 位置(`align_arms_to_reference` / `align_fingers_to_reference` / 足首 tail 指 つま先),降低方向误差。position 误差无法完全消除(限肢比例),会留残余抖动。

**Lesson**:VMD 播放异常时按这个顺序排查(**不要跳步**,CLAUDE.md 有强调):
1. rest pose 方向偏(`bone.matrix_local` Y/Z 轴对比)
2. pose bone constraint / lock_rotation
3. vertex group 挂反或缺失
4. 以上都排除才查 weight

**Detail**: `doc/leg_jitter_investigation.md`, `doc/hip_leg_fix_methods.md`, `doc/leg_hip_d_bone_pitfalls.md`

---

## 6. 新加骨漏配 mmd_bone_group → 掉 'other' 假象消失

**症状**:Convert 加新骨(乳奶/首1 等)PMXEditor 里看不见,以为 export 时丢了。

**Root cause**:新骨忘了加到 `bone_map_and_group.py:mmd_bone_group` 列表。mmd_tools export 时按 group 分类,没归组的骨掉到 'Other' 汇总 group 里,UI 里容易忽略。

**Lesson**:**convert 阶段增/改骨名一律同步 `mmd_bone_group`**。没有这一步 PMXEditor 看不见骨,但 scene 里和 PMX 二进制里都在 — 假象最容易误导。

**Detail**: memory `feedback_bone_group_other_pitfall.md`

---

## 7. Operator 顺序依赖 — vertex group 是中间产物

**症状**:Path D morph 合成需要 source mesh 的 `lip_upper` / `eyelid_*` 等 vg,但 `cleanup_face_bones` 会删脸骨连带 vg,跑完 cleanup 再跑 morph synth 就空。

**Root cause**:pipeline 里某些 op 的 side effect(删 vg / 删骨)破坏了下游 op 的输入前提。

**Lesson**:pipeline step 顺序不是执行顺序,**是数据依赖顺序**。任何依赖中间产物的 op 必须排在产物消失之前。加新 op 前先画数据依赖图。

**Detail**: session handoff 里的 step 6→8 顺序约定

---

## 8. Blender op 返回 FINISHED 但没生效

**症状**:`bpy.ops.object.surfacedeform_bind(modifier='_morph_sd')` 返回 `{'FINISHED'}`,但 `sd.is_bound` 永远 False。

**Root cause**:Blender 3.6.21 bug — 脚本调用 bind 不 trigger 实际绑定,UI 点击才行。

**Lesson**:Blender ops 的返回值只代表"命令执行到底",不代表"副作用生效"。依赖某个 op 副作用时,**必须另查 state flag**(`is_bound` / `modifier.show_viewport` / vertex count diff 等),不能只看 `{'FINISHED'}`。

**Detail**: `doc/morph_transfer_paths_2026_04_18.md` Path C 段

---

## 跨主题方法论教训

从上面 8 条提炼出的通用原则(和 `~/.claude/CLAUDE.md` 的 Karpathy 原则一致):

### A. Metadata 一个字段的代价可能放大到全身

`addition_transform_bone` 一个字段错(腰 vs 下半身) → 176 帧腿抖。metadata 驱动的框架(mmd_tools)里,一个布尔/字符串字段的精度等价于一大段 code。所有 metadata 改动要有显式 fixture 值而非"差不多就行"。

### B. "Mesh 不动" 不等于 "weight 错"

L1→L2→L3→L4 顺序排查,不跳步。CLAUDE.md 里的"姿态偏差排查顺序"也是同一原则的专题化。

### C. 跨模型/跨几何的附属物存 bone-local

rigid/joint/morph offset/bone tail/constraint target — 任何要跨模型复用的量,存成**相对骨 local** 是默认,**绝对 world** 是坑。world 值只在"同一 rig 内"有意义。

### D. Blender op FINISHED ≠ 生效

ops 返回值是"命令跑完",不是"副作用达成"。依赖副作用一律另查 state。

### E. 先 probe rig 能力再选算法

无论 morph/physics/IK,动手前先查 source 有没有需要的 vg / bone / property。没有就换方法,不要靠"算法够强能兜住"。

### F. 视觉 ground truth > 数据指标

max offset / region distribution / constraint 是否存在 — 全是 sanity check,不是成功标准。侧面截图、side-by-side、VMD 端到端播完才算。

---

## 交叉引用

- `morph_path_d_lessons.md` — Path D morph 合成专题
- `leg_jitter_investigation.md` — 腿抖动完整调查过程
- `mmd_additional_transform_mechanism.md` — 付与親 机制理论权威
- `twist_debugging_lessons.md` — L1-L4 诊断框架完整版
- `pitfalls.md` — 历史坑汇总(可能和本文有重叠,以本文为精简索引)
- `physics_generalization_plan_2026_04_19.md` — 物理通用化 + rigid 坐标存法
- `hip_leg_fix_methods.md` — 腿胯修复方法清单(含失败记录)
- `session_postmortem_2026_04_19.md` — 行为规则(Karpathy 四原则 + 8 条)
