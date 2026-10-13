#!/bin/bash
# ============================================================
#  思维殿堂 · 云服务器一键部署脚本（Linux / Ubuntu 版）
#  适用：阿里云/腾讯云 轻量应用服务器，Ubuntu 22.04 或 24.04
#
#  用法：通过云控制台的「远程连接 / Workbench」登录后，
#        把本文件内容整段粘贴进终端，回车执行
#
#  前提：已把电脑上的 C:\知识库 上传到服务器的 /root/知识库
#        （在自己电脑的 PowerShell 里执行：
#          scp -r C:\知识库 root@你的公网IP:/root/ ）
# ============================================================

# ================== 可修改区 ==================
知识库目录="/root/知识库"
访问密码=""          # 手机打开网页要输的密码；留空则自动生成并显示
端口=8000
# ==============================================

echo "==============================================="
echo "        思维殿堂 · 服务器部署（Linux）"
echo "==============================================="

if [ "$(id -u)" != "0" ]; then
  echo "× 请用 root 用户执行（阿里云 Workbench 默认就是 root）"
  exit 1
fi

if [ ! -f "$知识库目录/server/app.py" ]; then
  echo "× 找不到 $知识库目录/server/app.py"
  echo "  请先在自己电脑的 PowerShell 里执行："
  echo "  scp -r D:\\知识库 root@<服务器IP>:/root/"
  exit 1
fi
echo "√ 知识库目录：$知识库目录"

# ---------- 1. 安装系统依赖 ----------
echo "正在安装系统组件（python3 / ffmpeg / exiftool）…"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-pip ffmpeg libimage-exiftool-perl curl > /dev/null
echo "√ 系统组件安装完成"

# ---------- 2. 安装 Python 库 ----------
echo "正在安装 Python 依赖库（fastapi / uvicorn / pypdf / pillow）…"
pip3 install -q --upgrade pip -i https://mirrors.aliyun.com/pypi/simple/ 2>/dev/null
if ! pip3 install -q -i https://mirrors.aliyun.com/pypi/simple/ fastapi uvicorn pypdf pillow 2>/dev/null; then
  # Ubuntu 24.04 及以上的外部管理环境需要加参数
  pip3 install -q --break-system-packages -i https://mirrors.aliyun.com/pypi/simple/ fastapi uvicorn pypdf pillow
fi
python3 -c "import fastapi, uvicorn, pypdf, PIL" || { echo "× 依赖安装失败"; exit 1; }
echo "√ Python 依赖安装完成"

# ---------- 3. 写入访问密码 ----------
if [ -z "$访问密码" ]; then
  访问密码=$(tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 10)
  echo "未指定访问密码，已自动生成：$访问密码"
fi
printf '%s' "$访问密码" > "$知识库目录/server/access_token.txt"
echo "√ 访问密码已写入"

# ---------- 4. 注册 systemd 开机自启服务 ----------
cat > /etc/systemd/system/kb.service <<EOF
[Unit]
Description=Mind Palace
After=network.target

[Service]
Type=simple
WorkingDirectory=$知识库目录/server
ExecStart=/usr/bin/python3 -m uvicorn app:app --host 0.0.0.0 --port $端口
Restart=always
RestartSec=5
StandardOutput=append:$知识库目录/server/server.log
StandardError=append:$知识库目录/server/server.log

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable kb > /dev/null 2>&1
systemctl restart kb
echo "√ 已注册开机自启服务（kb）"

# ---------- 5. 放行防火墙 ----------
if command -v ufw > /dev/null 2>&1; then
  ufw allow $端口/tcp > /dev/null 2>&1 && echo "√ 已放行 ufw 防火墙端口 $端口"
fi

# ---------- 6. 自检 ----------
echo "等待服务启动…"
sleep 6
if curl -s --max-time 20 "http://127.0.0.1:$端口/api/stats" > /tmp/kb_check.txt; then
  echo "√ 服务已在运行：$(cat /tmp/kb_check.txt)"
else
  echo "× 本地访问失败，查看日志：tail -50 $知识库目录/server/server.log"
fi

# ---------- 7. 显示访问地址 ----------
公网IP=$(curl -s --max-time 5 http://100.100.100.200/latest/meta-data/eipv4)
echo ""
echo "==============================================="
echo "  部署完成！"
echo "==============================================="
if [ -n "$公网IP" ]; then
  echo "  手机访问地址：http://$公网IP:$端口"
else
  echo "  手机访问地址：http://<你的服务器公网IP>:$端口"
fi
echo "  访问密码：$访问密码"
echo ""
echo "注意：还需在云控制台的【防火墙 / 安全组】里放行 TCP $端口"
echo "      阿里云轻量：控制台 → 服务器详情 → 防火墙 → 添加规则"
