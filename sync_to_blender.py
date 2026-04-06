"""
同步整个插件目录到 Blender AppData
用法: python sync_to_blender.py
"""
import shutil, os, glob

SRC  = r'E:\mywork\add_on\Convert-to-MMD-claude'
DST  = r'C:\Users\haoni\AppData\Roaming\Blender Foundation\Blender\3.6\scripts\addons\Convert-to-MMD-claude'

# 同步所有 .py 文件（保持目录结构）
copied = 0
for src_path in glob.glob(SRC + '/**/*.py', recursive=True):
    rel = os.path.relpath(src_path, SRC)
    dst_path = os.path.join(DST, rel)
    os.makedirs(os.path.dirname(dst_path), exist_ok=True)
    shutil.copy2(src_path, dst_path)
    print(f'  {rel}')
    copied += 1

# 同步 presets 目录下的 json 文件
for src_path in glob.glob(SRC + '/presets/**/*.json', recursive=True):
    rel = os.path.relpath(src_path, SRC)
    dst_path = os.path.join(DST, rel)
    os.makedirs(os.path.dirname(dst_path), exist_ok=True)
    shutil.copy2(src_path, dst_path)
    print(f'  {rel}')
    copied += 1

# 清除 __pycache__ 避免用旧缓存
pycache = os.path.join(DST, 'operators', '__pycache__')
if os.path.exists(pycache):
    shutil.rmtree(pycache)
    print('  __pycache__ cleared')

print(f'\nDone: {copied} files synced')
