[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$file = 'E:\mywork\add_on\Convert-to-MMD-claude\operators\leg_operator.py'
$content = [IO.File]::ReadAllText($file, [Text.Encoding]::UTF8)

# 修复关键骨骼名称（影响功能的字符串）
$content = $content -replace '"瓒抽D\.L"', '"足首D.L"'
$content = $content -replace '"瓒抽D\.R"', '"足首D.R"'
$content = $content -replace '"瓒抽D"', '"足首D"'
$content = $content -replace '"瓒矰"', '"足D"'
$content = $content -replace '"銇层仏D"', '"ひざD"'
$content = $content -replace '"銇层仏"', '"ひざ"'

# 修复被截断的字符串字面量（末尾有 ? 导致语法错误）
$content = $content -replace '"下半\x{0024}1?', '"下半身"'
$content = $content -replace 'get\("下半[^"]*"?\)', 'get("下半身")'
$content = $content -replace '"上半[^1-9"][^"]*\?[^"]*"', '"上半身"'

# 关键：修复所有 ? 后接 ) 的截断字符串
# 例如: " 已存在?) → " 已存在")
$content = $content -replace '(\"[^\"]*)\?([\)\s])', '$1$2'

# 修复 docstring 中的乱码（影响语法）
$content = $content -replace '"""[^"]*璁[^"]*"""', '"""helper function"""'
$content = $content -replace '"""[^"]*绉[^"]*"""', '"""helper function"""'

[IO.File]::WriteAllText($file, $content, [Text.Encoding]::UTF8)
Write-Host "修复完成"
