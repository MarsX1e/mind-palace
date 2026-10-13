# ============================================================
#  检查云服务器上的知识库部署状态
#  在【你自己的电脑】上运行
#
#  用法：Win + R → powershell → 回车，然后粘贴：
#    powershell -ExecutionPolicy Bypass -File "C:\知识库\部署\检查服务器状态.ps1"
# ============================================================

$服务器IP = "1.2.3.4"   # ← 改成你的服务器公网 IP
$用户名   = "Administrator"

Write-Host "===============================================" -ForegroundColor Cyan
Write-Host "   检查 $服务器IP 的部署状态"
Write-Host "===============================================" -ForegroundColor Cyan

# ---------- 1. 端口连通性（不需要密码） ----------
Write-Host "`n[1] 端口检查"
foreach ($端口 in @(22, 8000)) {
    $测试 = Test-NetConnection -ComputerName $服务器IP -Port $端口 -WarningAction SilentlyContinue
    if ($测试.TcpTestSucceeded) {
        Write-Host "  √ $端口 端口可达" -ForegroundColor Green
    } else {
        Write-Host "  × $端口 端口不可达" -ForegroundColor Red
    }
}

# ---------- 2. 文件是否上传完成 ----------
Write-Host "`n[2] 检查服务器上的文件（会提示输入密码，只输一次）" -ForegroundColor Yellow
$文件信息 = ssh "${用户名}@${服务器IP}" "dir C:\kb /a 2>nul && echo ---SCRIPT--- && if exist C:\kb\deploy-server.ps1 (echo 部署脚本已就位) else (echo 缺少部署脚本) && echo ---TASK--- && schtasks /query /tn KB-Service /fo LIST 2>nul | findstr /i status"
if ($LASTEXITCODE -ne 0) {
    Write-Host "  × 连不上服务器或 C:\kb 不存在 —— 说明文件还没传上去" -ForegroundColor Red
} else {
    Write-Host $文件信息
}

# ---------- 3. 网页服务是否已在运行 ----------
Write-Host "`n[3] 检查网页服务（HTTPS 自签名证书，忽略证书告警）" -ForegroundColor Cyan
try { [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12 } catch { }
try { [System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true } } catch { }
try {
    $响应 = Invoke-WebRequest "https://${服务器IP}:8000/" -UseBasicParsing -TimeoutSec 15
    Write-Host "  √ 网页服务已运行（HTTPS $($响应.StatusCode)）" -ForegroundColor Green
    Write-Host "  → 手机打开：https://$服务器IP`:8000" -ForegroundColor Green
} catch {
    $码 = $_.Exception.Response.StatusCode.value__
    if ($码 -eq 401) {
        Write-Host "  √ 网页服务已运行（要求输入访问密码）" -ForegroundColor Green
        Write-Host "  → 手机打开：https://$服务器IP`:8000" -ForegroundColor Green
    } else {
        Write-Host "  × 网页服务还没起来（可能部署脚本没跑完）" -ForegroundColor Red
    }
}

Write-Host "`n===============================================" -ForegroundColor Cyan
Write-Host " 结论怎么看："
Write-Host "  · 第3步显示『网页服务已运行』→ 部署成功，直接用手机访问即可"
Write-Host "  · 第2步显示文件夹内容但第3步失败 → 文件传完了，但部署脚本没跑完，"
Write-Host "    重新运行『从本机上传并部署.ps1』并输入 c（只更新程序）即可"
Write-Host "  · 第2步就失败 → 文件没传完，重新运行『从本机上传并部署.ps1』"
Write-Host "    并直接回车（完整上传）"
Write-Host "===============================================" -ForegroundColor Cyan

Write-Host ""
Read-Host "按回车键关闭窗口"
