# -*- coding: utf-8 -*-
"""
构建线上展厅的图片资源与数据文件。

输入（三个只读源目录）：
  A. ComfyUI 输出目录（MyFavourite_HighQuality）
  B. 拼贴画成品目录
  C. 纯背景目录

  这三处路径带本机信息，不写进代码，放在 build/sources.local.json
  （已 gitignore，不入库；模板见 build/sources.example.json）。

输出（三档，按「谁在什么时候付带宽」切）：
  assets/img/<collection>/t_NNN.jpg   展墙缩略图：低清，滚动加载，字节越小越好
  assets/img/<collection>/l_NNN.jpg   灯箱档：原分辨率 JPEG（q80），点开才拉
  assets/img/<collection>/f_NNN.webp  原图档：原始分辨率 + 原始编码，只有按
                                      「显示原图」或下载才请求
  assets/data/*.js                     window.__DATA_* 数据

AI 标识（《人工智能生成合成内容标识办法》2025-09-01 施行，配套 GB 45438-2025）：
  显式 —— 在画面**下方外接一条黑条**写「AI 辅助生成」，不压在画面上，
          做进 l_ 与 f_ 两档（展墙缩略图上放字不可读，故不加）；
  隐式 —— EXIF 写 属性信息 / 服务提供者编码 / 内容编号。
  只有真正含扩散模型输出的系列加条（见 AI_LABEL）；
  「千禧迷思」「东方风背景图」是程序化合成，加了就是错误标注。
"""
import os, re, json, glob, sys, time, shutil
from PIL import Image

try:
    from opencc import OpenCC
    _t2s = OpenCC("t2s").convert
except Exception:                     # 没装 opencc 时退回原文
    def _t2s(x):
        return x

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")
IMG = os.path.join(ASSETS, "img")
DATA = os.path.join(ASSETS, "data")

SRC_COMFY = SRC_COLLAGE = SRC_BG = None


def _load_sources():
    """从 build/sources.local.json 读取三个源目录（该文件不入库）。"""
    global SRC_COMFY, SRC_COLLAGE, SRC_BG
    cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "sources.local.json")
    if not os.path.exists(cfg_path):
        raise SystemExit(
            f"缺少源目录配置：{cfg_path}\n"
            "请复制 build/sources.example.json 为 sources.local.json，"
            "填入本机上三个只读源目录的路径。")
    with open(cfg_path, encoding="utf-8") as fh:
        cfg = json.load(fh)
    SRC_COMFY, SRC_COLLAGE, SRC_BG = cfg["comfy"], cfg["collage"], cfg["bg"]
    for name, path in (("comfy", SRC_COMFY), ("collage", SRC_COLLAGE), ("bg", SRC_BG)):
        if not os.path.isdir(path):
            raise SystemExit(f"源目录不存在：{name} -> {path}")

# ---- 三档参数 -------------------------------------------------------------
# 缩略图：展墙一格 CSS 宽约 290–400px（style.css 的 minmax(290px,1fr)），
# 手机上单列约 335 CSS 像素、dpr2 要 670 —— 所以取 640 长边，够到 dpr≈1.9。
THUMB_EXT, THUMB_MAX, THUMB_Q, THUMB_SUB = "jpg", 640, 70, 1
# 灯箱档：默认原分辨率（1.0）。想要「80% 分辨率」而不是「80% 质量」，
# 把 VIEW_SCALE 改成 0.8 即可，其余代码不用动。
VIEW_EXT, VIEW_SCALE, VIEW_Q, VIEW_SUB = "jpg", 1.0, 80, 1
# 原图档：原始分辨率 + 原始编码（WebP），只在按「原图」或下载时请求
FULL_EXT = "webp"
FULL_MIN_EDGE = 1600               # 画面长边 ≤ 这个数就不写 f_，灯箱档即原图
# 灯箱档长边上限。探针实测：8K 源按原分辨率出 q80 JPEG 是 4.7–5.3 MB，
# 5M 带宽下单张要 8–9 秒；限到 3000 后约 0.8–1.0 MB（1:1 细看会自动先取原图）。
# 想严格按「原分辨率」出灯箱档，把这里改回 0。
VIEW_CAP_EDGE = 3000
TIER_REVISION = 3                  # 出图逻辑变了（不只是参数）就手动 +1，强制整批重出

# ---- AI 标识 --------------------------------------------------------------
# 显式标识（黑条）**不烧进图片**：构建端出干净像素，条由前端画在画面下方
# （app.js 的 markEl + style.css 的 .lb__mark），下载时由 canvas 现场合成。
# 于是：同一份文件既是作品原样；改字号字重配色只动 CSS，不用重编码 266 张图。
EMBED_META = True                  # 隐式标识（EXIF）只写元数据，不动像素，保留
AI_LABEL = {
    "comfy": "AI 辅助生成 · 扩散模型",
    "collage": None,               # 程序化合成，不含扩散模型输出
    "bg": None,                    # 同上：Pillow / NumPy 渲染管线
}
PROVIDER_CODE = "TEWHAC-GALLERY"   # 隐式标识里的服务方编码；不含任何本机信息

for d in (IMG, DATA):
    os.makedirs(d, exist_ok=True)


# 每个集合的「序号 → 源文件名」映射。文件一增一删，序号会整体平移，
# 只按 mtime 判断就会把旧图当新图复用 —— 张冠李戴且不报错。
# 参数指纹按档分组：只改缩略图尺寸时不该重烧 8K 的原图档（一次全量 10+ 分钟）。
# 见 apply_param_revision —— _FORCE[tier] 为真时那一档整批重出。
_META_KEYS = ("AI_LABEL", "PROVIDER_CODE", "EMBED_META", "TIER_REVISION")
PARAM_GROUPS = {
    "thumb": ("THUMB_EXT", "THUMB_MAX", "THUMB_Q", "THUMB_SUB"),
    "view":  ("VIEW_EXT", "VIEW_SCALE", "VIEW_Q", "VIEW_SUB", "VIEW_CAP_EDGE") + _META_KEYS,
    "full":  ("FULL_EXT", "FULL_MIN_EDGE") + _META_KEYS,
}
_FORCE = {"thumb": False, "view": False, "full": False}
_MANIFEST = {}      # 磁盘上那份（只读，用于校验）
_PENDING = {}       # 本轮新写进去的（保存时才合并）


def _manifest(coll):
    """返回 {序号: 文件名}；None 表示这个集合还没有映射表（首次启用，退回 mtime 判断）。"""
    if coll not in _MANIFEST:
        p = os.path.join(IMG, coll, "manifest.json")
        if os.path.exists(p):
            try:
                _MANIFEST[coll] = json.load(open(p, encoding="utf-8"))
            except Exception:
                _MANIFEST[coll] = {}
        else:
            _MANIFEST[coll] = None
    return _MANIFEST[coll]


def _mapped(coll, idx, src):
    m = _manifest(coll)
    if m is None:
        return True
    return m.get(f"{idx:03d}") == os.path.basename(src)


def _mark(coll, idx, src):
    _PENDING.setdefault(coll, {})[f"{idx:03d}"] = os.path.basename(src)


def save_manifests():
    for coll, add in _PENDING.items():
        m = dict(_manifest(coll) or {})
        m.update(add)
        os.makedirs(os.path.join(IMG, coll), exist_ok=True)
        with open(os.path.join(IMG, coll, "manifest.json"), "w", encoding="utf-8") as fh:
            json.dump(m, fh, ensure_ascii=False, indent=0, sort_keys=True)


def prune_collection(coll, count):
    """删掉序号超出现有条数的产物（源文件被删后留下的孤儿），
    以及旧的 {t,l}_*.webp —— 三档换格式以后，旧格式没人引用，留着只会让
    「这张到底是哪档出的」再也答不出来。"""
    gone = 0
    for path in glob.glob(os.path.join(IMG, coll, "*_*")):
        name = os.path.basename(path)
        m = re.match(r"^([tlf])_(\d{3})\.(webp|jpg|jpeg|png)$", name)
        if not m:
            continue
        if m.group(1) in ("t", "l") and m.group(3) == "webp":
            os.remove(path)          # 旧格式的缩略图/快图：迁移后一律删
            gone += 1
            continue
        if int(m.group(2)) > count:
            os.remove(path)
            gone += 1
    # 映射表里超出条数的键也一并清掉
    for tbl in (_MANIFEST.get(coll), _PENDING.get(coll)):
        if tbl:
            for k in [k for k in tbl if int(k) > count]:
                tbl.pop(k)
    return gone


def _done(path, src, tier="full"):
    """产物算不算"已经生成好了"：存在、非空、不比源文件旧，且**这一档**的参数没变。
    只看存在性会被一次中断的写入永久钉死 —— 0 字节的 webp 既跳过重建，
    又能在 Pages 上返回 200，坏图就这么悄悄上线了。
    参数指纹那条更要紧：改了档位质量或黑条文案，文件名和 mtime 都不变，
    没有它就会出现「代码改了、产物没改」——最难查的一种失败。"""
    if _FORCE.get(tier):
        return False
    return (os.path.exists(path) and os.path.getsize(path) > 0
            and os.path.getmtime(path) > os.path.getmtime(src))


# 只列档位与黑条的参数。绝不把 SRC_* 写进指纹：params.json 会随站点发布，
# 而源目录路径是「本站不含任何本地路径」这条约定里唯一还可能漏出去的东西。
# 字体路径也不列（换机器就变），逻辑本身变了就手动 +1 TIER_REVISION。
def _params_fingerprint():
    """{档: {参数名: 值}}。绝不把 SRC_* 写进来：params.json 随站点发布，
    而源目录路径是「本站不含任何本地路径」这条约定里唯一还可能漏出去的东西。
    字体路径也不列（换机器就变）；出图逻辑本身变了就手动 +1 TIER_REVISION。"""
    return {tier: {k: globals()[k] for k in keys} for tier, keys in PARAM_GROUPS.items()}


def apply_param_revision():
    """逐档比对参数指纹：哪一档变了就只重出那一档。

    比较一律走 JSON 序列化后的字符串 —— 指纹里有元组（BAR_BG/BAR_FG），
    json 存成数组、读回来是列表，直接比 dict 会永远不相等，
    结果是每次构建都整批重编码（实测多烧 5 分钟且没人发现）。"""
    p = os.path.join(IMG, "params.json")
    old = None
    if os.path.exists(p):
        try:
            old = json.load(open(p, encoding="utf-8"))
        except Exception:
            old = None
    cur = _params_fingerprint()
    norm = lambda o: json.dumps(o, sort_keys=True, ensure_ascii=False)
    for tier, params in cur.items():
        same = bool(old) and norm(old.get(tier)) == norm(params)
        _FORCE[tier] = not same
        if _FORCE[tier]:
            print(f"  [{tier}] 参数与上次构建不同 → 这一档整批重出")
    if not old:
        print("  首次记录参数指纹")
    return dict(_FORCE)


def save_params():
    with open(os.path.join(IMG, "params.json"), "w", encoding="utf-8") as fh:
        json.dump(_params_fingerprint(), fh, ensure_ascii=False, indent=1, sort_keys=True)


def _view_size(w, h):
    """灯箱档出图尺寸：默认原分辨率，VIEW_CAP_EDGE 可设长边上限。"""
    cap = int(max(w, h) * VIEW_SCALE)
    if VIEW_CAP_EDGE:
        cap = min(cap, VIEW_CAP_EDGE)
    scale = min(1.0, cap / max(w, h))
    return max(1, round(w * scale)), max(1, round(h * scale))


# ---------------------------------------------------------------- AI 标识
def ai_exif(label, no):
    """隐式标识：属性信息 / 服务提供者编码 / 内容编号。绝不含本机路径。"""
    ex = Image.Exif()
    ex[0x010E] = (f"生成合成内容属性：{label}；服务提供者编码：{PROVIDER_CODE}；"
                  f"内容编号：{no}")
    ex[0x0131] = f"{PROVIDER_CODE} build_site"
    return ex.tobytes()


# ---------------------------------------------------------------- image utils
def _rel(path):
    return os.path.relpath(path, ROOT).replace(os.sep, "/")


def _save_jpeg(im, path, q, sub, exif_bytes=None):
    kw = dict(quality=q, optimize=True, progressive=True, subsampling=sub)
    if exif_bytes:
        kw["exif"] = exif_bytes
    im.save(path, "JPEG", **kw)


def _save_by_ext(im, path, q, sub, exif_bytes=None):
    """按文件后缀选编码器 —— 否则 THUMB_EXT/VIEW_EXT 一改就变成
    「把 JPEG 字节写成 .webp 文件名」，浏览器照样能猜着显示，但 CDN 与
    Content-Type 全错，是最难查的那类静默错配。"""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".jpg", ".jpeg"):
        _save_jpeg(im, path, q, sub, exif_bytes)
    elif ext == ".webp":
        _save_webp(im, path, min(95, q + 6), 5, exif_bytes)
    else:
        raise SystemExit(f"不支持的档位格式：{ext}（{os.path.basename(path)}）")


def _save_webp(im, path, q, method, exif_bytes=None):
    kw = dict(quality=q, method=method)
    if exif_bytes:
        kw["exif"] = exif_bytes
    im.save(path, "WEBP", **kw)


def build_previews(src, coll, idx, force=False):
    """缩略图档 + 灯箱档。返回 (画面w, 画面h, rel_t, rel_l, 灯箱档w, 灯箱档h)。

    出的是干净像素：AI 黑条由前端画在画面下方，下载时才用 canvas 合成。"""
    out_dir = os.path.join(IMG, coll)
    os.makedirs(out_dir, exist_ok=True)
    label = AI_LABEL.get(coll)
    no = f"{coll[0]}{idx:03d}"
    t_path = os.path.join(out_dir, f"t_{idx:03d}.{THUMB_EXT}")
    l_path = os.path.join(out_dir, f"l_{idx:03d}.{VIEW_EXT}")
    rel_t, rel_l = _rel(t_path), _rel(l_path)

    if not force and _mapped(coll, idx, src) and _done(t_path, src, "thumb") \
            and _done(l_path, src, "view"):
        with Image.open(src) as im:
            w, h = im.size
        # 灯箱档尺寸从**产物本身**读，不按常数回推：常数回推会在
        # 「产物是旧参数出的」时谎报，数据就对不上文件了。
        with Image.open(l_path) as lim:
            return w, h, rel_t, rel_l, lim.size[0], lim.size[1]

    with Image.open(src) as im:
        im = im.convert("RGB")
        w, h = im.size
        # 灯箱档：原分辨率（VIEW_SCALE=1.0）JPEG；超大的源可选设长边上限
        view = im.copy()
        vw, vh = _view_size(w, h)
        if (vw, vh) != (w, h):
            view.thumbnail((vw, vh), Image.LANCZOS)
        _save_by_ext(view, l_path, VIEW_Q, VIEW_SUB,
                     ai_exif(label, no) if (label and EMBED_META) else None)
        thumb = im.copy()
        thumb.thumbnail((THUMB_MAX, THUMB_MAX), Image.LANCZOS)
        _save_by_ext(thumb, t_path, THUMB_Q, THUMB_SUB)
    _mark(coll, idx, src)
    return w, h, rel_t, rel_l, vw, vh


def build_full(src, coll, idx, force=False):
    """原图档：原始分辨率 + 原始编码，干净像素。返回 (rel, w, h)。"""
    out_dir = os.path.join(IMG, coll)
    os.makedirs(out_dir, exist_ok=True)
    label = AI_LABEL.get(coll)
    no = f"{coll[0]}{idx:03d}"
    f_path = os.path.join(out_dir, f"f_{idx:03d}.{FULL_EXT}")
    rel = _rel(f_path)
    with Image.open(src) as im:
        im = im.convert("RGB")
        w, h = im.size
        if not force and _mapped(coll, idx, src) and _done(f_path, src, "full"):
            return rel, w, h
        big = max(w, h) > 3000
        _save_webp(im, f_path, (88 if big else 90), (4 if big else 5),
                   ai_exif(label, no) if (label and EMBED_META) else None)
    _mark(coll, idx, src)
    return rel, w, h


def build_full_copy(src, coll, idx):
    """源本身已经是压好的网络格式且就是目标分辨率：按字节复制。
    重新编码就是第二代损失 —— 8000×8000 的卡面再 q95 压一次尤其亏。

    复制前先探一眼元数据：相机与工具链的 EXIF/XMP 里常带本机路径，
    而「本站不含任何本地路径」是硬约定。这类文件一旦出现在源目录，
    宁可当场报错（只报文件名，不报路径）也不要悄悄把它发出去。"""
    out_dir = os.path.join(IMG, coll)
    os.makedirs(out_dir, exist_ok=True)
    ext = os.path.splitext(src)[1].lstrip(".").lower()
    f_path = os.path.join(out_dir, f"f_{idx:03d}.{ext}")
    rel = _rel(f_path)
    with Image.open(src) as im:
        w, h = im.size
        if im.getexif() or im.info.get("xmp"):
            raise SystemExit(f"源文件带 EXIF/XMP 元数据，可能含本机路径，先清掉再发布："
                             f"{os.path.basename(src)}")
    if not _mapped(coll, idx, src) or not _done(f_path, src, "full") \
            or os.path.getsize(f_path) != os.path.getsize(src):
        shutil.copyfile(src, f_path)
    return rel, w, h, 0


# ------------------------------------------------------- A. ComfyUI 元数据
def parse_overview():
    """从 概述.md 的逐图表格里取出：版本 / 场景 / seed / 步数 / p50 / edgeN / 机位。"""
    path = os.path.join(SRC_COMFY, "概述.md")
    rows = {}
    if not os.path.exists(path):
        return rows
    for line in open(path, encoding="utf-8"):
        if not line.startswith("| `"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 8:
            continue
        f = cells[0].strip("`")
        rows[f] = {
            "version": cells[1], "scene": cells[2], "seed": cells[3],
            "steps": cells[4], "p50": cells[5], "edge": cells[6],
            "shot": cells[7],
        }
    return rows


def comfy_prompt_meta(path):
    try:
        with Image.open(path) as im:
            raw = im.info.get("prompt")
    except Exception:
        raw = None
    if not raw:
        return {}
    try:
        g = json.loads(raw)
    except Exception:
        return {}
    out = {}
    for node in g.values():
        ct = node.get("class_type")
        inp = node.get("inputs", {})
        if ct == "TextEncodeQwenImage21":
            out["prompt"] = (inp.get("prompt") or "").strip()
            out["negative"] = (inp.get("negative_prompt") or "").strip()
        elif ct == "RandomNoise":
            out["seed"] = inp.get("noise_seed")
        elif ct == "CFGGuider":
            out["cfg"] = inp.get("cfg")
        elif ct == "ManualSigmas":
            sig = str(inp.get("sigmas", ""))
            n = len([s for s in sig.split(",") if s.strip()])
            out["steps"] = max(n - 1, 0)
        elif ct == "UNETLoader":
            out["model"] = inp.get("unet_name")
        elif ct == "CLIPLoader":
            out["clip"] = inp.get("clip_name")
        elif ct == "VAELoader":
            out["vae"] = inp.get("vae_name")
        elif ct == "KSamplerSelect":
            out["sampler"] = inp.get("sampler_name")
    return out


VERSION_META = {
    "v1–v6 早期": ("第 1–6 轮", "半写实 CG 路线", "否决", "semi-realistic 走成了 3D 动画电影，不是手绘。"),
    "v11 中期": ("第 11 轮", "确立「细线厚涂」画法", "转向", "构图改用物理机位描述；材质词（oil impasto）实测无效。"),
    "材质实验": ("第 11 轮附", "试材质词", "无效", "加与不加出图完全一致，之后不再浪费时间。"),
    "v12 平涂": ("第 12 轮", "平涂矢量路线", "否决", "纯色块 + 硬边 + 零纹理，用户评价「恶心感」。"),
    "v13": ("第 13 轮", "14 步后期调色流水线", "弯路", "fit_levels / 颗粒 / 色散全是在补提示词的债。"),
    "v14 后期版": ("第 14 轮", "后期调色加码", "弯路", "效果能出，但色散与边缘抖动本身在制造瑕疵。"),
    "v15 直出定稿": ("第 15 轮", "推翻后期，把影调写进提示词", "突破", "high key exposure + 点名哪里必须亮，raw 影调第一次落进参考区间。"),
    "v16 逆光": ("第 16 轮", "试整体逆光", "失败", "模型把整张图一起压暗，暗部被砍平。"),
    "v16b 逆光": ("第 16b 轮", "逆光加码", "失败", "edge 0.128 → 0.066，细节掉一半。"),
    "v17 逆光修正": ("第 17 轮", "逆光修正", "部分", "亮度回来一些，仍不如直出。"),
    "v18 光源实验": ("第 18 轮", "光源 + 衰减 + 硬投影", "部分", "灯珠出来了，但红泛光丢失、整体偏暗。"),
    "v20 采样实验": ("第 20 轮", "采样参数实验", "突破", "16 步是甜点（edgeN 翻倍）；cfg 2.0 会把布料拉平。"),
    "v22 角色实验": ("第 22 轮", "中间调锚点", "收敛", "加「中间调三十灰」防止暗部吃掉整张图。"),
    "v23 定稿": ("第 23 轮", "当前定稿配方", "定稿", "中间调锚点 + 黑裙不黑 + 填满画面，六场景一次成立。"),
    "v24 曝光修正": ("第 24 轮", "曝光修正", "微调", "同配方下压曝光，验证稳定性。"),
    "v26 参考图试跑": ("第 26 轮", "启用参考图通道", "试验", "用三视图当参考，身份锁住但细节掉一档。"),
    "v27 参考图": ("第 27 轮", "参考图锁身份", "取舍", "发夹 / 领口缎带 / 发长锁死，12 步换取一致性。"),
    "v28 自由创作": ("第 28 轮", "用定稿配方自由创作", "产出", "10 个新场景，单张 355s，稳定产出。"),
    "v29 写实支线": ("第 29 轮", "无人称大场景（鲸 / 道口 / 拉面摊）", "偏离",
                 "构图与光都成立，但画风跑成了摄影：没有细线、没有笔触。留 3 张作对照。"),
    "v31 对照": ("第 31 轮", "在 v29 的场景里加一个远处的小人物", "仍偏离",
               "人物不占画幅就带不动画风 —— 画风不在场景里。"),
    "v33 黄雨衣系列": ("第 33 轮", "换自己的角色：黄雨衣少女 × 八个世界", "关键结论",
                  "画风回来了。anime 画风由人物承载，不由风格词承载 —— 这是整条谱系最贵的一条。"),
    "v34 百景": ("第 34 轮", "二十个互不相同的世界，人物各不相同", "扩展",
               "同一套配方在四个轴（题材 / 时间 / 色调 / 机位）上同时拉开，验证画风能否脱离固定角色。"),
    "v35 三十景": ("第 35 轮", "三十个没碰过的题材", "扩展",
                "沿用 v34 三条定稿规则（人物占画幅 ≥ 1/4、写明动漫五官、脸不被遮住），题材转向江户 / 昭和 / 近未来 / 工业 / 极地。"),
    "v36 幻想三十": ("第 36 轮", "三十个现实里不存在的题材", "转向",
                 "这一轮放开「必须露脸」：可以有动物、有遮脸的角色、也可以纯景。风格头换成 gouache + storybook，并显式写「这是画」。"),
}
VERSION_ORDER = list(VERSION_META.keys())
# 同一輪的散落標籤併入同一組
VERSION_ALIAS = {"v2 早期": "v1–v6 早期", "v4 早期": "v1–v6 早期", "v6 早期": "v1–v6 早期",
                 "v1 早期": "v1–v6 早期"}


def prettify_scene(scene):
    if not scene or scene == "—":
        return None
    m = re.match(r"^([A-Za-z]?\d+)[_ ](.+)$", scene)
    if m:
        return f"{m.group(1).upper()} · {m.group(2).replace('_', ' ')}"
    return scene.replace("_", " ")


# ---------------------------------------------------------- 主题归类
# 主题展示顺序：巨鲸钉在最前，其余按「组内最新版本」倒序（新的在前）
THEME_PINNED = ["whale"]


def ver_num(label):
    """从版本标签里取轮次：'v34 百景' → 34，'v1–v6 早期' → 1，'未归档' → 0。"""
    m = re.search(r"v(\d+)", label or "")
    return int(m.group(1)) if m else 0

THEMES = {
    "stage": ("舞台", "聚光灯、音箱堆与湿地板"),
    "theater": ("剧场", "金箔拱门与红丝绒座椅"),
    "topdown": ("俯视", "垂直向下的机位"),
    "bedroom": ("卧室", "四柱床与窗光"),
    "crowd": ("人群", "护栏、购物袋与背后的观众"),
    "door": ("门隙", "从门缝里看出去"),
    "ruins": ("废墟", "荒草、断柱、鸟居，与林间长满蕨类的旧机甲"),
    "field": ("麦田", "齐腰的麦穗与天光"),
    "garden": ("花园", "盛放的玫瑰枝"),
    "stairs": ("阶梯", "扶手与柱头"),
    "rooftop": ("屋顶", "铁丝网与城市天际线"),
    "mirror": ("镜厅", "镀金镜框与反射"),
    "library": ("图书馆", "书堆、窗与尘埃"),
    "konbini": ("便利店", "货架与冷白灯"),
    "rain": ("雨夜", "伞沿与雨滴"),
    "vending": ("自动贩卖机", "夜里的冷光橱窗"),
    "aquarium": ("水族馆", "弧形亚克力与鱼群"),
    "train": ("列车", "车厢纵深与吊环"),
    "billboard": ("广告牌", "钢架与撕破的海报"),
    "shrine": ("神社", "石灯笼与鸟居"),
    "books": ("书页", "翻动的纸页"),
    "phonebooth": ("电话亭", "磨砂玻璃与金属框"),
    "piano": ("钢琴", "湿沙上的琴盖与琴键"),
    "corridor": ("走廊", "一点透视的长廊"),
    "crossing": ("道口", "铁轨、警示机与压顶的雷雨云；也有把人放到很远的一张"),
    "ramen": ("拉面店", "暖帘、柜台蒸汽与街对面的夜"),
    "whale": ("巨鲸", "淹没街道上的鲸与落日"),
    "atrium": ("中庭", "环形楼层仰视的天井光"),
    "cat": ("猫", "窗台、蕾丝窗帘与怀里的黑猫"),
    "lighthouse": ("灯塔", "雪地栅栏、极光与塔顶的光"),
    "desert": ("沙漠", "沙丘上的商队与公路尽头的加油站"),
    "ice": ("冰原", "冰壁、暴风雪与冰湖上的落日"),
    "greenhouse": ("温室", "维多利亚玻璃棚与清晨的雾气"),
    "festival": ("祭典", "纸灯笼、摊位蒸汽与人潮"),
    "workshop": ("车间", "车床、工具板与机油"),
    "overpass": ("天桥", "雨里的钢梁与车灯"),
    "sakura": ("樱花", "河堤两岸的花枝隧道"),
    "star": ("星空", "云海之上的银河与望远镜"),
    "edo": ("江户", "雨夜的町屋与雪里的花街"),
    "showa": ("昭和室内", "咖啡馆、理发店、洗衣房的老灯与镜子"),
    "cinema": ("放映室", "光束穿过灰尘打到幕布上"),
    "saltflat": ("盐湖", "天与地互相照镜子的那种平"),
    "balloon": ("热气球", "清晨的球囊与吊篮"),
    "cablecar": ("缆车", "雾里的钢索与车厢"),
    "mushroom": ("蘑菇林", "巨型菌盖下的光斑"),
    "port": ("港口", "集装箱、吊机与夜里的钠灯"),
    "myth": ("幻想巨物", "鹿神、巨龟、凤凰、龙骨与雾中巨像"),
    "skyrealm": ("天空奇筑", "浮空岛、天空之城、沙漏城市与巫师塔"),
    "costumed": ("奇装人物", "全盔骑士、狐面巫女、黄铜潜水盔、白兔绅士、蝶翼少女"),
    "forest": ("秘境森林", "发光水母、菌丝、镜中森林与树洞"),
    "other": ("其他", "未标注场景的试验稿"),
}

# 场景码 → 主题的显式归并：画面主体是"荒废之物"时，算废墟而不是单开一类。
SCENE_THEME = {
    "mecha": "ruins",     # 林间长满蕨类的旧机甲 —— 与断柱鸟居同属荒废
    "figure": "crossing",  # v31 是道口机位、人放远 —— 同一处景，不另开一类
    # v34 百景：语义相近的场景码并进同一个主题，别为一张图单开一类
    "caravan": "desert", "gasstation": "desert",
    "climber": "ice", "icelake": "ice",
    "bookshop": "library", "stacks": "library",
    "scarecrow": "field", "trainwindow": "train",
    "snowkonbini": "konbini", "ruinpiano": "piano",
    "greenhouse": "greenhouse", "festival": "festival",
    "workshop": "workshop", "overpass": "overpass",
    "sakura": "sakura", "stargazer": "star",
    # v35 三十景
    "edo": "edo", "hanamachi": "edo",
    "kissaten": "showa", "barber": "showa", "laundry": "showa",
    "chapel": "ruins", "junkyard": "ruins", "ferris": "ruins",
    "observatory": "star", "rarebooks": "library", "elevator": "library",
    "projection": "cinema", "saltflat": "saltflat", "busstop": "rain",
    "balloon": "balloon", "cablecar": "cablecar", "mushroom": "mushroom",
    "port": "port", "polar": "ice", "subway": "train", "station": "star",
    "ricefield": "field", "paddymirror": "field", "rainhouse": "greenhouse",
    "onsen": "rain", "rooftoppool": "rooftop", "cabin": "bedroom",
    "lava": "ice", "yakitori": "ramen", "icecave": "ice",
    # v36 幻想三十：按这一批自己的三类分（纯景 / 生物 / 遮脸人物），不逐张开新类
    "islands": "skyrealm", "skycity": "skyrealm", "hourglass": "skyrealm",
    "teapot": "skyrealm", "papercranes": "skyrealm", "owltower": "skyrealm",
    "deergod": "myth", "turtle": "myth", "phoenix": "myth",
    "dragonbones": "myth", "statue": "myth",
    "knight": "costumed", "foxmask": "costumed", "diverhelmet": "costumed",
    "alien": "costumed", "rabbit": "costumed", "butterfly": "costumed",
    "jellyfish": "forest", "mycelium": "forest", "mirrorforest": "forest",
    "treehouse": "forest",
    "whalesky": "whale", "skywhale": "whale", "glasswhale": "whale",
    "cloudlibrary": "library", "catlibrary": "library",
    "crystal": "desert", "stardust": "star", "aurorabones": "ice",
}

# v34 的场景码 → 中文短名（取自 风格复刻/scripts/run_v34.py 的 JOBS 表）
SCENE_CN = {
    "rider": "雨夜高架上的骑手", "caravan": "正午沙漠里的商队", "climber": "暴风雪里的攀登者",
    "greenhouse": "清晨的玻璃温室", "diver": "深潜者与光柱", "bookshop": "旧书店的午后",
    "boxer": "拳台顶灯下的拳手", "festival": "夏日祭的灯笼下", "icelake": "冰湖上的日落",
    "workshop": "车间里的机械师", "overpass": "天桥上的雨", "scarecrow": "麦田里的稻草人",
    "kite": "天台上的风筝", "trainwindow": "车厢窗边的旅人", "stacks": "书库高架上的少女",
    "snowkonbini": "雪夜的便利店", "gasstation": "沙漠公路的加油站",
    "sakura": "樱花隧道里的自行车", "ruinpiano": "废墟里的钢琴师", "stargazer": "星空下的观测者",
    "figure": "道口远影",
    # v35 三十景
    "edo": "江户雨夜的町屋", "kissaten": "昭和咖啡馆的午后", "station": "空间站观景舱",
    "balloon": "清晨的热气球", "chapel": "教堂废墟里的光", "subway": "淹水的地铁站",
    "ricefield": "稻田上的雷雨", "barber": "老理发店的镜子", "icecave": "蓝冰洞里的探险者",
    "yakitori": "夜市烧烤摊", "laundry": "深夜洗衣房", "cablecar": "雾中的缆车",
    "junkyard": "废车场里的野花", "observatory": "天文台圆顶内", "rainhouse": "暴雨中的玻璃花房",
    "projection": "放映室的光束", "onsen": "雪夜的露天温泉", "rooftoppool": "天台泳池的午后",
    "ferris": "废弃游乐园的摩天轮", "rarebooks": "特藏室的善本", "saltflat": "盐湖上的镜面",
    "cabin": "深林小屋的窗", "busstop": "雨中的公交站", "lava": "熔岩原上的观测站",
    "hanamachi": "花街的雪", "mushroom": "巨型蘑菇森林", "port": "港口的集装箱夜",
    "elevator": "图书馆的铁栅电梯", "polar": "极地科考站", "paddymirror": "银河下的水田",
    # v36 幻想三十
    "islands": "浮空岛与瀑布", "whalesky": "鲸群飞过巨月", "deergod": "发光鹿神",
    "crystal": "沙漠里的水晶巨树", "cloudlibrary": "云海上的图书馆塔", "jellyfish": "发光水母森林",
    "owltower": "猫头鹰巫师塔", "turtle": "驮城的巨龟", "stardust": "星尘瀑布",
    "skywhale": "机械鲸与飞艇港", "glasswhale": "花海里的玻璃鲸", "phoenix": "火山口的凤凰",
    "dragonbones": "冰封的巨龙骸骨", "mycelium": "菌丝森林", "skycity": "天空之城的阶梯",
    "hourglass": "沙漏里的城市", "knight": "全盔骑士的荒原", "foxmask": "狐面巫女",
    "diverhelmet": "黄铜潜水盔的探险家", "alien": "异星沙漠的宇航员", "rabbit": "白兔绅士的茶会",
    "catlibrary": "猫的图书馆", "butterfly": "蝶翼少女", "papercranes": "纸鹤飞过城市",
    "aurorabones": "极光下的巨鲸骨", "mirrorforest": "镜中森林", "treehouse": "树洞里的房间",
    "teapot": "悬浮的茶壶群岛", "boat": "银河中的小船", "statue": "雾中的巨神像",
}

# 无场景码时按提示词关键词兜底（顺序即优先级：越靠前越是"画面主体"）
PROMPT_THEME = [
    (r"vending machine", "vending"),
    (r"inside the tank|curved acrylic|aquarium", "aquarium"),
    (r"\bcarriage\b|hanging straps", "train"),
    (r"billboard|torn poster", "billboard"),
    (r"phone booth", "phonebooth"),
    (r"grand piano|piano keys|\bpiano\b", "piano"),
    (r"one point perspective|corridor|doorframe", "corridor"),
    (r"stone lantern|torii", "shrine"),
    (r"konbini|convenience store|products are huge", "konbini"),
    (r"railway crossing|the tracks run straight|crossing barrier|warning light", "crossing"),
    (r"noren|ramen shop|steaming bowls", "ramen"),
    (r"\bwhale\b", "whale"),
    (r"circular atrium|rings of balconies", "atrium"),
    (r"\blighthouse\b", "lighthouse"),
    (r"\bmecha\b|rusty robot", "ruins"),
    (r"a black cat|in her arms, a cat", "cat"),
    (r"umbrella|raindrops|\brain\b|wet street", "rain"),
    (r"narrow gap|door edge|chipped dark wood door", "door"),
    (r"library|bookshelf|stack of (leather )?books|leather books|heavy desk", "library"),
    (r"gilded mirror|mirror frame|in the mirror", "mirror"),
    (r"banister|newel|foot of the stairs", "stairs"),
    (r"chain link fence|rooftop", "rooftop"),
    (r"rose branch|rose garden|garden", "garden"),
    (r"wheat|stalks", "field"),
    (r"tall grass|ruins", "ruins"),
    (r"proscenium|auditorium|velvet seat|theater", "theater"),
    (r"\bstage\b|microphone|amp stack", "stage"),
    (r"four poster bed|bedroom", "bedroom"),
    (r"crowd|barrier|shopping bag", "crowd"),
]


CN_NUM = "零一二三四五六七八九十"


def _cn_num(n):
    return CN_NUM[n] if n <= 10 else str(n)


def scene_key(scene):
    """场景码归一化：去掉 _W2 / _v2 这类机位后缀，'statue_W2' → 'statue'。"""
    return re.sub(r"_w\d+$", "", (scene or "").strip().lower())


def make_title(scene, stem, theme_name):
    """中文场景名 > 场景码 + 主题 > 只有单词场景就只用主题 > 文件名前缀。"""
    key = scene_key(scene)
    if key in SCENE_CN:
        return SCENE_CN[key]
    if scene and scene != "—":
        m = re.match(r"^([A-Za-z]{0,2}\d+)", scene)
        if m:
            return f"{theme_name} · {m.group(1).upper()}"
        return theme_name
    if len(stem) <= 6 and "_" not in stem:
        return f"{theme_name} · {stem}"
    return stem


def classify_theme(scene, prompt):
    """先看场景码；没有码时，先拿提示词开头那句「机位 + 前景近物」判断，
    判不出来再全文兜底 —— 全文里的比喻（mirror sharp / mirrors the lamps）会骗人。"""
    if scene and scene != "—":
        tail = scene_key(scene)
        if tail in SCENE_THEME:
            return SCENE_THEME[tail]
        if tail in THEMES:
            return tail
        if scene.lower() in THEMES:
            return scene.lower()
    text = (prompt or "").lower()
    head = text[:300]
    for pat, key in PROMPT_THEME:
        if re.search(pat, head):
            return key
    for pat, key in PROMPT_THEME:
        if re.search(pat, text):
            return key
    return "other"


def build_comfy():
    label = AI_LABEL.get("comfy")
    rows = parse_overview()
    files = sorted(f for f in os.listdir(SRC_COMFY) if f.lower().endswith(".png"))
    items = []
    for i, f in enumerate(files, 1):
        src = os.path.join(SRC_COMFY, f)
        w, h, t, l, lw, lh = build_previews(src, "comfy", i)
        fp, fw, fh = build_full(src, "comfy", i)
        meta = comfy_prompt_meta(src)
        row = rows.get(f, {})
        stem = re.sub(r"(_\d+)+_?\.png$", "", f)
        scene = row.get("scene") or ""
        title = stem
        items.append({
            "id": f"c{i:03d}", "file": f, "title": title, "stem": stem,
            "thumb": t, "large": l, "full": fp, "w": w, "h": h, "fw": fw, "fh": fh,
            "ai": label, "lw": lw, "lh": lh,
            "version": row.get("version", "未归档"),
            "scene": scene, "seed": meta.get("seed") or row.get("seed"),
            "steps": meta.get("steps") or row.get("steps"),
            "cfg": meta.get("cfg"), "model": meta.get("model"),
            "p50": row.get("p50"), "edge": row.get("edge"),
            "shot": (row.get("shot") or "").rstrip(" ."),
            "prompt": meta.get("prompt", ""),
        })
        print(f"  comfy {i:02d}/{len(files)} {f}", flush=True)

    for it in items:
        it["group"] = VERSION_ALIAS.get(it["version"], it["version"])
        it["theme"] = classify_theme(it["scene"], it["prompt"])
        it["themeName"] = THEMES[it["theme"]][0]
        it["title"] = make_title(it["scene"], it["stem"], it["themeName"])

    # 同一场景出多张时（caravan ×2、climber ×2），标题补「之二 / 之三」
    seen = {}
    for it in items:
        t = it["title"]
        n = seen.get(t, 0)
        seen[t] = n + 1
        if n:
            it["title"] = f"{t} · 之{_cn_num(n + 1)}"

    print(f"  清理孤儿产物 {prune_collection('comfy', len(files))} 个")

    groups = []
    for v in VERSION_ORDER:
        sel = [it for it in items if it["group"] == v]
        if not sel:
            continue
        rnd, what, verdict, note = VERSION_META[v]
        groups.append({"name": v, "round": rnd, "what": what,
                       "verdict": verdict, "note": note, "items": sel})
    rest = [it for it in items if it["group"] not in VERSION_META]
    if rest:
        groups.append({"name": "未归档", "round": "—", "what": "早期杂项", "verdict": "—",
                       "note": "早期试验残稿。", "items": rest})

    # 按主题分组（张数多的在前，"其他" 置末）
    counts = {}
    for it in items:
        counts[it["theme"]] = counts.get(it["theme"], 0) + 1
    order = sorted([k for k in counts if k != "other"], key=lambda k: -counts[k])
    if counts.get("other"):
        order.append("other")
    theme_groups = []
    for k in order:
        name, desc = THEMES[k]
        sel = [it for it in items if it["theme"] == k]
        vers = []
        for it in sel:
            if it["group"] not in vers:
                vers.append(it["group"])
        theme_groups.append({"key": k, "name": name, "desc": desc,
                             "versions": vers, "items": sel})

    # 巨鲸钉第一，其余按组内最新版本倒序；同版本保持原来的张数排序（sort 稳定）
    theme_groups.sort(key=lambda g: (0 if g["key"] in THEME_PINNED else 1,
                                     -max(ver_num(it["group"]) for it in g["items"])))

    return {"items": items, "groups": groups, "themes": theme_groups}


# ------------------------------------------------------------ B. 拼贴画
COLLAGE_FRAMES = [
    ("final_01.png", "8k_01.png", "千.禧.迷.思", "土星", "這一天算什麼。", "儀式該向誰領取",
     "張望 / 遲疑 / 未定", "再想想。", "未", "0.35"),
    ("final_02.png", "8k_02.png", "電.波", "抛物面天线", "該向誰交班。", "典禮尚未排定日期",
     "呼叫 / 回音 / 延後", "再等等吧。", "延", "0.47"),
    ("final_03.png", "8k_03.png", "日.蝕", "黑日", "算交接嗎。", "黑日過去誰來宣布",
     "長夜 / 觀禮 / 歸來", "天亮了再說。", "候", "0.34"),
    ("final_04.png", "8k_04.png", "月.相", "殘月", "月有陰晴 人無屆次。", "誰為圓滿那一刻設過儀程",
     "觀止 / 遠望 / 排期", "下次再說。", "望", "0.89"),
    ("final_05.png", "8k_05.png", "星.語", "無錨點", "算不算一個結束。", "想紀念該從哪一頁起",
     "起念 / 翻頁 / 恍惚", "記哪一頁。", "念", "0.36"),
    ("final_06.png", "8k_06.png", "流.星.雨", "小行星", "此處也曾經是節點。", "鳥飛過的天空可有刻度",
     "遺跡 / 潮聲 / 提名", "慢慢想。", "尋", "0.43"),
]


def build_collage():
    label = AI_LABEL.get("collage")
    items = []
    for i, (f, f8, title, anchor, band, vert, emo, bottom, seal, score) in enumerate(COLLAGE_FRAMES, 1):
        src = os.path.join(SRC_COLLAGE, f)
        src8 = os.path.join(SRC_COLLAGE, f8)
        # 有 8K 源就从 8K 一次出三档：以前是「小图出预览 + 8K 补大图」两条路，
        # 现在灯箱档本身就是原分辨率，分两头只会让同系列出现两种清晰度。
        psrc = src8 if os.path.exists(src8) else src
        w, h, t, l, lw, lh = build_previews(psrc, "collage", i)
        if max(w, h) <= FULL_MIN_EDGE:
            fp, fw, fh = l, w, h      # 原图就是灯箱档，不再写一份没人引用的 f_
        else:
            fp, fw, fh = build_full(psrc, "collage", i)
        items.append({
            "id": f"k{i:02d}", "file": f, "title": title, "stem": f"第 {i:02d} 帧",
            "thumb": t, "large": l, "full": fp, "w": w, "h": h, "fw": fw, "fh": fh,
            "ai": label, "lw": lw, "lh": lh,
            "anchor": anchor, "band": band, "vertical": vert,
            "emotion": emo, "bottom": bottom, "seal": seal, "score": score,
            "big": f"{fw} × {fh}",
        })
        print(f"  collage {i}/6 {f}", flush=True)

    # 流程复刻图（层序说明）
    extra = []
    proc = os.path.join(SRC_COLLAGE, "流程复刻.png")
    if os.path.exists(proc):
        w, h, t, l, lw, lh = build_previews(proc, "collage", 90)
        if max(w, h) <= FULL_MIN_EDGE:
            fp, fw, fh = l, w, h
        else:
            fp, fw, fh = build_full(proc, "collage", 90)
        extra.append({"id": "k90", "file": "流程复刻.png", "title": "層序復刻",
                      "stem": "渲染顺序对照", "thumb": t, "large": l, "full": fp, "w": w, "h": h,
                      "fw": fw, "fh": fh, "ai": label, "lw": lw, "lh": lh})
    return {"items": items, "extra": extra}


# ------------------------------------------------------------ C. 纯背景
BG_SERIES = [
    {
        "key": "bg20c", "dir": "二十幻想原画", "name": "二十幻想原画",
        "sub": "二十种美学方向 · 原作向", "generator": "bg20c.py",
        "note": "色轴取自 54 张真实封面调色板（主色相重铸成暗→亮一族），素材换用 th06–th13 游戏线。",
        "overview": "二十幻想原画总览.png", "prefix": "b",
    },
    {
        "key": "bg20b", "dir": "二十新景", "name": "二十新景",
        "sub": "梦幻系配方 v2 · 一景一策", "generator": "bg20b.py",
        "note": "沿用被认可的配方语法：素材混底 + pastel 色轴 + 光源 + 花瓣光斑 + 暗角颗粒，每景只换素材组合、色轴、构图母题。",
        "overview": "二十新景总览.png", "prefix": "b",
    },
    {
        "key": "covers", "dir": "原封面背景54张", "name": "原封面背景 54 张",
        "sub": "同色轴仿制 · 不借用原图像素", "generator": "gen_backgrounds.py",
        "note": "为特征库里每张原封面生成一张同色轴纯拼接背景；共享同一条 kmeans 色轴与统计亮度校准，构图与素材随机。",
        "overview": None, "prefix": "b",
    },
    {
        "key": "layout", "dir": "新排布六类", "name": "新排布六类",
        "sub": "8000 × 8000 原生渲染", "generator": "birthday_card*.py",
        "note": "六种贺图排布的纯背景版，直接按 8K 画布出图；1080p 版为同一构图的降采样。",
        "overview": "新排布背景总览.png", "prefix": "b", "hd": "新排布六类_1080p",
        "cards": "新排布贺图",   # 同名成品卡（带标题），排在纯背景前面
    },
    {
        "key": "birthday", "dir": "", "name": "明快氛围",
        "sub": "同配方 · 十种色调 + 两版基础", "generator": "birthday_variants.py --notitle",
        "note": "同一套妖精大战争配方管线，只换色轴、素材配比、花串色与标题色，去掉标题即为纯背景。",
        "overview": "生日贺图背景10张总览.png", "prefix": "b",
    },
]


# 页面上的展示顺序：靠前的三个系列先看
SERIES_ORDER = ["layout", "birthday", "bg20b", "bg20c", "covers"]


def build_backgrounds():
    label = AI_LABEL.get("bg")
    series = []
    idx = 0
    for s in BG_SERIES:
        files = []
        if s["dir"]:
            d = os.path.join(SRC_BG, s["dir"])
            files = sorted(f for f in os.listdir(d) if f.lower().endswith(".png"))
            files = [f for f in files if f != s["overview"]]
        else:
            files = sorted(f for f in os.listdir(SRC_BG)
                           if f.startswith("birthday_") and f.endswith(".png")
                           and f != s["overview"])
        items = []
        ov = None
        if s["overview"]:
            op = os.path.join(SRC_BG, s["dir"], s["overview"]) if s["dir"] else os.path.join(SRC_BG, s["overview"])
            if os.path.exists(op):
                idx += 1
                w, h, t, l, lw, lh = build_previews(op, "bg", idx)
                if max(w, h) <= FULL_MIN_EDGE:
                    fp, fw, fh = l, w, h   # 灯箱档即原图，不再写一份没人引用的 f_
                else:
                    fp, fw, fh = build_full(op, "bg", idx)
                ov = {"id": f"g{idx:03d}", "title": "系列总览", "thumb": t, "large": l,
                      "full": fp, "w": w, "h": h, "fw": fw, "fh": fh,
                      "ai": label, "lw": lw, "lh": lh, "file": s["overview"]}
        # 成品卡（带标题）排在同组纯背景前面。两边文件名同名，靠 kind 区分。
        if s.get("cards"):
            cdir = os.path.join(SRC_BG, s["cards"])
            cfiles = sorted(f for f in os.listdir(cdir)
                            if f.lower().endswith((".jpg", ".jpeg"))
                            and "_compressed" in f.lower()
                            and "总览" not in f)
            for f in cfiles:
                idx += 1
                p = os.path.join(cdir, f)
                w, h, t, l, lw, lh = build_previews(p, "bg", idx)
                fp, fw, fh = build_full_copy(p, "bg", idx)   # 他压好的 JPG：复制且不落元数据
                card = {"id": f"g{idx:03d}", "file": f,
                        "title": _t2s(re.sub(r"_compressed$", "", os.path.splitext(f)[0])),
                        "thumb": t, "large": l, "full": fp,
                        "w": w, "h": h, "fw": fw, "fh": fh,
                        "ai": label, "lw": lw, "lh": lh,
                        "kind": "成品卡面", "badge": "成品"}
                if max(w, h) > FULL_MIN_EDGE:
                    card["big"] = f"{w} × {h}"
                items.append(card)
                print(f"  bg {s['key']} 卡面 {len(items)}/{len(cfiles)} {f}", flush=True)
        for f in files:
            idx += 1
            p = os.path.join(SRC_BG, s["dir"], f) if s["dir"] else os.path.join(SRC_BG, f)
            w, h, t, l, lw, lh = build_previews(p, "bg", idx)
            title = re.sub(r"\.png$", "", f)
            title = title.replace("birthday_", "").replace("_背景", "")
            title = _t2s(title)
            if max(w, h) <= FULL_MIN_EDGE:
                fp, fw, fh = l, w, h    # 原图本身就不大，灯箱档即原图
            else:
                fp, fw, fh = build_full(p, "bg", idx)
            item = {"id": f"g{idx:03d}", "file": f, "title": title,
                    "thumb": t, "large": l, "full": fp, "w": w, "h": h, "fw": fw, "fh": fh,
                    "ai": label, "lw": lw, "lh": lh}
            if s.get("cards"):
                item["kind"] = "纯背景"     # 与前面的成品卡对照
            # 8K 原生渲染的：灯箱档已经是原分辨率，只需把画幅告诉读者
            if s.get("hd") and max(w, h) > FULL_MIN_EDGE:
                item["big"] = f"{w} × {h}"
            items.append(item)
            print(f"  bg {s['key']} {len(items)}/{len(files)} {f}", flush=True)
        series.append({"key": s["key"], "name": s["name"], "sub": s["sub"],
                       "generator": s["generator"], "note": s["note"],
                       "overview": ov, "items": items})
    series.sort(key=lambda x: SERIES_ORDER.index(x["key"]) if x["key"] in SERIES_ORDER else 99)
    return {"series": series}


# ---------------------------------------------------------------- emit
def emit(name, obj):
    p = os.path.join(DATA, f"{name}.js")
    js = "window.__DATA_" + name.upper() + " = " + json.dumps(obj, ensure_ascii=False) + ";\n"
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(js)
    print(f"  -> {p}  ({os.path.getsize(p)/1024:.0f} KB)")


def probe(n=2):
    """便宜探针：只重出几张的三档，量字节、量耗时，不整批重跑。
    搜到想要的参数再烧全量，比整批试错便宜得多。"""
    _load_sources()
    global IMG
    IMG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "probe")
    out = []

    def one(tag, src, coll, idx):
        t0 = time.time()
        w, h, rel_t, rel_l, vw, vh = build_previews(src, coll, idx, force=True)
        if max(w, h) <= FULL_MIN_EDGE:
            rel_f, fw, fh = rel_l, w, h
        else:
            rel_f, fw, fh = build_full(src, coll, idx, force=True)
        sz = lambda r: os.path.getsize(os.path.join(ROOT, r)) / 1024
        out.append((tag, f"{w}×{h}", sz(rel_t), sz(rel_l), sz(rel_f),
                    f"{vw}×{vh}", f"{fw}×{fh}", time.time() - t0))

    files = sorted(f for f in os.listdir(SRC_COMFY) if f.lower().endswith(".png"))
    for i, f in enumerate(files[:n], 1):
        one(f"comfy{i:02d}", os.path.join(SRC_COMFY, f), "comfy", i)
    c8 = os.path.join(SRC_COLLAGE, COLLAGE_FRAMES[0][1])
    if os.path.exists(c8):
        one("coll8k", c8, "collage", 1)
    lay = os.path.join(SRC_BG, "新排布六类")
    if os.path.isdir(lay):
        big = sorted(glob.glob(os.path.join(lay, "*.png")))
        if big:
            one("bg8k", big[0], "bg", 1)

    print(f"\n{'档':9} {'画面':11} {'缩略KB':>8} {'灯箱KB':>8} {'原图KB':>8} {'灯箱出图':>12} {'原图出图':>12} {'秒':>6}")
    for tag, dim, t, l, fp, vd, fd, dt in out:
        print(f"{tag:9} {dim:11} {t:8.0f} {l:8.0f} {fp:8.0f} {vd:>12} {fd:>12} {dt:6.1f}")


def purge_legacy():
    """三档换格式之后，旧的 {t,l}_*.webp 不再被任何数据引用。
    留着不会报错，但半年后没人答得出「这张是哪一批出的」—— 一次改格式的
    残留比一张坏图更难查。f_ 档仍是 webp，不在清理范围。"""
    gone = 0
    for coll in ("comfy", "collage", "bg"):
        for path in glob.glob(os.path.join(IMG, coll, "[tl]_*.webp")):
            os.remove(path)
            gone += 1
    return gone


def main():
    t0 = time.time()
    _load_sources()
    only = sys.argv[1] if len(sys.argv) > 1 else "all"
    if only != "probe":
        apply_param_revision()
    if only == "probe":
        probe(int(sys.argv[2]) if len(sys.argv) > 2 else 2)
        return
    if only in ("all", "comfy"):
        print("[A] ComfyUI 系列")
        emit("comfy", build_comfy())
    if only in ("all", "collage"):
        print("[B] 拼贴画")
        emit("collage", build_collage())
    if only in ("all", "bg"):
        print("[C] 纯背景")
        emit("bg", build_backgrounds())
    print(f"  清理旧格式产物 {purge_legacy()} 个")
    save_manifests()
    save_params()
    print(f"done in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
