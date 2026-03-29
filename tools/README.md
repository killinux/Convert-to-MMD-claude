# Tools

开发辅助脚本。

---

## sync_to_blender.sh

将源码同步到 Blender 插件目录（排除 `.git`）。

**用法：** 在项目根目录执行
```bash
bash tools/sync_to_blender.sh
```

目标目录：`C:/Users/haoni/AppData/Roaming/Blender Foundation/Blender/3.6/scripts/addons/Convert-to-MMD-claude`

---

## reload_in_blender.py

通过 MCP 在 Blender 内热重载插件。单纯同步文件后 Blender 不会自动读取新版本，必须执行此脚本清除模块缓存并重新启用插件。

**用法：** 将文件内容通过 MCP `execute_blender_code` 工具发送给 Blender 执行，或直接让 Claude 调用。

**执行步骤：**
1. 禁用插件 (`addon_disable`)
2. 清除 Python 模块缓存（否则 Blender 仍使用旧版本）
3. 重新启用插件 (`addon_enable`)

---

## 完整更新流程

```bash
# 1. 修改源码后，同步到 Blender
bash tools/sync_to_blender.sh

# 2. 通过 MCP 重载（让 Claude 执行，或手动粘贴 reload_in_blender.py 内容）
```

面板顶部时间戳会更新，确认重载成功。
