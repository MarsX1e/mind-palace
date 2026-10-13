# ============================================================
#  在服务器上自查：为什么搜不到黄金视频
#  用法（在你电脑上执行）：
#    ssh Administrator@1.2.3.4 "powershell -ExecutionPolicy Bypass -File C:\kb\tools\check-search.ps1"
# ============================================================

try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
try { [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12 } catch { }
[System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }

$词 = "黄金"
$索引目录 = "C:\kb\00-影像资料\索引"
$描述文件 = Join-Path $索引目录 "视频描述.txt"
$密码文件 = "C:\kb\server\access_token.txt"

Write-Host "==============================================="
Write-Host "   服务器自查：黄金视频检索"
Write-Host "==============================================="

Write-Host "`n[1] 视频描述文件"
if (Test-Path $描述文件) {
    $全部 = Get-Content $描述文件 -Encoding UTF8
    $匹配 = $全部 | Where-Object { $_ -match $词 }
    Write-Host "   文件存在，共 $($全部.Count) 行，其中含『$词』的 $($匹配.Count) 行" -ForegroundColor Green
    $匹配 | Select-Object -First 5 | ForEach-Object { Write-Host "   $_" }
} else {
    Write-Host "   × 文件不存在：$描述文件" -ForegroundColor Red
}

Write-Host "`n[2] 索引目录内容"
Get-ChildItem $索引目录 -File -ErrorAction SilentlyContinue |
    Select-Object Name, @{N = '字节'; E = { $_.Length } } | Format-Table -AutoSize

Write-Host "`n[3] 影像总目录里是否含黄金"
$总目录 = Join-Path $索引目录 "影像总目录.md"
if (Test-Path $总目录) {
    $命 = (Get-Content $总目录 -Encoding UTF8 | Where-Object { $_ -match $词 }).Count
    Write-Host "   影像总目录.md 中含『$词』的行数：$命"
    Write-Host "   文件时间：$((Get-Item $总目录).LastWriteTime)"
}

Write-Host "`n[4] 直接调用本机搜索接口（用 curl，需要 30-60 秒）…"
$密码 = ""
if (Test-Path $密码文件) { $密码 = (Get-Content $密码文件 -Raw).Trim() }
try {
    # curl 自带现代 TLS 与中文编码处理，比 PowerShell 5.1 的 Invoke-WebRequest 可靠
    $原始 = & curl.exe -k -s -G "https://127.0.0.1:8000/api/search" --data-urlencode "q=$词" -H "X-Token: $密码" --max-time 200
    $d = $原始 | ConvertFrom-Json
    Write-Host "   √ 照片 $($d.照片.Count) 张，视频 $($d.视频.Count) 个" -ForegroundColor Green
    $d.视频 | ForEach-Object { Write-Host "      -> $($_.名)" }
    if ($d.视频.Count -eq 0) {
        Write-Host "   （接口没返回视频，回答开头 150 字：）" -ForegroundColor Yellow
        Write-Host "   " ($d.回答.Substring(0, [Math]::Min(150, $d.回答.Length)))
    }
} catch {
    Write-Host "   × 调用失败：$($_.Exception.Message)" -ForegroundColor Red
}

Write-Host "`n[5] 服务进程与代码时间"
Get-Process python -ErrorAction SilentlyContinue | Select-Object Id, StartTime | Format-Table -AutoSize
Write-Host "   app.py 修改时间：$((Get-Item C:\kb\server\app.py).LastWriteTime)"
Write-Host "   app.py 大小：$((Get-Item C:\kb\server\app.py).Length) 字节"

Write-Host "`n[6] 服务日志最后 5 行"
Get-Content "C:\kb\server\server.log" -Tail 5 -ErrorAction SilentlyContinue

Write-Host ""
Read-Host "按回车键退出"
