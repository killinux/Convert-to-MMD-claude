# 已知问题记录

> 待重构时修复，按严重程度排序。

---

## 严重 Bug（会直接崩溃或报错）

### BUG-01 多线程操作 Blender API
- **文件**：`operators/clear_unweighted_bones_operator.py`，第 62–77 行
- **问题**：`remove_bones_with_threads()` 用 `ThreadPoolExecutor` 在子线程里调用 `edit_bones.remove()`。Blender Python API 不是线程安全的，所有 `edit_bones` 操作必须在主线程执行，多线程操作轻则数据损坏，重则 Blender 崩溃。
- **修复方向**：去掉多线程，直接在主线程循环删除骨骼。

### BUG-02 返回 `RUNNING_MODAL` 却没有 `modal()` 方法
- **文件**：`operators/clear_unweighted_bones_operator.py`，第 60 行
- **问题**：`execute()` 返回 `{'RUNNING_MODAL'}`，但类里没有实现 `modal()` 方法，Blender 会卡住，操作无法结束。
- **修复方向**：改为返回 `{'FINISHED'}`。

### BUG-03 `has_vertex_groups()` 跨网格对象比较顶点组索引，逻辑错误
- **文件**：`operators/clear_unweighted_bones_operator.py`，第 19–24 行
- **问题**：遍历的是 `bpy.data.meshes`（所有网格数据块，包含未关联到场景的），而不是传入的 `obj`。更严重的是顶点组的 `index` 在每个网格对象里是独立编号的，用一个对象的顶点组 index 去匹配另一个 mesh 的 `v.groups[].group`，会产生错误的权重判断。
- **修复方向**：只遍历传入的 `obj.data.vertices`，用 `obj.data` 而非 `bpy.data.meshes`。

### BUG-04 `draw_error_menu()` 中 `obj` 未定义
- **文件**：`operators/preset_operator.py`，第 144 行
- **问题**：`draw_error_menu()` 是独立的回调函数，但末尾调用了 `obj.select_set(True)`，`obj` 只在 `execute()` 里定义，在这里直接 `NameError`。
- **修复方向**：删除该行，或通过闭包/自定义属性传入 `obj`。

### BUG-05 `complete_missing_bones` 直接用下标访问骨骼，缺骨骼即崩溃
- **文件**：`operators/bone_operator.py`，第 122 行及多处
- **问题**：多处直接用 `edit_bones["骨骼名"]` 访问，没有 `.get()` 保护，用户骨架缺少对应骨骼时直接 `KeyError` 崩溃。受影响的包括 `上半身2`、`左肩`、`左腕`、`左ひじ`、`右肩`、`右腕`、`右ひじ` 等。
- **修复方向**：统一改用 `.get()` 并在为 `None` 时给出友好报错。

---

## 中等问题（功能异常或不完整）

### BUG-06 异常时复制的修改器没有清理
- **文件**：`operators/pose_operator.py`，第 69–77 行、第 125–127 行
- **问题**：步骤3给每个网格创建了 `_copy` 修改器，但步骤8应用修改器时若抛出 `RuntimeError`，函数直接 `return {'CANCELLED'}`，`_copy` 修改器永久残留在场景里。
- **修复方向**：用 `try/finally` 确保异常时也能清理复制的修改器。

### BUG-07 A-Pose 转换只转了上臂，效果不完整
- **文件**：`operators/pose_operator.py`，第 22–25 行
- **问题**：`arm_bones` 字典只包含 `left_upper_arm` / `right_upper_arm`，标准 A-Pose 通常还需要同时旋转肩膀骨骼，仅转上臂效果不自然。
- **修复方向**：补充肩膀骨骼的旋转，并考虑将旋转角度做成可调参数。

---

## 轻微问题（代码质量）

### BUG-08 无用的导入
- **文件**：`operators/clear_unweighted_bones_operator.py`，第 3–4 行
- **问题**：`import asyncio` 和 `from mathutils import Vector` 在文件中从未使用。

### BUG-09 `@lru_cache` 没有实际意义
- **文件**：`operators/collection_operator.py`，第 5 行
- **问题**：`load_bone_presets()` 加了 `@lru_cache`，但模块加载时第 34 行就直接调用并将结果存入全局变量，缓存永远不会被命中第二次，装饰器形同虚设。

### BUG-10 绕道从父包导入 `preset_operator`
- **文件**：`operators/bone_operator.py`，第 5 行
- **问题**：`from .. import preset_operator` 依赖根 `__init__.py` 提前将 `preset_operator` 导入其命名空间才能成立，是隐式依赖。
- **修复方向**：改为 `from . import preset_operator`，直接从同级目录导入。

---

## 外部插件修复记录

### FIX-EXT-01 mmd_tools VMD导入报错 `frame_start expected int, not float`
- **日期**：2026-04-08
- **文件**：Mac 上 `~/Library/Application Support/Blender/3.6/scripts/addons/mmd_tools/auto_scene_setup.py`
- **问题**：`action.frame_range` 返回 float，直接赋值给 `frame_start`/`frame_end` 会报 TypeError。
- **修复**：4 处赋值加 `int()` 包装：
  ```python
  bpy.context.scene.frame_start = int(s)
  bpy.context.scene.frame_end = int(e)
  bpy.context.scene.rigidbody_world.point_cache.frame_start = int(s)
  bpy.context.scene.rigidbody_world.point_cache.frame_end = int(e)
  ```
- **注意**：此修改在 Mac 本地，不在本仓库管理。
