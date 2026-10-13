# ============================================================
#  思维殿堂 · 云服务器一键部署脚本
#  适用：Windows Server 2022（阿里云/腾讯云轻量应用服务器）
#
#  用法（三选一）：
#   A. 把本文件复制到服务器，右键 →「使用 PowerShell 运行」
#   B. 在服务器上以管理员身份打开 PowerShell，粘贴本文件全部内容后回车
#   C. 粘贴到阿里云控制台的「远程连接」终端里
#
#  前提：已把电脑上的 C:\知识库 整个文件夹复制到服务器的 C:\知识库
# ============================================================

# ================== 可修改区 ==================
$知识库目录 = "C:\知识库"
$访问密码   = ""        # 手机打开网页时要输的密码；留空则自动随机生成并显示
$端口       = 8000      # 网页端口，一般不用改
# ==============================================

function 提示($文字, $颜色 = "Cyan") { Write-Host $文字 -ForegroundColor $颜色 }

提示 "==============================================="
提示 "        思维殿堂 · 服务器部署"
提示 "==============================================="

# ---------- 0. 管理员检查 ----------
$是管理员 = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $是管理员) {
    提示 "× 请用【管理员身份】运行 PowerShell / 本脚本" "Red"
    return
}

# ---------- 1. 检查知识库文件夹 ----------
$服务器目录 = Join-Path $知识库目录 "server"
if (-not (Test-Path (Join-Path $服务器目录 "app.py"))) {
    提示 "× 找不到 $服务器目录\app.py" "Red"
    提示 "  请先把电脑上的 C:\知识库 整个文件夹复制到服务器的 $知识库目录" "Yellow"
    提示 "  （用远程桌面登录服务器后，直接在资源管理器里复制粘贴即可）" "Yellow"
    return
}
提示 "√ 知识库目录：$知识库目录"

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
    提示 "未检测到 Python，正在下载安装（约 25MB，需几分钟，请耐心等待）…" "Yellow"
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
    if (-not $下载好) { 提示 "× Python 下载失败：请确认服务器能正常上外网" "Red"; return }
    提示 "  正在静默安装 Python…"
    Start-Process -FilePath $安装包 -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1 Include_pip=1" -Wait
    $python = 找Python
    if (-not $python) { $python = "C:\Program Files\Python312\python.exe" }
}
提示 "√ Python：$python"
& $python --version

# ---------- 3. 安装依赖库 ----------
提示 "正在安装依赖库（fastapi / uvicorn / pypdf / pillow）…"
& $python -m pip install --quiet --disable-pip-version-check --upgrade pip -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com 2>$null
& $python -m pip install --quiet --disable-pip-version-check -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com fastapi uvicorn pypdf pillow
if ($LASTEXITCODE -ne 0) { 提示 "× 依赖安装失败，请检查网络后重试" "Red"; return }
提示 "√ 依赖安装完成"

# ---------- 4. 写入访问密码 ----------
if ([string]::IsNullOrWhiteSpace($访问密码)) {
    $字符集 = (48..57) + (65..90) + (97..122)
    $访问密码 = -join ($字符集 | Get-Random -Count 10 | ForEach-Object { [char]$_ })
    提示 "未指定访问密码，已自动生成：$访问密码" "Yellow"
}
$token路 = Join-Path $服务器目录 "access_token.txt"
[System.IO.File]::WriteAllText($token路, $访问密码, (New-Object System.Text.UTF8Encoding($false)))
提示 "√ 访问密码已写入"

# ---------- 5. 放行 Windows 防火墙 ----------
$规则名 = "思维殿堂端口 $端口"
if (-not (Get-NetFirewallRule -DisplayName $规则名 -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName $规则名 -Direction Inbound -Protocol TCP -LocalPort $端口 -Action Allow | Out-Null
    提示 "√ 已放行 Windows 防火墙端口 $端口"
} else {
    提示 "√ 防火墙规则已存在"
}

# ---------- 6. 注册开机自启服务 ----------
$任务名 = "思维殿堂服务"
$日志 = Join-Path $服务器目录 "server.log"
$参数 = "/c cd /d `"$服务器目录`" && `"$python`" -m uvicorn app:app --host 0.0.0.0 --port $端口 >> `"$日志`" 2>&1"
$动作 = New-ScheduledTaskAction -Execute "cmd.exe" -Argument $参数
$触发器 = New-ScheduledTaskTrigger -AtStartup
$主体 = New-ScheduledTaskPrincipal -UserId "SYSTEM" -RunLevel Highest
$设置 = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName $任务名 -Action $动作 -Trigger $触发器 -Principal $主体 -Settings $设置 -Force | Out-Null
Stop-ScheduledTask -TaskName $任务名 -ErrorAction SilentlyContinue
Start-ScheduledTask -TaskName $任务名
提示 "√ 已注册开机自启（任务名：$任务名）"

# ---------- 7. 启动自检 ----------
提示 "等待服务启动…"
Start-Sleep -Seconds 8
$本地正常 = $false
try {
    $响应 = Invoke-WebRequest "http://127.0.0.1:$端口/api/stats" -UseBasicParsing -TimeoutSec 30
    提示 "√ 服务已在运行：$($响应.Content)" "Green"
    $本地正常 = $true
} catch {
    提示 "× 本地访问失败，请查看日志：$日志" "Red"
}

# ---------- 8. 显示访问地址 ----------
$公网IP = $null
try { $公网IP = (Invoke-RestMethod -Uri "http://100.100.100.200/latest/meta-data/eipv4" -TimeoutSec 5) } catch { }
if (-not $公网IP) {
    try { $公网IP = (Invoke-RestMethod -Uri "http://100.100.100.200/latest/meta-data/public-ipv4" -TimeoutSec 5) } catch { }
}

Write-Host ""
提示 "===============================================" "Green"
if ($本地正常) { 提示 "  部署完成！" "Green" } else { 提示 "  部署完成但服务未正常启动，请看日志" "Yellow" }
提示 "===============================================" "Green"
if ($公网IP) { 提示 "  手机访问地址：http://$公网IP`:$端口" "Green" }
else { 提示 "  手机访问地址：http://<你的服务器公网IP>:$端口" "Green" }
提示 "  访问密码：$访问密码" "Green"
Write-Host ""
提示 "注意：还需在云控制台的【防火墙 / 安全组】里放行 TCP $端口 端口" "Yellow"
提示 "      （阿里云轻量：控制台 → 服务器详情 → 防火墙 → 添加规则）" "Yellow"
