# ============================================================
#  重启知识库服务（并清理占用 8000 端口的僵尸进程）
#  在服务器上执行：
#    powershell -ExecutionPolicy Bypass -File C:\kb\tools\restart-service.ps1
# ============================================================

try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

$服务目录 = "C:\kb\server"
$日志 = Join-Path $服务目录 "server.log"

function 说($文字, $颜色 = "Cyan") { Write-Host $文字 -ForegroundColor $颜色 }

说 "==============================================="
说 "   重启知识库服务"
说 "==============================================="

说 "`n[1] 停止计划任务…"
Stop-ScheduledTask -TaskName KB-Service -ErrorAction SilentlyContinue

说 "`n[2] 结束占用 8000 端口的进程…"
$占用 = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
foreach ($连接 in $占用) {
    try {
        Stop-Process -Id $连接.OwningProcess -Force -ErrorAction SilentlyContinue
        说 "   已结束进程 $($连接.OwningProcess)" "Yellow"
    } catch { }
}
Get-Process python -ErrorAction SilentlyContinue | ForEach-Object {
    Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 3

说 "`n[3] 启动计划任务…"
Start-ScheduledTask -TaskName KB-Service
Start-Sleep -Seconds 10

说 "`n[4] 本地自测（HTTPS，忽略证书告警）…"
# PowerShell 5.1 默认只用 TLS 1.0，必须显式启用 TLS 1.2 才能连上现代 HTTPS
try { [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12 } catch { }
[System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }
$本地好 = $false
try {
    $码 = (Invoke-WebRequest "https://127.0.0.1:8000/" -UseBasicParsing -TimeoutSec 20).StatusCode
    说 "   √ 本地 HTTPS 正常（HTTP $码）" "Green"
    $本地好 = $true
} catch {
    $内部 = $_.Exception.Response.StatusCode.value__
    if ($内部 -eq 401) {
        说 "   √ 本地 HTTPS 正常（要求密码）" "Green"
        $本地好 = $true
    } else {
        说 "   × 本地失败：$($_.Exception.Message)" "Red"
    }
}

说 "`n[5] 端口监听情况：" "Cyan"
Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue |
    Select-Object LocalAddress, LocalPort, OwningProcess | Format-Table -AutoSize

说 "[6] 日志尾部（最后 20 行）：" "Cyan"
if (Test-Path $日志) {
    Get-Content $日志 -Tail 20 -ErrorAction SilentlyContinue | ForEach-Object { Write-Host "   $_" -ForegroundColor DarkGray }
} else {
    说 "   日志文件不存在：$日志" "Yellow"
}

说 "`n[7] 任务状态：" "Cyan"
Get-ScheduledTask -TaskName KB-Service -ErrorAction SilentlyContinue |
    Select-Object TaskName, State | Format-Table -AutoSize

if ($本地好) { 说 "`n√ 服务已恢复，手机可以访问 https://1.2.3.4:8000" "Green" }
else { 说 "`n× 服务仍未起来，请把上面的日志发给我" "Red" }

Write-Host ""
Read-Host "按回车键退出"
