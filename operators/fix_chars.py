
import re, ast

filepath = r'E:\mywork\add_on\Convert-to-MMD-claude\operators\leg_operator.py'

with open(filepath, encoding='utf-8') as f:
    content = f.read()

# 清理所有导致语法错误的特殊字符
replacements = {
    '\uff08': '(',    # （
    '\uff09': ')',    # ）
    '\uff0c': ',',    # ，
    '\u3002': '.',    # 。
    '\uff01': '!',    # ！
    '\uff1f': '?',    # ？
    '\uff1a': ':',    # ：
    '\uff1b': ';',    # ；
    '\ufffd': '',     # 替换字符（删除）
    '\u2014': '-',    # — em dash
    '\u2026': '...',  # … ellipsis
    '\u00b7': '*',    # · 中点
}

for ch, rep in replacements.items():
    content = content.replace(ch, rep)

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)

# 循环检查并修复
prev_lineno = -1
for attempt in range(30):
    try:
        ast.parse(content)
        print(f'✓ Syntax OK after {attempt} fixes')
        break
    except SyntaxError as e:
        line_txt = repr(e.text[:80]) if e.text else 'no text'
        print(f'  L{e.lineno}: {e.msg} | {line_txt}')
        if e.lineno == prev_lineno:
            print('  Stuck, stopping')
            break
        prev_lineno = e.lineno
        lines = content.splitlines(keepends=True)
        if e.lineno and e.lineno <= len(lines):
            bad_line = lines[e.lineno - 1]
            # 删除 U+FF00-FFEF 范围（全角字符）和 FFFD
            fixed = re.sub(r'[\uff00-\uffef\ufffd\u2000-\u206f\u00b7]', '', bad_line)
            lines[e.lineno - 1] = fixed
            content = ''.join(lines)
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)

# 同步到 AppData
appdata = r'C:\Users\haoni\AppData\Roaming\Blender Foundation\Blender\3.6\scripts\addons\Convert-to-MMD-claude\operators\leg_operator.py'
import shutil
shutil.copy2(filepath, appdata)
print('✓ Synced to AppData')
