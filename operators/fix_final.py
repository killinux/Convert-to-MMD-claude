
filepath = r'E:\mywork\add_on\Convert-to-MMD-claude\operators\leg_operator.py'

with open(filepath, encoding='utf-8') as f:
    content = f.read()
    lines = content.splitlines(keepends=True)

# ── 修复1：注释和代码被合并的行 ──
# Line 26: 注释 + LOWER_BODY_TARGETS = { 合并了，需要拆开
for i, line in enumerate(lines):
    # 如果注释行里包含了 = { 等代码，拆开
    if line.strip().startswith('#') and 'LOWER_BODY_TARGETS = {' in line:
        idx = line.find('LOWER_BODY_TARGETS = {')
        lines[i] = line[:idx] + '\n' + 'LOWER_BODY_TARGETS = {\n'
        print(f"Fixed L{i+1}: split comment and code")
        break

for i, line in enumerate(lines):
    if line.strip().startswith('#') and 'PHASE2_TARGETS = {' in line:
        idx = line.find('PHASE2_TARGETS = {')
        lines[i] = line[:idx] + '\n' + 'PHASE2_TARGETS = {\n'
        print(f"Fixed L{i+1}: split comment and code")
        break

# ── 修复2：瓒抽D → 足首D （还没修复的）──
for i, line in enumerate(lines):
    if '瓒抽D' in line:
        lines[i] = line.replace('瓒抽D', '足首D')
        print(f"Fixed L{i+1}: 瓒抽D → 足首D")

# ── 修复3：_side_of_mmd_bone 函数中 "宸" → "左", "鍙" → "右" ──
for i, line in enumerate(lines):
    if 'startswith("宸")' in line:
        lines[i] = line.replace('startswith("宸")', 'startswith("左")')
        print(f"Fixed L{i+1}: 宸→左")
    if 'startswith("鍙")' in line:
        lines[i] = line.replace('startswith("鍙")', 'startswith("右")')
        print(f"Fixed L{i+1}: 鍙→右")

# ── 修复4：_arm_bone_name 中 ("宸" if → ("左" if, ("鍙" if 等 ──
for i, line in enumerate(lines):
    if '("宸"' in line or '("�"' in line:
        lines[i] = line.replace('("宸"', '("左"').replace('("�"', '("左"')
        print(f"Fixed L{i+1}: arm bone name left")
    if '"鍙"' in line or '"鑷"' in line:
        lines[i] = line.replace('"鍙"', '"右"').replace('"鑷"', '"右"')
        print(f"Fixed L{i+1}: arm bone name right")

# ── 修复5：vg.name for k in ["足", "ひざ", "腰", "D."] ──
for i, line in enumerate(lines):
    if '"ひざ"' in line and '"D."' in line and ('["' in line or ', "' in line):
        # 这是过滤列表，修复被截断的 足 和 腰
        lines[i] = line.replace('["\\ufffd"', '["足"').replace('"\\ufffd"', '"腰"')
        # 更宽泛的修复
        import re
        lines[i] = re.sub(r'\["[^"]{1,2}", "ひざ"', '["足", "ひざ"', lines[i])
        print(f"Fixed L{i+1}: filter list")

# ── 修复6：UPPER3_SOURCE_BONES 和 target bone ──
for i, line in enumerate(lines):
    if 'UPPER3_SOURCE_BONES' in line and '上半' in line:
        lines[i] = 'UPPER3_SOURCE_BONES = ["上半身", "上半身1", "上半身2", "上半身3"]\n'
        print(f"Fixed L{i+1}: UPPER3_SOURCE_BONES")
    if 'UPPER3_TARGET_BONE' in line and '上半' in line:
        lines[i] = 'UPPER3_TARGET_BONE  = "上半身3"\n'
        print(f"Fixed L{i+1}: UPPER3_TARGET_BONE")

# ── 修复7：get("下半...") 修复 ──
import re
for i, line in enumerate(lines):
    if 'get("下半' in line and '"下半身"' not in line:
        lines[i] = re.sub(r'get\("下半[^"]*"?\)', 'get("下半身")', line)
        print(f"Fixed L{i+1}: get 下半身")

# ── 修复8：edit_bones.get("下半身") 等 ──
for i, line in enumerate(lines):
    if '"下半' in line and '"下半身"' not in line:
        old = lines[i]
        lines[i] = re.sub(r'"下半[^"]{0,2}"', '"下半身"', line)
        if lines[i] != old:
            print(f"Fixed L{i+1}: 下半身 string")

# ── 修复9：左ひ→左ひじ 等常见截断 ──
for i, line in enumerate(lines):
    if '"左ひ"' in line:
        lines[i] = line.replace('"左ひ"', '"左ひじ"')
        print(f"Fixed L{i+1}: 左ひ→左ひじ")
    if '"右ひ"' in line:
        lines[i] = line.replace('"右ひ"', '"右ひじ"')
        print(f"Fixed L{i+1}: 右ひ→右ひじ")

# 写回
with open(filepath, 'w', encoding='utf-8') as f:
    f.writelines(lines)
print("\nWritten back")

# 语法检查
import ast
try:
    src = ''.join(lines)
    ast.parse(src)
    print("✓ Python syntax OK!")
except SyntaxError as e:
    print(f"✗ SyntaxError at line {e.lineno}: {e.msg}")
    print(f"  {e.text}")
