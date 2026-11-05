# -*- coding: utf-8 -*-
"""发布前自检：数据↔文件互查、本机信息泄露扫描、元数据清点。

只报文件名，不报路径 —— 报错信息本身也可能是要发布的内容的一部分。
用法：python build/pre_release.py
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMG = os.path.join(ROOT, "assets", "img")
DATA = os.path.join(ROOT, "assets", "data")
PUB_EXT = {".html", ".js", ".css", ".json", ".svg", ".txt", ".xml", ".webmanifest", ".py", ".md"}
# 本来就不入库的东西（gitignore），扫到了也不算泄露
SKIP = ("build/sources.local.json", "build/probe/", ".preview/")
LEAK_T = ["D:\\", "D:/", "E:\\", "E:/", "C:\\Users", "C:/Users",
          "PythonProjects", "11305", "TouhouPic", "ComfyUI-aki"]
# 元数据里会带文本的那几个通道；icc_profile 之类的二进制不参与比对
META_KEYS = ("xmp", "comment", "description", "author", "artist",
             "software", "copyright", "title", "exif")


def load_data():
    items = []
    for name in ("comfy.js", "collage.js", "bg.js"):
        p = os.path.join(DATA, name)
        raw = open(p, encoding="utf-8").read()
        d = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
        got = d.get("items")
        if got is None:
            got = [i for s in d.get("series", []) for i in s.get("items", [])]
        items += [(name, i) for i in got]
    return items


def refs(items):
    out = set()
    for _, it in items:
        for k in ("thumb", "large", "full"):
            v = it.get(k)
            if v:
                out.add(v.replace("assets/img/", ""))
    return out


def on_disk():
    out = {}
    for dirpath, _, files in os.walk(IMG):
        for f in files:
            if f.endswith((".jpg", ".webp", ".png")):
                p = os.path.join(dirpath, f)
                out[os.path.relpath(p, IMG).replace("\\", "/")] = os.path.getsize(p)
    return out


def meta_strings(path):
    """只解析元数据容器（EXIF / XMP / PNG tEXt / JPEG COM）。

    为什么不能对图片按字节 grep：压缩流是近似随机的比特，「D:\\」这种三字节序列
    纯属撞出来的 —— 上一版就这么报了 80 处假阳性。解析容器才是真命中。
    """
    from PIL import Image
    vals = []
    with Image.open(path) as im:
        try:
            ex = im.getexif()
            for tag, v in (ex.items() if ex else []):
                vals.append(f"{tag}={v}")
            for k in (0x8769, 0x8825):          # ExifIFD / GPSIFD
                try:
                    sub = ex.get_ifd(k) if ex else None
                except Exception:
                    sub = None
                for tag, v in (sub.items() if sub else []):
                    vals.append(f"{tag}={v}")
        except Exception:
            pass
        for k, v in (getattr(im, "text", None) or {}).items():
            vals.append(f"{k}={v}")
        for k, v in im.info.items():
            if k.lower() not in META_KEYS:
                continue
            if isinstance(v, (bytes, bytearray)):
                v = v.decode("utf-8", "ignore")
            if isinstance(v, str):
                vals.append(f"{k}={v[:2000]}")
    return vals


def main():
    problems = []
    items = load_data()
    want, have = refs(items), on_disk()

    missing = sorted(want - set(have))
    orphans = sorted(set(have) - want)
    if missing:
        problems.append(f"数据里引用但磁盘上没有：{len(missing)} 个，如 {missing[:3]}")
    if orphans:
        problems.append(f"磁盘上有但数据没引用（孤儿）：{len(orphans)} 个：{orphans}")
    print(f"=== 数据↔文件：引用 {len(want)} 条，磁盘 {len(have)} 个，缺 {len(missing)}，孤儿 {len(orphans)}")

    tiers = {}
    for rel, size in have.items():
        k = rel.split("/")[0] + "/" + rel.split("/")[1][0]
        t = tiers.setdefault(k, [0, 0])
        t[0] += 1
        t[1] += size
    for k in sorted(tiers):
        n, b = tiers[k]
        print(f"  {k}: {n} 张, {b / 1048576:.1f} MB")
    print(f"  合计: {len(have)} 张, {sum(have.values()) / 1048576:.1f} MB")

    for rel, size in sorted(have.items()):
        if size < 2048:
            problems.append(f"可疑小文件：{rel} ({size} B)")

    # 1) 发布文本：没有压缩，按字节命中就是真命中
    print("=== 本机信息扫描（发布文本）")
    n_text = hits = 0
    for dirpath, dirnames, files in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames
                       if d not in (".git", "node_modules", ".preview", "__pycache__", "img")]
        for f in files:
            p = os.path.join(dirpath, f)
            rel = os.path.relpath(p, ROOT).replace("\\", "/")
            if any(rel.startswith(s) for s in SKIP) or rel == os.path.relpath(__file__, ROOT).replace("\\", "/"):
                continue
            if os.path.splitext(f)[1].lower() not in PUB_EXT:
                continue
            n_text += 1
            blob = open(p, "rb").read()
            for pat in LEAK_T:
                if pat.encode() in blob:
                    hits += 1
                    problems.append(f"发布文本含本机信息：{rel} 命中 {pat!r}")
            m = re.search(rb"[A-Za-z]:[\\/](Users|Data|Download|ProgramData)", blob)
            if m:
                hits += 1
                problems.append(f"疑似绝对路径：{rel} → {m.group(0)!r}")
    print(f"  扫了 {n_text} 个发布文本，命中 {hits} 处")

    # 2) 图片元数据：容器解析 + 清点
    print("=== 图片元数据")
    ai = {r.replace("assets/img/", "").lstrip("/")
          for _, it in items for r in (it.get("large"), it.get("full"))
          if it.get("ai") and r}
    tier = lambda rel: os.path.basename(rel)[0]   # t/l/f 在文件名上，不在目录名上
    with_meta = 0
    for rel in sorted(have):
        vals = meta_strings(os.path.join(IMG, rel))
        text = "\n".join(vals)
        bad = [p for p in LEAK_T if p in text] or re.findall(r"[A-Za-z]:[\\/]\S{0,40}", text)
        if bad:
            problems.append(f"元数据里有本机信息：{rel} → {str(bad[:2])}")
        if vals:
            with_meta += 1
            if rel not in ai:
                problems.append(f"非 AI 作品却带元数据：{rel} → {text[:60]!r}")
        elif rel in ai and tier(rel) in ("l", "f"):
            problems.append(f"AI 作品缺隐式标识（无元数据）：{rel}")
    print(f"  带元数据 {with_meta} 个 / {len(have)}；AI 组应有 {len([r for r in ai if tier(r) in ("l", "f")])} 个")

    print("=== 结论")
    if problems:
        for p in problems[:20]:
            print("  !", p)
        print(f"  共 {len(problems)} 项")
        sys.exit(1)
    print("  通过：数据↔文件互查、发布文本、图片元数据三项都干净")


if __name__ == "__main__":
    main()
