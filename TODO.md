# TODO

## P1 — 上半身后续

- **ダミー.L/R**: MMD 标准的手首末端配饰挂点骨 (parent=手首, 长度~1.2x 手长)。
  无动作影响, 只给配饰/物品用。XPS 无对应源, 需要创建空骨。优先级低, 有动作
  需求后再做。

- **乳奶1.L/R (第二节)**: 当前只 rename `boob left/right 1` → `乳奶.L/R`。
  XPS 有 `boob left/right 2` 作为第二节, 目标 PMX 没有对应骨但有独立运动。
  是否把第二节 rename 成 `乳奶1.L/R` 需要验证是否能在 MMD 里正确变形, 可能
  需要物理 joint 配合。

- **twist 子骨权重**: 当前算法"尽量用 XPS 原权重, 不切分", 若 XPS 无 twist
  源 (xtra07pp / foretwist 这类), 上臂 sub (腕捩1/2/3) 全部创建为空骨, 只有
  pose-only 驱动, 不产生梯度变形, 外观会比 target 粗糙。若需要, 后续加一个
  可选的"从主骨切分权重"模式。

- **乳奶骨的位置识别版本**: 目前 `boob/breast left/right 1` 是硬编码名字 rename。
  其他 XPS 模型 (Daz/Poser 等) 可能用不同名字。可以加位置识别: 扫描
  parent ∈ {上半身2, 上半身1} + 胸部区域 + 有权重 的骨。

## P2 — 下半身重设计

当前 `leg_operator.py` 内 complete_d_bones / complete_hip_cancel_bones /
assign_weights 的实现是针对 xna_lara_Inase 调出来的, 通用性一般:

- **腿部 twist 系统**: target PMX 没有腿部 twist 骨 (标准 MMD 也很少有),
  但有些模型会加。当前完全不处理。
- **足IK親**: target 有 `足IK親.L/R` (parent=全ての親, 控制 `足ＩＫ` 的父骨),
  现在 `add_mmd_ik` 只创建 `足ＩＫ` 和 `つま先ＩＫ`, 没创建 `足IK親`。
- **通用化辅助骨保留策略**: `PRESERVE_HELPER_KEYWORDS` 硬编码 `xtra02/04/
  08/08opp/muscle_elbow`, 其他模型用不同名字就不生效。改成"所有 unused 骨
  若位于关节处且 PMX 目标集之外则默认保留"会更通用。

## P3 — 代码/工具

- **operators/ 补并重组**: 当前 `bone_operator.py` 里塞了 rename + complete
  + 两个 convert helper, 可以拆成 rename / structure / convert 三个文件。
- **preset 格式 v2**: 加上开关 (是否创建 twist sub, 是否创建 ダミー 等),
  目前只有 bone name 映射。
- **单元测试**: 给 twist_operator 写个能离线跑的 pytest, mock 一个简易 XPS
  骨架, 验证候选识别 + 分配算法。
