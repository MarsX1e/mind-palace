# ============================================================
#  Mind Palace - Server Deployment (Windows)
#  思维殿堂 · 服务器一键部署脚本（英文文件名，避免远程执行时中文乱码）
#
#  会自动识别自己所在的文件夹作为知识库根目录
#  （即：本文件放在 <知识库>\deploy-server.ps1，则根目录 = <知识库>）
#
#  用法：在服务器上以管理员身份运行
#     powershell -ExecutionPolicy Bypass -File C:\kb\deploy-server.ps1
# ============================================================

# ================== 可修改区 ==================
$访问密码 = ""   # ← 想固定密码就填在这里，留空则自动生成/沿用   # 网页访问密码；留空 "" 则沿用服务器上已有的密码
$端口     = 8000      # 网页端口
# ==============================================

function 提示($文字, $颜色 = "Cyan") { Write-Host $文字 -ForegroundColor $颜色 }

# SSH 远程执行时用 UTF-8 输出，避免本机看到乱码
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

# 自动识别知识库目录（本脚本所在目录）
if ($PSCommandPath) {
    $知识库目录 = Split-Path -Parent $PSCommandPath
} else {
    $知识库目录 = "C:\kb"
}

提示 "==============================================="
提示 "        思维殿堂 · 服务器部署"
提示 "==============================================="
提示 "知识库目录：$知识库目录"

# ---------- 0. 管理员检查 ----------
$是管理员 = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $是管理员) {
    提示 "× 请用【管理员身份】运行 PowerShell" "Red"
    Read-Host "按回车退出"
    exit 1
}

# ---------- 1. 检查目录 ----------
$服务器目录 = Join-Path $知识库目录 "server"
if (-not (Test-Path (Join-Path $服务器目录 "app.py"))) {
    提示 "× 找不到 $服务器目录\app.py，请确认文件已上传完整" "Red"
    Read-Host "按回车退出"
    exit 1
}
提示 "√ 程序文件检查通过" "Green"

# ---------- 2. 准备 Python ----------
function 找Python {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
    foreach ($候选 in @("python", "python3", "py")) {
        try { $命令 = Get-Command $候选 -ErrorAction Stop; if ($命令.Source) { return $命令.Source } } catch { }
    }
    foreach ($路径 in @("C:\Program Files\Python312\python.exe", "C:\Program Files\Python313\python.exe",
            "C:\Program Files\Python311\python.exe", "C:\Program Files\Python310\python.exe")) {
        if (Test-Path $路径) { return $路径 }
    }
    return $null
}

$python = 找Python
if (-not $python) {
    提示 "未检测到 Python，正在下载安装（约 25MB，需几分钟）…" "Yellow"
    $安装包 = Join-Path $env:TEMP "python-setup.exe"
    $镜像们 = @(
        "https://mirrors.huaweicloud.com/python/3.12.7/python-3.12.7-amd64.exe",
        "https://mirrors.aliyun.com/python-release/windows/python-3.12.7-amd64.exe",
        "https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe"
    )
    $下载好 = $false
    foreach ($镜像 in $镜像们) {
        try {
            提示 "  尝试：$镜像"
            Invoke-WebRequest -Uri $镜像 -OutFile $安装包 -TimeoutSec 600 -UseBasicParsing
            $下载好 = $true; break
        } catch { 提示 "  该镜像不可用，换下一个" "DarkGray" }
    }
    if (-not $下载好) { 提示 "× Python 下载失败：请确认服务器能访问外网" "Red"; Read-Host "按回车退出"; exit 1 }
    提示 "  正在静默安装 Python…"
    Start-Process -FilePath $安装包 -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1 Include_pip=1" -Wait
    $python = 找Python
    if (-not $python) { $python = "C:\Program Files\Python312\python.exe" }
}
提示 "√ Python：$python" "Green"
& $python --version

# ---------- 3. 安装依赖库 ----------
提示 "正在安装依赖库（fastapi / uvicorn / pypdf / pillow / cryptography / numpy）…"
$pip输出 = & $python -m pip install --disable-pip-version-check --no-input -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com fastapi uvicorn pypdf pillow cryptography numpy 2>&1
$pip码 = $LASTEXITCODE
if ($pip码 -ne 0) {
    提示 "阿里云镜像失败（pip 返回 $pip码），改用官方源重试…" "Yellow"
    $pip输出 = & $python -m pip install --disable-pip-version-check --no-input fastapi uvicorn pypdf pillow cryptography numpy 2>&1
    $pip码 = $LASTEXITCODE
}
if ($pip码 -ne 0) {
    提示 "× 依赖安装失败（pip 返回 $pip码），最后几行输出：" "Red"
    $pip输出 | Select-Object -Last 15 | ForEach-Object { Write-Host "   $_" -ForegroundColor DarkGray }
    Read-Host "按回车退出"
    exit 1
}
提示 "√ 依赖安装完成" "Green"

# ---------- 3.5 生成 HTTPS 证书 ----------
$证书 = Join-Path $服务器目录 "cert.pem"
$私钥 = Join-Path $服务器目录 "key.pem"
if (-not (Test-Path $证书)) {
    提示 "正在生成 HTTPS 证书（浏览器会提示『不安全』，点继续访问即可）…"
    $公网IP = ""
    try { $公网IP = (Invoke-RestMethod -Uri "http://100.100.100.200/latest/meta-data/eipv4" -TimeoutSec 5) } catch { }
    提示 "  将绑定这些地址：$公网IP, 127.0.0.1" "DarkGray"
    $证书脚本 = Join-Path $知识库目录 "tools\生成证书.py"
    if (-not (Test-Path $证书脚本)) {
        提示 "  × 找不到 $证书脚本（tools 目录没上传完整？）" "Red"
    } else {
        $证书参数 = @($证书脚本)
        if ($公网IP) { $证书参数 += $公网IP }
        $证书参数 += "127.0.0.1"
        $证书输出 = & $python @证书参数 2>&1
        $证书输出 | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkGray }
    }
} else {
    提示 "√ HTTPS 证书已存在" "Green"
}
$启用HTTPS = (Test-Path $证书) -and (Test-Path $私钥)
if ($启用HTTPS) { 提示 "√ 将启用 HTTPS 加密访问" "Green" } else { 提示 "! 证书不可用，暂时用 HTTP" "Yellow" }

# ---------- 4. 访问密码（已有则沿用，不会每次都换） ----------
$token路 = Join-Path $服务器目录 "access_token.txt"
if ([string]::IsNullOrWhiteSpace($访问密码)) {
    if (Test-Path $token路) {
        $访问密码 = (Get-Content $token路 -Raw).Trim()
        提示 "沿用已有访问密码：$访问密码" "Yellow"
    } else {
        $字符集 = (48..57) + (65..90) + (97..122)
        $访问密码 = -join ($字符集 | Get-Random -Count 10 | ForEach-Object { [char]$_ })
        提示 "首次部署，已自动生成访问密码：$访问密码" "Yellow"
    }
}
$token路 = Join-Path $服务器目录 "access_token.txt"
[System.IO.File]::WriteAllText($token路, $访问密码, (New-Object System.Text.UTF8Encoding($false)))
提示 "√ 访问密码已写入" "Green"

# ---------- 5. 放行 Windows 防火墙 ----------
$规则名 = "KB-Port-$端口"
if (-not (Get-NetFirewallRule -DisplayName $规则名 -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName $规则名 -Direction Inbound -Protocol TCP -LocalPort $端口 -Action Allow | Out-Null
    提示 "√ 已放行 Windows 防火墙端口 $端口" "Green"
} else {
    提示 "√ 防火墙规则已存在" "Green"
}

# ---------- 6. 注册开机自启 ----------
$任务名 = "KB-Service"
$日志 = Join-Path $服务器目录 "server.log"
$ssl参数 = ""
if ($启用HTTPS) { $ssl参数 = " --ssl-certfile `"$证书`" --ssl-keyfile `"$私钥`"" }
$参数 = "/c cd /d `"$服务器目录`" && `"$python`" -m uvicorn app:app --host 0.0.0.0 --port $端口$ssl参数 >> `"$日志`" 2>&1"
$动作 = New-ScheduledTaskAction -Execute "cmd.exe" -Argument $参数
$触发器 = New-ScheduledTaskTrigger -AtStartup
$主体 = New-ScheduledTaskPrincipal -UserId "SYSTEM" -RunLevel Highest
$设置 = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName $任务名 -Action $动作 -Trigger $触发器 -Principal $主体 -Settings $设置 -Force | Out-Null
Stop-ScheduledTask -TaskName $任务名 -ErrorAction SilentlyContinue
Start-ScheduledTask -TaskName $任务名
提示 "√ 已注册开机自启（任务名：$任务名）" "Green"

# ---------- 7. 自检 ----------
提示 "等待服务启动…"
Start-Sleep -Seconds 10
$本地正常 = $false
$协议 = if ($启用HTTPS) { "https" } else { "http" }
try { [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12 } catch { }
try { [System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true } } catch { }
try {
    $响应 = Invoke-WebRequest "${协议}://127.0.0.1:$端口/api/stats" -UseBasicParsing -TimeoutSec 30 `
        -Headers @{ "X-Token" = $访问密码 }
    提示 "√ 服务已运行：$($响应.Content)" "Green"
    $本地正常 = $true
} catch {
    $码 = $_.Exception.Response.StatusCode.value__
    if ($码 -eq 401) {
        提示 "√ 服务已运行（访问密码校验正常）" "Green"
        $本地正常 = $true
    } else {
        提示 "× 本地访问失败，查看日志：$日志" "Red"
    }
}

# ---------- 8. 输出结果 ----------
Write-Host ""
提示 "===============================================" "Green"
if ($本地正常) { 提示 "  部署完成！" "Green" } else { 提示 "  部署已执行，但服务未正常启动" "Yellow" }
提示 "===============================================" "Green"
提示 "  访问密码：$访问密码" "Green"
$公网 = ""
try { $公网 = (Invoke-RestMethod -Uri "http://100.100.100.200/latest/meta-data/eipv4" -TimeoutSec 5) } catch { }
if ($公网) { 提示 "  访问地址：$协议`://$公网`:$端口" "Green" }
Write-Host ""
提示 "还需确认：阿里云控制台 → 防火墙 → 已放行 TCP $端口" "Yellow"
if ($启用HTTPS) { 提示 "浏览器提示『不安全』是正常的（自签名证书），点『继续访问』即可" "Yellow" }
Write-Host ""
Read-Host "按回车键退出"
