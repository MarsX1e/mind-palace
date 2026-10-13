# ============================================================
#  诊断并重启知识库服务
#  在【你自己的电脑】上运行
#
#  用法：Win + R → powershell → 回车，粘贴：
#    powershell -ExecutionPolicy Bypass -File "C:\知识库\部署\诊断并重启服务.ps1"
#
#  说明：会要求输入服务器密码 1-2 次。若阿里云防火墙里 22 端口被禁用了，
#        请先在控制台启用它，或用控制台的"远程连接"进服务器操作。
# ============================================================

$服务器IP = "1.2.3.4"   # ← 改成你的服务器公网 IP
$用户名   = "Administrator"

try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

Write-Host "===============================================" -ForegroundColor Cyan
Write-Host "   诊断知识库服务（$服务器IP）"
Write-Host "===============================================" -ForegroundColor Cyan

# ---------- 1. 网页端口 ----------
Write-Host "`n[1] 网页端口 8000 是否可达"
$测试 = Test-NetConnection -ComputerName $服务器IP -Port 8000 -WarningAction SilentlyContinue
if ($测试.TcpTestSucceeded) { Write-Host "  √ 8000 端口可达" -ForegroundColor Green }
else { Write-Host "  × 8000 端口不可达（可能服务没运行，或阿里云防火墙禁用了 8000）" -ForegroundColor Red }

# ---------- 2. 服务器内部状态 ----------
Write-Host "`n[2] 读取服务器内部状态（需要输入密码）" -ForegroundColor Yellow
Write-Host "   ---- 当前访问密码 ----"
ssh "${用户名}@${服务器IP}" "type C:\kb\server\access_token.txt & echo. & echo ---- 最近日志 ---- & powershell -Command `"Get-Content C:\kb\server\server.log -Tail 12 -ErrorAction SilentlyContinue`" & echo ---- 任务状态 ---- & schtasks /query /tn KB-Service /fo LIST 2>nul"

# ---------- 3. 清理占用进程并重启（调用服务器上的脚本，避免多层引号问题） ----------
Write-Host "`n[3] 清理占用 8000 端口的进程，然后重启服务…（再输一次密码）" -ForegroundColor Yellow
ssh "${用户名}@${服务器IP}" "powershell -ExecutionPolicy Bypass -File C:\kb\tools\restart-service.ps1"

# ---------- 4. 再测一次 ----------
Start-Sleep -Seconds 3
Write-Host "`n[4] 重新测试外网访问（忽略自签名证书告警）" -ForegroundColor Cyan
try { [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12 } catch { }
try { [System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true } } catch { }
try {
    $响应 = Invoke-WebRequest "https://${服务器IP}:8000/" -UseBasicParsing -TimeoutSec 20
    Write-Host "  √ 网页已恢复（HTTPS $($响应.StatusCode)）" -ForegroundColor Green
    Write-Host "  → 手机刷新页面：https://$服务器IP`:8000，用上面『当前访问密码』登录" -ForegroundColor Green
} catch {
    $码 = $_.Exception.Response.StatusCode.value__
    if ($码 -eq 401) {
        Write-Host "  √ 网页已恢复（要求输入密码）" -ForegroundColor Green
        Write-Host "  → 手机打开：https://$服务器IP`:8000" -ForegroundColor Green
    } else {
        Write-Host "  × 还是打不开，把上面的输出（尤其是日志部分）截图发我" -ForegroundColor Red
    }
}

Write-Host ""
Read-Host "按回车键关闭窗口"
