# -*- coding: utf-8 -*-
"""知识库服务器配置：从现有文件里自动读密钥，避免重复填写"""

import json
import os
import re

服务器目录 = os.path.dirname(os.path.abspath(__file__))
根目录 = os.path.normpath(os.path.join(服务器目录, ".."))
脚本目录 = os.path.join(根目录, "tools")

照片目录 = os.path.join(根目录, "00-影像资料", "照片原图")
视频目录 = os.path.join(根目录, "00-影像资料", "视频原图")
索引目录 = os.path.join(根目录, "00-影像资料", "索引")
笔记目录 = os.path.join(根目录, "02-笔记")
素材目录 = os.path.join(根目录, "03-素材卡片")
书籍目录 = os.path.join(根目录, "01-书籍扫描", "已OCR")

视频描述文件 = os.path.join(索引目录, "视频描述.txt")

视频扩展名 = {".mp4", ".mov", ".m4v", ".3gp", ".avi", ".mkv"}
图片扩展名 = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".heic", ".heif"}


def 从脚本提取(pattern, 文件):
    """在脚本里找配置保底值（兼容 '变量 = "值"' 与 '变量 = xxx or "值"' 两种写法）"""
    try:
        with open(os.path.join(脚本目录, 文件), encoding="utf-8") as f:
            内容 = f.read()
        匹配 = re.search(pattern, 内容)
        return 匹配.group(1).strip() if 匹配 else ""
    except Exception:
        return ""


def 读配置():
    """读取根目录下的 config.json（推荐方式）。没有该文件时返回空字典，
    程序会自动退回"从各个文件里读密钥"的老方式，保证向后兼容。"""
    try:
        with open(os.path.join(根目录, "config.json"), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


配置 = 读配置()


# 阿里云 Key：config.json 优先，其次从识图脚本里读
阿里云Key = str(配置.get("阿里云Key", "")).strip() or 从脚本提取(r'阿里云API密钥\s*=[^\n]*?"(sk-[^"\n]+)"', "照片视频识图.py")
识图模型 = str(配置.get("识图模型", "")).strip() or 从脚本提取(r'模型名\s*=[^\n]*?"([a-zA-Z0-9._\-]+)"', "照片视频识图.py") or "qwen3-vl-plus"

# DeepSeek Key：config.json 优先，其次读 server/deepseek_key.txt
DeepSeekKey = str(配置.get("DeepSeekKey", "")).strip()
if not DeepSeekKey:
    try:
        with open(os.path.join(服务器目录, "deepseek_key.txt"), encoding="utf-8") as f:
            DeepSeekKey = f.read().strip()
    except Exception:
        DeepSeekKey = ""

# 访问密码：config.json 优先，其次读 server/access_token.txt
访问密码 = str(配置.get("访问密码", "")).strip()
if not 访问密码:
    try:
        with open(os.path.join(服务器目录, "access_token.txt"), encoding="utf-8") as f:
            访问密码 = f.read().strip()
    except Exception:
        访问密码 = ""
