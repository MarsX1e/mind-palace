# ============================================================
#  思维殿堂 · 从本机上传并部署到云服务器
#  在【你自己的电脑】上运行（不需要管理员）
#
#  用法：
#    1. Win + R → 输入 powershell → 回车
#    2. 粘贴这一行并回车：
#       powershell -ExecutionPolicy Bypass -File "C:\知识库\部署\从本机上传并部署.ps1"
#
#  前提：阿里云控制台防火墙已放行 TCP 22（SSH）和 TCP 8000（网页）
# ============================================================

$服务器IP = "1.2.3.4"   # ← 改成你的服务器公网 IP
$用户名   = "Administrator"
$本地目录 = "C:\知识库"
$远程目录 = "C:/kb"                        # 服务器目标目录（英文路径，避免中文乱码）
$远程部署脚本 = "C:\kb\deploy-server.ps1"

# 让 SSH 返回的中文正常显示
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

Write-Host "===============================================" -ForegroundColor Cyan
Write-Host "   上传并部署知识库到 $服务器IP" -ForegroundColor Cyan
Write-Host "===============================================" -ForegroundColor Cyan

try {
    # ---------- 1. 连通性检查 ----------
    Write-Host "`n[1/5] 检查 SSH 端口（22）是否可达…"
    $测试 = Test-NetConnection -ComputerName $服务器IP -Port 22 -WarningAction SilentlyContinue
    if (-not $测试.TcpTestSucceeded) {
        Write-Host "× 连不上服务器的 22 端口，请检查：" -ForegroundColor Red
        Write-Host "   1) 阿里云控制台 → 实例 → 防火墙 → 是否已放行 TCP 22" -ForegroundColor Yellow
        Write-Host "   2) 服务器上 sshd 是否在运行" -ForegroundColor Yellow
        throw "22 端口不通"
    }
    Write-Host "√ 22 端口可达" -ForegroundColor Green

    # ---------- 2. 选择模式 ----------
    Write-Host "`n[2/5] 请选择本次要做什么：" -ForegroundColor Cyan
    Write-Host "      直接回车 = 第一次部署（完整上传全部资料）" -ForegroundColor White
    Write-Host "      输入 n  = 更新程序和资料" -ForegroundColor White
    Write-Host "      输入 c  = 只更新程序（几秒钟，改了代码后用它）" -ForegroundColor White
    Write-Host "      输入 i  = 只同步索引（识图/OCR/检索索引，几十秒，不重传照片视频）" -ForegroundColor White
    $回答 = Read-Host "      你的选择"
    $模式 = "完整"
    if ($回答 -eq "n" -or $回答 -eq "N") { $模式 = "全部更新" }
    if ($回答 -eq "c" -or $回答 -eq "C") { $模式 = "只更新程序" }
    if ($回答 -eq "i" -or $回答 -eq "I") { $模式 = "只同步索引" }

    if (-not (Test-Path $本地目录)) { throw "找不到 $本地目录" }

    # 上传前统一给所有 .ps1 补 BOM，避免服务器 PowerShell 把中文读成乱码
    Write-Host "`n[3/5] 检查脚本编码（自动补 BOM）…" -ForegroundColor Cyan
    $补正数 = 0
    Get-ChildItem -Path $本地目录 -Recurse -Filter *.ps1 -File -ErrorAction SilentlyContinue | ForEach-Object {
        try {
            $原始 = [System.IO.File]::ReadAllBytes($_.FullName)
            $有BOM = ($原始.Length -ge 3 -and $原始[0] -eq 0xEF -and $原始[1] -eq 0xBB -and $原始[2] -eq 0xBF)
            if (-not $有BOM) {
                $内容 = [System.IO.File]::ReadAllText($_.FullName, [System.Text.Encoding]::UTF8)
                [System.IO.File]::WriteAllText($_.FullName, $内容, (New-Object System.Text.UTF8Encoding($true)))
                Write-Host "   已补 BOM：$($_.Name)" -ForegroundColor DarkGray
                $补正数++
            }
        } catch { }
    }
    Write-Host "   √ 编码检查完成（补正 $补正数 个文件）" -ForegroundColor Green

    # ---------- 4. 上传 ----------
    if ($模式 -eq "完整") {
        Write-Host "`n[3/5] 开始完整上传（约 4GB，取决于你的上行带宽，可能 20-60 分钟）…" -ForegroundColor Cyan
        Write-Host "      下一步会提示输入服务器 Administrator 密码（输入时不显示字符，正常）`n" -ForegroundColor Yellow
        # 目标目录不存在时，scp 会直接创建它
        scp -r "$本地目录" "${用户名}@${服务器IP}:${远程目录}"
    } elseif ($模式 -eq "只同步索引") {
        Write-Host "`n[3/5] 只同步索引目录（识图缓存 / OCR 结果 / 检索索引）…" -ForegroundColor Cyan
        Write-Host "      下一步会提示输入服务器 Administrator 密码`n" -ForegroundColor Yellow
        $索引目录 = Join-Path $本地目录 "00-影像资料\索引"
        if (-not (Test-Path $索引目录)) { throw "找不到索引目录：$索引目录" }
        $目标 = "${用户名}@${服务器IP}:${远程目录}/00-影像资料/"
        scp -r "$索引目录" $目标
    } else {
        Write-Host "`n[3/5] 开始上传（$模式）…" -ForegroundColor Cyan
        Write-Host "      下一步会提示输入服务器 Administrator 密码`n" -ForegroundColor Yellow
        $要传 = @("$本地目录\server", "$本地目录\tools", "$本地目录\deploy-server.ps1")
        if (Test-Path "$本地目录\部署") { $要传 += "$本地目录\部署" }
        if ($模式 -eq "全部更新") {
            foreach ($名字 in @("00-影像资料", "01-书籍扫描", "02-笔记", "03-素材卡片", "04-写作项目", "05-AI问答导出")) {
                $路径 = Join-Path $本地目录 $名字
                if (Test-Path $路径) { $要传 += $路径 }
            }
        }
        $目标 = "${用户名}@${服务器IP}:${远程目录}/"
        scp -r @要传 $目标
    }
    if ($LASTEXITCODE -ne 0) { throw "上传失败（密码错误或网络中断）。重新运行本脚本，输入 n 走增量更新即可。" }
    Write-Host "√ 上传完成" -ForegroundColor Green

    # ---------- 4. 远程部署 ----------
    Write-Host "`n[4/5] 在服务器上执行部署（再次输入密码）…`n" -ForegroundColor Cyan
    ssh "${用户名}@${服务器IP}" "powershell -ExecutionPolicy Bypass -File $远程部署脚本"
    if ($LASTEXITCODE -ne 0) { throw "远程部署返回错误码 $LASTEXITCODE，请把上面的输出发我" }

    # ---------- 5. 完成 ----------
    Write-Host "`n[5/5] 全部完成！" -ForegroundColor Green
    Write-Host "`n用手机（关掉 WiFi，走 4G/5G）打开：" -ForegroundColor Green
    Write-Host "   https://${服务器IP}:8000" -ForegroundColor Green
    Write-Host "访问密码 = 上面部署脚本打印的那串（服务器上可查 C:\kb\server\access_token.txt）" -ForegroundColor Yellow
}
catch {
    Write-Host "`n==============================" -ForegroundColor Red
    Write-Host " 出错了：$($_.Exception.Message)" -ForegroundColor Red
    Write-Host "==============================" -ForegroundColor Red
    Write-Host "把上面的红字截图发我即可。" -ForegroundColor Yellow
}

Write-Host ""
Read-Host "按回车键关闭窗口"
