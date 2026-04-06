
import re, sys

filepath = r'E:\mywork\add_on\Convert-to-MMD-claude\operators\leg_operator.py'

# 读取时去掉 BOM
with open(filepath, encoding='utf-8-sig') as f:
    lines = f.readlines()

print(f"Total lines: {len(lines)}")

fixes = 0
for i, line in enumerate(lines):
    orig = line

    # 1. 修复关键骨骼名称
    line = line.replace('"瓒抽D.L"', '"足首D.L"')
    line = line.replace('"瓒抽D.R"', '"足首D.R"')
    line = line.replace('"瓒抽D"', '"足首D"')
    line = line.replace('"瓒矰"', '"足D"')
    line = line.replace('"銇层仏D"', '"ひざD"')
    line = line.replace('"銇层仏"', '"ひざ"')

    # 2. 修复截断的字符串（末尾 ? 导致字符串未闭合）
    # 模式：" 中文？) 或 " 中文？, 等
    # 找出引号内以 ? 结尾然后紧接右括号/逗号/空格的情况
    def fix_truncated(m):
        inner = m.group(1)
        close = m.group(2)
        # 如果内容以 ? 结尾，去掉 ? 然后补引号
        if inner.endswith('?'):
            inner = inner[:-1]
        return '"' + inner + '"' + close

    # 匹配 "...?" 后接 )) , 换行等
    line = re.sub(r'"([^"\n]*?)\?([\)\s,\n])', fix_truncated, line)

    # 3. 修复 get("下半？) → get("下半身")
    line = re.sub(r'get\(["\']下半[身]?[\'"]?\)', 'get("下半身")', line)
    line = re.sub(r'\.get\("下半\)', '.get("下半身")', line)

    # 4. 修复以 ? 结尾的 docstring 行
    line = re.sub(r'("""[^"]*)\?"""', r'\1"""', line)

    if line != orig:
        fixes += 1
        print(f"L{i+1}: {line.rstrip()}")

    lines[i] = line

print(f"\nFixed {fixes} lines")

# 写回（不写 BOM）
with open(filepath, 'w', encoding='utf-8') as f:
    f.writelines(lines)
print("Written back")

# 语法检查
import ast
try:
    src = ''.join(lines)
    ast.parse(src)
    print("✓ Python syntax OK")
except SyntaxError as e:
    print(f"✗ SyntaxError at line {e.lineno}: {e.msg}")
    print(f"  {e.text}")
