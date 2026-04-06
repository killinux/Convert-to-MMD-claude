
import ast, sys

filepath = r'E:\mywork\add_on\Convert-to-MMD-claude\operators\leg_operator.py'
try:
    with open(filepath, encoding='utf-8') as f:
        src = f.read()
    ast.parse(src)
    print("OK - no syntax errors")
except SyntaxError as e:
    print(f"SyntaxError at line {e.lineno}: {e.msg}")
    print(f"  Text: {e.text}")
except Exception as e:
    print(f"Error: {e}")
