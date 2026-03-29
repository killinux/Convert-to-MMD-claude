"""
通过 Blender MCP 执行此脚本以热重载插件。
用法：将此文件内容粘贴到 MCP execute_blender_code 工具中执行。
"""
import bpy, sys

bpy.ops.preferences.addon_disable(module="Convert-to-MMD-claude")
for k in [k for k in sys.modules if 'Convert-to-MMD-claude' in k]:
    del sys.modules[k]
bpy.ops.preferences.addon_enable(module="Convert-to-MMD-claude")
print("重载完成")
