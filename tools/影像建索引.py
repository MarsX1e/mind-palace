# -*- coding: utf-8 -*-
"""
影像资料建索引工具
==================
扫描 00-影像资料 下的照片和视频，读取 EXIF 里的 GPS 地理信息，
通过高德地图 API 反向解析出拍摄地点（省/市/区/附近地标），
生成《影像总目录.md》——把这个文件导入 AnythingLLM，就能对 AI 说：
「我需要一些新疆的风貌」，AI 会按地名找出对应的照片和视频。

依赖：ExifTool（读取照片和视频的GPS，单文件程序）
     下载：https://exiftool.org/  → 把 exiftool(-k).exe 改名为 exiftool.exe
     放到本脚本同目录，或安装到系统 PATH

使用前：把下面的 高德API密钥 填上（免费申请，见脚本底部说明）
运行：  python 影像建索引.py
"""

import csv
import json
import os
import subprocess
import sys
import time
import urllib.request

脚本目录 = os.path.dirname(os.path.abspath(__file__))


def 读根配置():
    """优先读知识库根目录的 config.json；没有则返回空"""
    try:
        with open(os.path.normpath(os.path.join(脚本目录, "..", "config.json")), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


_配置 = 读根配置()

# ================== 配置区 ==================
# 优先用根目录 config.json 里的"高德Key"；没有该文件时用下面的保底值。
# 申请地址：https://lbs.amap.com （个人开发者免费，注意要选「Web服务」类型）
高德API密钥 = str(_配置.get("高德Key", "")).strip() or ""
# ==========================================

照片目录 = os.path.normpath(os.path.join(脚本目录, "..", "00-影像资料", "照片原图"))
视频目录 = os.path.normpath(os.path.join(脚本目录, "..", "00-影像资料", "视频原图"))
输出目录 = os.path.normpath(os.path.join(脚本目录, "..", "00-影像资料", "索引"))
缓存文件 = os.path.join(输出目录, "逆地理缓存.json")
# ======================================================

支持的扩展名 = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp",
               ".mp4", ".mov", ".m4v", ".3gp"}


def 找_exiftool():
    """在本脚本目录和系统 PATH 里找 exiftool，找不到返回 None（照片可退回用 Pillow 读取）"""
    候选 = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "exiftool.exe"),
            "exiftool", "exiftool.exe"]
    for c in 候选:
        try:
            subprocess.run([c, "-ver"], capture_output=True, check=True)
            return c
        except Exception:
            continue
    return None


def 度分秒转小数(度分秒, 方向):
    度, 分, 秒 = [float(x) for x in 度分秒]
    值 = 度 + 分 / 60 + 秒 / 3600
    return -值 if 方向 in ("S", "W") else 值


def 用Pillow读元数据(文件路径):
    """不依赖 exiftool，读取照片 EXIF 中的 GPS（支持 jpg/png 等，不支持 HEIC 和视频）"""
    try:
        from PIL import Image
        with Image.open(文件路径) as img:
            exif = img.getexif()
            gps = exif.get_ifd(0x8825)  # GPSInfo
            if not gps or 2 not in gps or 4 not in gps:
                return None
            纬度 = 度分秒转小数(gps[2], gps.get(1, "N"))
            经度 = 度分秒转小数(gps[4], gps.get(3, "E"))
            拍摄时间 = str(exif.get(36867) or exif.get(306) or "未知时间")
            return {"经度": 经度, "纬度": 纬度, "拍摄时间": 拍摄时间}
    except Exception:
        return None


def 读元数据(exiftool, 文件路径):
    """优先用 exiftool（支持 HEIC 和视频）；没有时用 Pillow 读普通照片"""
    if exiftool is None:
        return 用Pillow读元数据(文件路径)
    参数 = [exiftool, "-j", "-n", "-fast",
            "-GPSPosition", "-GPSLatitude", "-GPSLongitude",
            "-DateTimeOriginal", "-CreateDate", "-MediaCreateDate",
            "-FileName", "-Directory", 文件路径]
    try:
        结果 = subprocess.run(参数, capture_output=True, text=True, encoding="utf-8")
        数据 = json.loads(结果.stdout)[0]
    except Exception:
        return None
    if "GPSPosition" not in 数据:
        return None  # 无GPS信息
    try:
        纬度, 经度 = [float(x) for x in str(数据["GPSPosition"]).split()]
    except Exception:
        return None
    拍摄时间 = (数据.get("DateTimeOriginal") or 数据.get("MediaCreateDate")
              or 数据.get("CreateDate") or "未知时间")
    return {"经度": 经度, "纬度": 纬度, "拍摄时间": str(拍摄时间)}


def 逆地理编码(经度, 纬度, 缓存):
    """调用高德 API 把坐标转成地名，带缓存避免重复扣配额"""
    键 = f"{经度:.5f},{纬度:.5f}"
    if 键 in 缓存:
        return 缓存[键]
    if not 高德API密钥:
        return None
    url = (f"https://restapi.amap.com/v3/geocode/regeo?location={经度},{纬度}"
           f"&key={高德API密钥}&extensions=all&radius=1000&output=json")
    try:
        with urllib.request.urlopen(url, timeout=10) as 响应:
            数据 = json.loads(响应.read().decode("utf-8"))
        if 数据.get("status") != "1":
            return None
        信息 = 数据["regeocode"]
        地址 = 信息.get("formatted_address", "")
        成分 = 信息.get("addressComponent", {})
        地标 = ""
        兴趣点 = 信息.get("pois") or []
        if 兴趣点:
            地标 = "、".join(p.get("name", "") for p in 兴趣点[:3])
        结果 = {
            "省": 成分.get("province", ""),
            "市": 成分.get("city", "") or 成分.get("province", ""),
            "区县": 成分.get("district", ""),
            "详细地址": 地址,
            "附近地标": 地标,
        }
    except Exception:
        return None
    缓存[键] = 结果
    time.sleep(0.15)  # 控制请求频率
    return 结果


def 主流程():
    if not 高德API密钥:
        print("提醒：尚未填写高德API密钥（脚本开头的 高德API密钥 = \"\"）。")
        print("本次运行只会列出带GPS的文件和坐标，没有地名。\n")

    os.makedirs(输出目录, exist_ok=True)
    exiftool = 找_exiftool()
    if exiftool is None:
        print("提示：未找到 exiftool，将用内置方式读取普通照片（jpg/png）。")
        print("      视频和 HEIC 格式需要 exiftool：")
        print("      https://exiftool.org 下载后把 exiftool(-k).exe 改名为 exiftool.exe，")
        print("      放到本脚本所在目录。\n")
    缓存 = {}
    if os.path.exists(缓存文件):
        with open(缓存文件, encoding="utf-8") as f:
            缓存 = json.load(f)

    记录 = []
    for 根目录, 类型 in [(照片目录, "照片"), (视频目录, "视频")]:
        for 目录路径, _, 文件名列表 in os.walk(根目录):
            for 文件名 in 文件名列表:
                if os.path.splitext(文件名)[1].lower() not in 支持的扩展名:
                    continue
                完整路径 = os.path.join(目录路径, 文件名)
                元数据 = 读元数据(exiftool, 完整路径)
                if not 元数据:
                    print(f"  跳过（无GPS信息）: {完整路径}")
                    continue
                地点 = 逆地理编码(元数据["经度"], 元数据["纬度"], 缓存)
                记录.append({"类型": 类型, "文件": 完整路径, **元数据,
                             **(地点 or {"省": "", "市": "", "区县": "",
                                         "详细地址": "", "附近地标": ""})})
                print(f"  已索引: {完整路径}")

    with open(缓存文件, "w", encoding="utf-8") as f:
        json.dump(缓存, f, ensure_ascii=False, indent=1)

    # 按省分组写 Markdown 目录（导入 AnythingLLM 后按省份检索）
    分组 = {}
    for r in 记录:
        分组.setdefault(r["省"] or "未知地区", []).append(r)

    md路径 = os.path.join(输出目录, "影像总目录.md")
    with open(md路径, "w", encoding="utf-8") as f:
        f.write("# 影像资料总目录（含拍摄地点）\n\n")
        f.write("本目录由脚本自动生成，每条记录：文件路径、拍摄时间、GPS坐标、拍摄地点。\n\n")
        for 省 in sorted(分组):
            f.write(f"\n## {省}\n\n")
            for r in sorted(分组[省], key=lambda x: x["拍摄时间"]):
                地点描述 = (f"{r['市']}{r['区县']}，{r['详细地址']}"
                            + (f"，附近：{r['附近地标']}" if r["附近地标"] else ""))
                f.write(f"- 【{r['类型']}】{r['文件']}\n")
                f.write(f"  - 拍摄时间：{r['拍摄时间']}；坐标：{r['纬度']:.5f}, {r['经度']:.5f}\n")
                f.write(f"  - 拍摄地点：{地点描述}\n")

        # 并入手工描述和AI识图描述（如存在）
        for 描述文件名, 节标题 in [("手工描述.md", "手工标注描述（照片/视频内容说明）"),
                                   ("AI识图描述.md", "AI识图描述（视觉模型自动生成）"),
                                   ("视频描述汇总.md", "视频描述汇总（用户手工填写）")]:
            描述路径 = os.path.join(输出目录, 描述文件名)
            if os.path.exists(描述路径):
                with open(描述路径, encoding="utf-8") as hf:
                    f.write(f"\n---\n\n## {节标题}\n\n")
                    f.write(hf.read())

    csv路径 = os.path.join(输出目录, "影像总目录.csv")
    with open(csv路径, "w", newline="", encoding="utf-8-sig") as f:
        写 = csv.DictWriter(f, fieldnames=["类型", "文件", "拍摄时间", "纬度", "经度",
                                           "省", "市", "区县", "详细地址", "附近地标"])
        写.writeheader()
        写.writerows(记录)

    print(f"\n完成！共索引 {len(记录)} 个文件（跳过无GPS的）。")
    print(f"- {md路径}  → 导入 AnythingLLM 供 AI 检索")
    print(f"- {csv路径} → 可用 Excel 打开浏览")


if __name__ == "__main__":
    主流程()
