"""
修复「注释行里藏着代码」的合并行
模式：# comment text     actual_code = something
拆成两行：# comment text\n    actual_code = something
"""
import re, ast, shutil

FILEPATH = r'E:\mywork\add_on\Convert-to-MMD-claude\operators\leg_operator.py'
APPDATA  = r'C:\Users\haoni\AppData\Roaming\Blender Foundation\Blender\3.6\scripts\addons\Convert-to-MMD-claude\operators\leg_operator.py'

with open(FILEPATH, encoding='utf-8') as f:
    lines = f.readlines()

# 匹配：注释内容 + 4个以上空格 + 代码（含 = 或 ( 或 : 的语句）
SPLIT_PAT = re.compile(
    r'^([ \t]*#[^\n]*?)'                         # group1: 注释部分（行首缩进+#内容）
    r'([ \t]{4,})'                               # group2: 分隔空白
    r'([a-zA-Z_\u4e00-\u9fff\u3040-\u30ff]'     # group3: 代码部分（变量/关键字开头）
    r'[^\n]*(?:=|\(|:|\bfor\b|\bif\b|\breturn\b)[^\n]*)$'
)

fixed = 0
new_lines = []
for i, line in enumerate(lines):
    stripped = line.lstrip()
    if stripped.startswith('#'):
        m = SPLIT_PAT.match(line.rstrip('\n\r'))
        if m:
            comment_part = m.group(1)
            code_part    = m.group(3)
            # 代码缩进 = 注释缩进（同层级）
            indent = len(line) - len(line.lstrip())
            new_lines.append(comment_part + '\n')
            new_lines.append(' ' * indent + code_part + '\n')
            print(f'L{i+1}: split -> "{comment_part.strip()}" | "{code_part.strip()[:60]}"')
            fixed += 1
            continue
    new_lines.append(line)

print(f'\n拆分 {fixed} 处')

# 语法检查
src = ''.join(new_lines)
try:
    ast.parse(src)
    print('Syntax OK')
except SyntaxError as e:
    print(f'SyntaxError L{e.lineno}: {e.msg}')
    print(f'  {e.text}')
    print('不写回，请手动检查')
    exit(1)

with open(FILEPATH, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
shutil.copy2(FILEPATH, APPDATA)
print('写回并同步到 AppData')
