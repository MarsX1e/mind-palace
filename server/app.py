# -*- coding: utf-8 -*-
"""
个人知识库手机端服务器
====================
功能：
- 统计并列出"未描述的视频"，手机上边播边写描述
- 手机上传照片/视频，自动触发 AI 识图与索引重建
- 手机向 DeepSeek 提问，检索知识库资料

运行：python -m uvicorn app:app --host 0.0.0.0 --port 8000
"""

import json
import os
import re
import subprocess
import threading
import time
import urllib.request

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

import config

import sys as _sys
if config.脚本目录 not in _sys.path:
    _sys.path.insert(0, config.脚本目录)
import 影像指纹 as 指纹  # noqa: E402  （去重指纹模块，放在 tools 目录）
import 知识检索 as 检索  # noqa: E402  （向量检索模块，放在 tools 目录）
import 文档指纹 as 文档  # noqa: E402  （文档去重模块，放在 tools 目录）

app = FastAPI(title="思维殿堂")

# 启动时确保数据目录存在（刚 clone 下来时目录是空的）
for _目录 in (config.照片目录, config.视频目录, config.索引目录, config.笔记目录,
              config.素材目录, config.书籍目录):
    try:
        os.makedirs(_目录, exist_ok=True)
    except Exception:
        pass


# ---------------- 访问密码 ----------------
失败记录 = {}          # 客户端 IP -> [失败时间戳, ...]
失败上限 = 10          # 窗口内允许的失败次数
失败窗口秒 = 600       # 窗口长度（秒）


def 校验密码(request: Request, x_token: str = Header(default=""), token: str = Query(default="")):
    """密码可以从请求头（X-Token）或网址参数（?token=）带过来。
    图片、视频这类 <img>/<video> 标签无法设置请求头，只能用网址参数。
    同一 IP 连续失败超过上限会被临时锁定，防止暴力破解。"""
    if not config.访问密码:
        return True

    客户端 = request.client.host if request.client else "未知"
    现在 = time.time()
    记录 = [t for t in 失败记录.get(客户端, []) if 现在 - t < 失败窗口秒]
    if len(记录) >= 失败上限:
        失败记录[客户端] = 记录
        raise HTTPException(status_code=429,
                            detail=f"密码错误次数过多，请 {失败窗口秒 // 60} 分钟后再试")

    if x_token == config.访问密码 or token == config.访问密码:
        失败记录.pop(客户端, None)      # 成功即清除失败记录
        return True

    记录.append(现在)
    失败记录[客户端] = 记录
    raise HTTPException(status_code=401, detail="需要访问密码")


# ---------------- 后台任务（识图 + 重建索引） ----------------
任务状态 = {"运行中": False, "日志": "", "待处理": False}


def 跑脚本(命令):
    任务状态["日志"] = ""
    过程 = subprocess.Popen(
        命令, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        cwd=config.根目录, text=True, encoding="utf-8", errors="replace")
    行列表 = []
    for 行 in 过程.stdout:
        行列表.append(行.rstrip())
        任务状态["日志"] = "\n".join(行列表[-30:])
    过程.wait()


def 触发处理():
    """先跑AI识图（缓存自动跳过已识别的），再重建索引。
    处理期间又有新上传时，会自动再跑一轮，不会漏掉。"""
    if 任务状态["运行中"]:
        任务状态["待处理"] = True
        return
    import sys

    def 循环跑():
        任务状态["运行中"] = True
        try:
            while True:
                任务状态["待处理"] = False
                跑脚本([sys.executable, os.path.join(config.脚本目录, "照片视频识图.py")])
                跑脚本([sys.executable, os.path.join(config.脚本目录, "影像建索引.py")])
                跑脚本([sys.executable, os.path.join(config.脚本目录, "知识检索.py")])
                if not 任务状态["待处理"]:
                    break
        finally:
            任务状态["运行中"] = False

    threading.Thread(target=循环跑).start()


def 触发索引重建():
    """只重建向量检索索引（不跑识图），用于书籍/笔记新增后"""
    if 任务状态["运行中"]:
        任务状态["待处理"] = True
        return
    import sys

    def 跑():
        任务状态["运行中"] = True
        try:
            跑脚本([sys.executable, os.path.join(config.脚本目录, "知识检索.py")])
        finally:
            任务状态["运行中"] = False

    threading.Thread(target=跑).start()


# ---------------- 视频描述读写 ----------------
def 读所有视频():
    列表 = []
    for 目录, _, 文件们 in os.walk(config.视频目录):
        for 名 in 文件们:
            if os.path.splitext(名)[1].lower() in config.视频扩展名:
                列表.append(名)
    return sorted(列表)


def 读描述():
    描述 = {}
    if os.path.exists(config.视频描述文件):
        with open(config.视频描述文件, encoding="utf-8") as f:
            for 行 in f:
                行 = 行.strip()
                if 行 and not 行.startswith("#") and "|" in 行:
                    名, _, 内容 = 行.partition("|")
                    描述[名.strip()] = 内容.strip()
    return 描述


def 写描述(文件名, 内容):
    行们 = []
    if os.path.exists(config.视频描述文件):
        with open(config.视频描述文件, encoding="utf-8") as f:
            行们 = f.read().splitlines()
    新行们, 已改 = [], False
    for 行 in 行们:
        if 行.strip().startswith("#") or "|" not in 行:
            新行们.append(行)
        elif 行.split("|")[0].strip() == 文件名:
            新行们.append(f"{文件名}|{内容}")
            已改 = True
        else:
            新行们.append(行)
    if not 已改:
        新行们.append(f"{文件名}|{内容}")
    with open(config.视频描述文件, "w", encoding="utf-8") as f:
        f.write("\n".join(新行们) + "\n")


# ---------------- API ----------------
@app.get("/api/stats")
def 统计(_=Depends(校验密码)):
    视频 = 读所有视频()
    描述 = 读描述()
    照片数 = sum(1 for 根, _, 文件们 in os.walk(config.照片目录) for f in 文件们
                 if os.path.splitext(f)[1].lower() in config.图片扩展名)
    return {"视频总数": len(视频),
            "已描述": sum(1 for v in 视频 if 描述.get(v)),
            "未描述": sum(1 for v in 视频 if not 描述.get(v)),
            "照片数": 照片数,
            "处理中": 任务状态["运行中"]}


@app.get("/api/videos")
def 视频列表(只看未描述: bool = Query(False), _=Depends(校验密码)):
    描述 = 读描述()
    结果 = [{"名": v, "已描述": bool(描述.get(v)), "描述": 描述.get(v, "")}
            for v in 读所有视频()]
    if 只看未描述:
        结果 = [x for x in 结果 if not x["已描述"]]
    return 结果


@app.get("/api/video/{name}")
def 播放视频(name: str, _=Depends(校验密码)):
    路径 = os.path.join(config.视频目录, os.path.basename(name))
    if not os.path.isfile(路径):
        raise HTTPException(404, "视频不存在")

    def 流():
        with open(路径, "rb") as f:
            while True:
                块 = f.read(1024 * 512)
                if not 块:
                    break
                yield 块
    return StreamingResponse(
        流(), media_type="video/mp4",
        headers={"Accept-Ranges": "bytes",
                 "Content-Length": str(os.path.getsize(路径))})


@app.post("/api/describe")
async  def 保存描述(request: Request, _=Depends(校验密码)):
    数据 = await request.json()
    名, 内容 = os.path.basename(数据.get("名", "")), 数据.get("描述", "").strip()
    if 名 not in 读所有视频():
        raise HTTPException(404, "视频不存在")
    写描述(名, 内容)
    return {"ok": True}


@app.put("/api/upload/{filename}")
async def 上传文件(filename: str, request: Request, _=Depends(校验密码)):
    数据 = await request.body()
    扩展名 = os.path.splitext(filename)[1].lower()
    名 = os.path.basename(filename)
    文档扩展名 = {".pdf", ".md", ".txt", ".markdown"}
    if 扩展名 in config.图片扩展名:
        目录, 类别 = config.照片目录, "照片"
    elif 扩展名 in config.视频扩展名:
        目录, 类别 = config.视频目录, "视频"
    elif 扩展名 == ".pdf":
        目录, 类别 = config.书籍目录, "书籍"
    elif 扩展名 in 文档扩展名:
        目录, 类别 = config.笔记目录, "笔记"
    else:
        raise HTTPException(400, "不支持的文件类型（支持：图片、视频、PDF、md、txt）")

    # ---------- 查重 ----------
    if 类别 in ("照片", "视频"):
        表 = 指纹.读指纹()
        新条目 = 指纹.图片指纹字节(数据) if 类别 == "照片" else 指纹.视频指纹字节(数据)
        for 其他类别 in ("照片", "视频"):
            for 已有名, 旧条目 in 表.get(其他类别, {}).items():
                if 旧条目.get("md5") and 旧条目["md5"] == 新条目.get("md5"):
                    return {"ok": True, "状态": "重复", "跳过": True,
                            "说明": f"与库里的 {已有名} 内容完全相同，已跳过"}
                if 类别 == "照片" and 其他类别 == "照片" and 指纹.可能近似重复(新条目, 旧条目):
                    return {"ok": True, "状态": "重复", "跳过": True,
                            "说明": f"与库里的 {已有名} 是同一张图（压缩或尺寸不同），已跳过"}
    else:
        # 文档查重：按内容 MD5 比对已有文档（只哈希大小相同的，避免无谓读取）
        新md5 = 指纹.算md5字节(数据)
        for 检查目录 in (config.书籍目录, config.笔记目录, config.素材目录):
            for 根, _, 文件们 in os.walk(检查目录):
                if os.path.basename(根) in ("pdf文本缓存", "thumbs"):
                    continue
                for 已有 in 文件们:
                    if os.path.splitext(已有)[1].lower() not in 文档扩展名:
                        continue
                    路 = os.path.join(根, 已有)
                    try:
                        if os.path.getsize(路) == len(数据) and 指纹.算md5(路) == 新md5:
                            return {"ok": True, "状态": "重复", "跳过": True,
                                    "说明": f"与库里的 {已有} 内容完全相同，已跳过"}
                    except Exception:
                        continue

    # ---------- 保存 ----------
    目标 = os.path.join(目录, 名)
    with open(目标, "wb") as out:
        out.write(数据)
    if 类别 in ("照片", "视频"):
        表.setdefault(类别, {})[名] = 新条目
        指纹.存指纹(表)

    触发处理()
    return {"ok": True, "状态": "已保存", "类型": 类别, "处理中": 任务状态["运行中"]}


# ---------------- 重复影像扫描与清理 ----------------
指纹状态 = {"运行中": False, "日志": ""}


def 后台刷新指纹():
    if 指纹状态["运行中"]:
        return

    def 跑():
        指纹状态["运行中"] = True
        行们 = []

        def 记录(文字):
            行们.append(str(文字))
            指纹状态["日志"] = "\n".join(行们[-20:])

        try:
            指纹.更新指纹(打印=记录)
        except Exception as e:
            记录(f"出错：{e}")
        finally:
            指纹状态["运行中"] = False

    threading.Thread(target=跑).start()


@app.post("/api/fingerprint/rebuild")
def 重建指纹(_=Depends(校验密码)):
    后台刷新指纹()
    return {"ok": True, "运行中": 指纹状态["运行中"]}


@app.get("/api/fingerprint/status")
def 指纹进度(_=Depends(校验密码)):
    return 指纹状态


@app.get("/api/duplicates")
def 查重复(_=Depends(校验密码)):
    if 指纹状态["运行中"]:
        return {"建库中": True, "组": [], "总数": 0}
    表 = 指纹.读指纹()
    if not 表.get("照片") and not 表.get("视频"):
        return {"未建库": True, "组": [], "总数": 0}
    组 = 指纹.找重复(表)
    return {"组": [{"保留": 保留, "重复": 重复} for 保留, 重复 in 组],
            "总数": sum(len(重复) for _, 重复 in 组)}


@app.post("/api/dedupe")
def 清理重复(_=Depends(校验密码)):
    表 = 指纹.读指纹()
    组 = 指纹.找重复(表)
    移动 = 0
    for 保留, 重复们 in 组:
        for 名 in 重复们:
            类别 = "照片" if os.path.splitext(名)[1].lower() in 指纹.图片扩展名 else "视频"
            if 指纹.移到回收站(名, 类别):
                移动 += 1
    指纹.更新指纹(打印=lambda *_: None)
    return {"ok": True, "移动": 移动, "回收目录": 指纹.回收目录}


@app.get("/api/tasks")
def 任务(_=Depends(校验密码)):
    return {"运行中": 任务状态["运行中"], "日志": 任务状态["日志"],
            "待处理": 任务状态["待处理"]}


@app.post("/api/rebuild")
def 手动重建(_=Depends(校验密码)):
    触发处理()
    return {"ok": True, "运行中": 任务状态["运行中"]}


# ---------------- 向量检索索引 ----------------
@app.post("/api/reindex")
def 重建检索索引(_=Depends(校验密码)):
    触发索引重建()
    return {"ok": True, "运行中": 任务状态["运行中"]}


@app.get("/api/reindex/status")
def 检索索引状态(_=Depends(校验密码)):
    块们, 矩阵 = 检索.读索引()
    分类 = {}
    for 块 in 块们:
        分类[块.get("类型", "其他")] = 分类.get(块.get("类型", "其他"), 0) + 1
    return {"段数": len(块们), "分类": 分类,
            "已建索引": bool(块们),
            "警告": 读索引警告(),
            "运行中": 任务状态["运行中"], "日志": 任务状态["日志"]}


# ---------------- 文档去重（按内容，不看文件名） ----------------
@app.get("/api/docs/duplicates")
def 文档查重(_=Depends(校验密码)):
    表 = 文档.更新指纹(打印=lambda *_: None)
    组 = 文档.找重复(表)
    return {"组": [{"保留": k, "重复": v, "依据": y, "说明": s} for k, v, y, s in 组],
            "总数": sum(len(v) for _, v, _, _ in 组)}


@app.post("/api/docs/dedupe")
def 文档清理(_=Depends(校验密码)):
    表 = 文档.更新指纹(打印=lambda *_: None)
    组 = 文档.找重复(表)
    移动 = 0
    for 保留, 重复们, _, _ in 组:
        for 名 in 重复们:
            if 文档.移到回收站(名):
                移动 += 1
    文档.更新指纹(打印=lambda *_: None)
    return {"ok": True, "移动": 移动, "回收目录": 文档.回收目录}


# ---------------- 照片文字识别（OCR） ----------------
def 触发OCR():
    if 任务状态["运行中"]:
        任务状态["待处理"] = True
        return
    import sys

    def 跑():
        任务状态["运行中"] = True
        try:
            跑脚本([sys.executable, os.path.join(config.脚本目录, "照片OCR.py")])
            跑脚本([sys.executable, os.path.join(config.脚本目录, "知识检索.py")])
        finally:
            任务状态["运行中"] = False

    threading.Thread(target=跑).start()


@app.post("/api/ocr")
def 开始OCR(_=Depends(校验密码)):
    触发OCR()
    return {"ok": True, "运行中": 任务状态["运行中"]}


@app.get("/api/ocr/status")
def OCR状态(_=Depends(校验密码)):
    已处理, 含字 = 0, 0
    try:
        with open(os.path.join(config.索引目录, "照片文字.json"), encoding="utf-8") as f:
            数据 = json.load(f)
        已处理 = len(数据)
        含字 = sum(1 for v in 数据.values() if v)
    except Exception:
        pass
    return {"已处理": 已处理, "含文字": 含字,
            "运行中": 任务状态["运行中"], "日志": 任务状态["日志"]}


# ---------------- 照片搜索与显示 ----------------
缩略图目录 = os.path.join(config.索引目录, "thumbs")
os.makedirs(缩略图目录, exist_ok=True)


def 读识图缓存():
    路 = os.path.join(config.索引目录, "识图缓存.json")
    if not os.path.exists(路):
        return {}
    try:
        with open(路, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


@app.get("/api/photos")
def 搜照片(q: str, _=Depends(校验密码)):
    """按AI描述关键词匹配照片，返回文件名列表（按相关度排序）"""
    缓存 = 读识图缓存()
    if not q.strip() or not 缓存:
        return []
    词 = [w for w in re.split(r"[\s，。！？、,.!?的了吗呢啊哦]+", q) if len(w) >= 2]
    if not 词:
        词 = [q.strip()]
    结果 = []
    for 路径, 描述 in 缓存.items():
        名 = os.path.basename(路径)
        if not os.path.isfile(os.path.join(config.照片目录, 名)):
            continue
        得分 = sum(描述.count(w) for w in 词)
        if 得分 > 0:
            结果.append({"名": 名, "描述": 描述, "得分": 得分})
    结果.sort(key=lambda x: -x["得分"])
    return 结果[:60]


@app.get("/api/thumb/{name}")
def 缩略图(name: str, _=Depends(校验密码)):
    名 = os.path.basename(name)
    缓存图 = os.path.join(缩略图目录, 名 + ".jpg")
    if not os.path.exists(缓存图):
        from PIL import Image
        原图 = os.path.join(config.照片目录, 名)
        if not os.path.isfile(原图):
            raise HTTPException(404, "照片不存在")
        try:
            with Image.open(原图) as img:
                img = img.convert("RGB")
                if max(img.size) > 480:
                    r = 480 / max(img.size)
                    img = img.resize((int(img.width * r), int(img.height * r)))
                img.save(缓存图, "JPEG", quality=78)
        except Exception:
            raise HTTPException(400, "无法处理该图片格式")
    return FileResponse(缓存图, media_type="image/jpeg")


@app.get("/api/photo/{name}")
def 原图(name: str, _=Depends(校验密码)):
    名 = os.path.basename(name)
    路径 = os.path.join(config.照片目录, 名)
    if not os.path.isfile(路径):
        raise HTTPException(404, "照片不存在")
    return FileResponse(路径)


# ---------------- 视频封面（首帧） ----------------
def 找ffmpeg():
    import shutil
    c = shutil.which("ffmpeg")
    if c:
        return c
    for p in [os.path.join(config.脚本目录, "ffmpeg.exe"),
              os.path.join(config.服务器目录, "ffmpeg.exe")]:
        if os.path.isfile(p):
            return p
    return None


@app.get("/api/vthumb/{name}")
def 视频封面(name: str, _=Depends(校验密码)):
    名 = os.path.basename(name)
    缓存图 = os.path.join(缩略图目录, 名 + ".jpg")
    if not os.path.exists(缓存图):
        ffmpeg = 找ffmpeg()
        视频路径 = os.path.join(config.视频目录, 名)
        if not ffmpeg or not os.path.isfile(视频路径):
            raise HTTPException(404, "无封面")
        try:
            尝试们 = [["-ss", "1"], []]  # 先试第1秒，失败（超短视频）取首帧
            for 附加 in 尝试们:
                r = subprocess.run([ffmpeg, *附加, "-i", 视频路径,
                                    "-frames:v", "1", "-vf", "scale=480:-2",
                                    "-q:v", "5", 缓存图],
                                   capture_output=True, timeout=120)
                if r.returncode == 0 and os.path.exists(缓存图):
                    break
            else:
                raise RuntimeError("ffmpeg failed")
        except Exception:
            raise HTTPException(404, "封面生成失败")
    return FileResponse(缓存图, media_type="image/jpeg")


# ---------------- 书籍 PDF ----------------
PDF缓存目录 = os.path.join(config.索引目录, "pdf文本缓存")
os.makedirs(PDF缓存目录, exist_ok=True)


def 提取PDF文本(路径):
    """按页提取PDF文字，每页带【第N页】标记；结果按文件缓存。需要 pypdf 库。"""
    import hashlib
    指纹 = hashlib.md5(("v2" + 路径 + str(os.path.getmtime(路径))).encode()).hexdigest()
    缓存路 = os.path.join(PDF缓存目录, 指纹 + ".txt")
    if os.path.exists(缓存路):
        with open(缓存路, encoding="utf-8") as f:
            return f.read()
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""
    try:
        读 = PdfReader(路径)
        文本们 = []
        for i, 页 in enumerate(读.pages):
            if i >= 300:  # 上限300页，防止超大文件
                break
            页文 = (页.extract_text() or "").strip()
            if 页文:
                文本们.append(f"【第{i+1}页】\n{页文}")
        文 = "\n\n".join(文本们).strip()
    except Exception:
        文 = ""
    with open(缓存路, "w", encoding="utf-8") as f:
        f.write(文)
    return 文


@app.get("/api/doc/{name}")
def 打开书籍(name: str, _=Depends(校验密码)):
    名 = os.path.basename(name)
    import urllib.parse
    for 目录 in [config.书籍目录, os.path.join(config.根目录, "01-书籍扫描", "待OCR")]:
        路 = os.path.join(目录, 名)
        if os.path.isfile(路):
            return FileResponse(
                路, media_type="application/pdf",
                headers={"Content-Disposition":
                         "inline; filename*=UTF-8''" + urllib.parse.quote(名)})
    raise HTTPException(404, "文件不存在")


# ---------------- AI 查询 ----------------
#  重要：影像总目录.md 里已经嵌入了 AI识图描述、手工描述、视频描述汇总的内容，
#        所以这三份文件不能再单独喂给 AI，否则会重复占满上下文，
#        把《视频描述.txt》（手机上新写的描述都在这里）挤出去。
索引里只喂这两个 = {"影像总目录.md", "视频描述.txt"}

# 每一类资料单独给预算，保证哪一类都不会被完全挤掉
预算们 = [
    ("影像资料", None, {".md", ".txt"}, 80000),      # 索引目录，但只取上面那两个文件
    ("书籍论文", "书籍", {".md", ".txt", ".pdf"}, 40000),
    ("笔记素材", "笔记", {".md", ".txt"}, 20000),
    ("笔记素材", "素材", {".md", ".txt"}, 20000),
]
总上限 = 120000


def 收集资料():
    """按类别预算收集资料作为提问上下文"""
    片段 = []

    def 已用():
        return sum(len(x) for x in 片段)

    def 加入文件(路径, 名):
        小名 = 名.lower()
        if 小名.endswith(".pdf"):
            文 = 提取PDF文本(路径)
        else:
            try:
                with open(路径, encoding="utf-8", errors="ignore") as f:
                    文 = f.read()
            except Exception:
                return
        if not 文.strip():
            return
        if 已用() + len(文) > 总上限:
            return
        片段.append(f"===== 资料文件：{名} =====\n{文}")

    def 加入目录(目录, 后缀, 预算, 只这些=None):
        起点 = 已用()
        for 根, _, 文件们 in os.walk(目录):
            # 跳过内部缓存目录
            if os.path.basename(根) in ("pdf文本缓存", "thumbs"):
                continue
            for 名 in sorted(文件们):
                if 只这些 is not None and 名 not in 只这些:
                    continue
                if os.path.splitext(名)[1].lower() not in 后缀:
                    continue
                if 已用() - 起点 >= 预算:
                    return
                加入文件(os.path.join(根, 名), 名)

    加入目录(config.索引目录, {".md", ".txt"}, 80000, 只这些=索引里只喂这两个)
    加入目录(config.书籍目录, {".md", ".txt", ".pdf"}, 40000)
    加入目录(config.笔记目录, {".md", ".txt"}, 20000)
    加入目录(config.素材目录, {".md", ".txt"}, 20000)
    return "\n\n".join(片段)


def 读索引警告():
    try:
        with open(os.path.join(config.索引目录, "索引警告.json"), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def 索引过期():
    """资料文件的修改时间晚于索引建立时间 → 说明有新资料还没进索引"""
    try:
        索引时间 = os.path.getmtime(检索.块文件)
    except Exception:
        return False
    后缀 = {".pdf", ".md", ".txt"}
    最新 = 0
    for 目录 in (config.书籍目录, config.笔记目录, config.素材目录):
        for 根, _, 文件们 in os.walk(目录):
            if os.path.basename(根) in ("pdf文本缓存", "thumbs"):
                continue
            for f in 文件们:
                if os.path.splitext(f)[1].lower() in 后缀:
                    try:
                        最新 = max(最新, os.path.getmtime(os.path.join(根, f)))
                    except Exception:
                        pass
    return 最新 > 索引时间 + 10


@app.get("/api/search")
def 查询(q: str, _=Depends(校验密码)):
    if not config.DeepSeekKey:
        return {"回答": "未配置 DeepSeek Key。请在 server\\deepseek_key.txt 里写入你的 API Key 后重启服务。", "照片": [], "视频": [], "书籍": [], "引用": []}

    # 优先用向量检索（RAG）：只把最相关片段交给 AI，跨语言、可无限扩充资料
    # 检索索引还没建立时，自动退回"全量塞入"的老方式
    资料 = ""
    用了检索 = False
    try:
        资料 = 检索.检索上下文(q, 条数=20)
        用了检索 = bool(资料.strip())
    except Exception:
        资料 = ""
    if not 用了检索:
        资料 = 收集资料()
    if not 资料.strip():
        return {"回答": "知识库里还没有可检索的文字资料。", "照片": [], "视频": [], "书籍": [], "引用": []}

    资料说明 = ("以下是根据你的问题，从知识库中检索出的最相关片段（可能不完整）。"
              if 用了检索 else "以下是知识库中的全部资料。")
    请求体 = json.dumps({
        "model": "deepseek-chat",
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content":
             "你是个人知识库助手。只根据提供的资料回答，每条结论注明出自哪个文件；"
             "资料里没有的内容就直说没有，不要编造。用中文回答（原文是外语时也用中文说明，必要时附原文）。\n\n"
             + 资料说明 + "\n\n"
             "资料中的影像片段格式为：【照片】文件名.jpg（拍摄地点：…）：画面描述，"
             "或【视频】文件名.mp4：描述。请从中挑出与问题确实相关的照片和视频，各最多 60 个，宁准勿滥。\n\n"
             "书籍片段形如\"资料片段：文件名.pdf 第N页\"。凡是引用书籍内容，必须在回答里注明"
             "出自哪本书第几页。同时把最关键的出处（最多 10 条）列在 refs 字段，"
             "方便用户直接跳转到该页阅读原文。\n\n"
             "严格输出JSON：{\"answer\": \"回答文字（引用书籍处注明页码）\", "
             "\"photos\": [\"照片1.jpg\"], \"videos\": [\"视频1.mp4\"], "
             "\"books\": [\"相关资料.pdf\"], "
             "\"refs\": [{\"file\": \"资料.pdf\", \"page\": 12, \"why\": \"一句话说明这段与问题的关系\"}]}"},
            {"role": "user", "content": f"资料如下：\n\n{资料}\n\n我的问题：{q}"},
        ],
    }).encode("utf-8")
    请求 = urllib.request.Request(
        "https://api.deepseek.com/chat/completions", data=请求体,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {config.DeepSeekKey}"})
    try:
        with urllib.request.urlopen(请求, timeout=180) as r:
            数据 = json.loads(r.read().decode("utf-8"))
        内容 = 数据["choices"][0]["message"]["content"]
        结果 = json.loads(内容)
        回答 = 结果.get("answer", 内容)
        照片名们 = [os.path.basename(str(p)) for p in 结果.get("photos", [])][:60]
        视频名们 = [os.path.basename(str(v)) for v in 结果.get("videos", [])][:60]
        书籍名们 = [os.path.basename(str(b)) for b in 结果.get("books", [])][:20]
        引用们 = []
        for r in 结果.get("refs", [])[:10]:
            try:
                引用们.append({"名": os.path.basename(str(r.get("file", ""))),
                               "页": int(r.get("page", 0)),
                               "说明": str(r.get("why", ""))[:100]})
            except Exception:
                continue
    except Exception as e:
        return {"回答": f"查询失败：{e}", "照片": [], "视频": [], "书籍": [], "引用": []}

    # 有资料比索引新 → 提示用户重建，避免"明明上传了却搜不到"
    if 用了检索 and 索引过期():
        回答 = ("⚠ 提示：检测到有资料是在建立检索索引之后才加入的（可能搜不到），"
                "请到「上传」页点一下「建立/更新检索索引」。\n\n") + 回答
    # 有资料提取不出文字 → 提示可能是扫描版
    警告们 = 读索引警告()
    if 警告们:
        名字们 = "、".join(w.get("文件", "?") for w in 警告们[:5])
        回答 = (f"⚠ 提示：以下资料没能加入检索（很可能是扫描版 PDF，需要 OCR）：{名字们}\n\n") + 回答
    # 附上描述用于标注，并过滤不存在的文件
    缓存 = 读识图缓存()
    照片 = [{"名": n, "描述": next((d for p, d in 缓存.items() if os.path.basename(p) == n), "")}
            for n in 照片名们
            if os.path.isfile(os.path.join(config.照片目录, n))]
    视频描述们 = 读描述()
    视频 = [{"名": n, "描述": 视频描述们.get(n, "")}
            for n in 视频名们
            if os.path.isfile(os.path.join(config.视频目录, n))]
    书籍 = []
    for n in 书籍名们:
        for 目录 in [config.书籍目录, config.笔记目录, config.素材目录, config.索引目录]:
            if os.path.isfile(os.path.join(目录, n)):
                书籍.append({"名": n})
                break
    引用 = [r for r in 引用们
            if any(os.path.isfile(os.path.join(d, r["名"]))
                   for d in [config.书籍目录, config.笔记目录, config.素材目录, config.索引目录])]
    return {"回答": 回答, "照片": 照片, "视频": 视频, "书籍": 书籍, "引用": 引用}


# ---------------- 前端页面 ----------------
@app.get("/")
def 首页():
    return FileResponse(os.path.join(config.服务器目录, "static", "index.html"))


app.mount("/static", StaticFiles(directory=os.path.join(config.服务器目录, "static")), name="static")
