#!/bin/bash
# 将插件同步到 Blender 并热重载

SRC="E:/mywork/add_on/Convert-to-MMD-claude"
DEST="C:/Users/haoni/AppData/Roaming/Blender Foundation/Blender/3.6/scripts/addons/Convert-to-MMD-claude"

cp -r "$SRC/operators" "$SRC/presets" "$SRC/doc" "$SRC/tools" "$DEST/"
cp "$SRC/"*.py "$DEST/"

echo "同步完成 -> $DEST"
