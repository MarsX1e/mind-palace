# ============================================================
#  在服务器上安装 Tailscale（内网加密隧道）
#  运行方式（在你自己的电脑上执行这条命令）：
#    ssh Administrator@1.2.3.4 "powershell -ExecutionPolicy Bypass -File C:\kb\tools\install-tailscale.ps1"
#
#  前提：你已经在 https://tailscale.com 注册好账号（用 Google/微软/邮箱都行）
# ============================================================

$ErrorActionPreference = "Continue"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

function 说($文字, $颜色 = "Cyan") { Write-Host $文字 -ForegroundColor $颜色 }

说 "==============================================="
说 "   安装 Tailscale（把服务器接入你的私人隧道）"
说 "==============================================="

$ts = "C:\Program Files\Tailscale\tailscale.exe"

if (-not (Test-Path $ts)) {
    说 "`n[1/4] 下载安装包…" "Yellow"
    $安装包 = Join-Path $env:TEMP "tailscale-setup.exe"
    try {
        Invoke-WebRequest -Uri "https://pkgs.tailscale.com/stable/tailscale-setup-latest.exe" `
            -OutFile $安装包 -UseBasicParsing -TimeoutSec 900
        说 "  √ 下载完成（$([math]::Round((Get-Item $安装包).Length / 1MB, 1)) MB）" "Green"
    } catch {
        说 "  × 下载失败：$($_.Exception.Message)" "Red"
        说 "  可以手动装：在服务器上打开 https://tailscale.com/download/windows 下载后双击安装" "Yellow"
        Read-Host "按回车退出"; exit 1
    }

    说 "`n[2/4] 静默安装（约 1 分钟）…" "Yellow"
    Start-Process msiexec.exe -ArgumentList "/i `"$安装包`" /quiet /norestart" -Wait
    Start-Sleep -Seconds 5
    if (-not (Test-Path $ts)) {
        说 "  × 安装未完成，请在服务器桌面上手动双击安装包" "Red"
        Read-Host "按回车退出"; exit 1
    }
    说 "  √ 安装完成" "Green"
} else {
    说 "`n[1/4] 已安装 Tailscale，跳过安装步骤" "Green"
}

说 "`n[2/4] 版本信息：" "Cyan"
& $ts version

说 "`n[3/4] 现在需要登录授权" "Yellow"
说 "  屏幕上会出现一个 https://login.tailscale.com/... 的链接" "White"
说 "  请把它复制到浏览器打开，用你的 Tailscale 账号登录并点 Authorize" "White"
说 ""
& $ts up

说 "`n[4/4] 服务器在隧道里的地址：" "Cyan"
$地址 = (& $ts ip -4) | Select-Object -First 1
if ($地址) {
    说 "  http://$地址`:8000" "Green"
    说 "  ↑ 手机上装好 Tailscale 并登录同一账号后，用这个地址访问知识库" "Green"
} else {
    说 "  × 还没拿到地址，说明授权没完成，请重新运行本脚本" "Red"
}

说 "`n把上面的地址告诉我，我带你做手机端和最后的安全收尾。" "Yellow"
Read-Host "按回车退出"
