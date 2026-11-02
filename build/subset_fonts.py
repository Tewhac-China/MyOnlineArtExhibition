# -*- coding: utf-8 -*-
"""把标题字體裁成子集，供 @font-face 的 url() 兜底使用。

页面优先用 local() 直接调系统已装字體（零下载）；若系统没装（手机基本都是这种情况），
就回落到这里裁出来的子集。

产出两份：kinghwa-sub.woff2（首选，体积约为 ttf 的四成）+ kinghwa-sub.ttf（老浏览器兜底）。
裁完会回读 cmap 逐字核对，缺一个字就报错退出 —— 缺字在装了系统字体的机器上根本看不出来，
只有在手机上才会逐字回退成别的字体，是典型的「本地正常、手机字体不对」。
"""
import os, re, glob, sys

from fontTools import subset
from fontTools.ttLib import TTFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets", "fonts")
os.makedirs(OUT, exist_ok=True)

WINDOWS_FONTS = os.path.join(
    os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts")

FONTS = [
    (os.path.join(WINDOWS_FONTS, "京華老宋体v3.0.ttf"), "kinghwa-sub"),
]

CJK = re.compile(u"[\u3000-\u303f\u3400-\u4dbf\u4e00-\u9fff\uff00-\uffef]")
ASCII_EXTRA = ("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
               "0123456789 .,:;!?/\\|-–—_()[]{}<>+=*&%#@'\"·×÷→←↑↓°′″"
               "áéíóúàèìòùâêîôûäëïöüñçÅÉÎÕÜ")


def collect():
    chars = set(ASCII_EXTRA)
    files = (glob.glob(os.path.join(ROOT, "*.html"))
             + glob.glob(os.path.join(ROOT, "assets", "data", "*.js"))
             + glob.glob(os.path.join(ROOT, "assets", "js", "*.js")))   # 界面文案在 app.js 里
    for p in files:
        with open(p, encoding="utf-8") as fh:
            txt = fh.read()
        chars |= set(CJK.findall(txt))
    # CSS 里 content:"" 写的文字也是会显示出来的字，漏扫就会静默回退成别的字体
    for p in glob.glob(os.path.join(ROOT, "assets", "css", "*.css")):
        with open(p, encoding="utf-8") as fh:
            for css_txt in re.findall(r'content:\s*("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')', fh.read()):
                chars |= set(CJK.findall(css_txt))
    chars.discard("\n")
    return "".join(sorted(chars))


def build(src, stem, text):
    font = TTFont(src, fontNumber=0)
    opts = subset.Options()
    opts.layout_features = ["kern"]   # 标题字体用不上复杂排版，砍掉 GSUB/GPOS 省 240KB
    opts.name_IDs = ["*"]
    opts.notdef_outline = True
    opts.recalc_bounds = True
    opts.drop_tables += ["DSIG"]
    sub = subset.Subsetter(options=opts)
    sub.populate(text=text)
    sub.subset(font)

    sizes = {}
    for flavor, ext in (("woff2", ".woff2"), (None, ".ttf")):
        font.flavor = flavor
        dst = os.path.join(OUT, stem + ext)
        font.save(dst)
        sizes[ext] = os.path.getsize(dst)
    return sizes


def verify(stem, text):
    """回读子集，逐字核对 —— 缺字必须在构建时就炸掉，不能留到手机上才发现"""
    f = TTFont(os.path.join(OUT, stem + ".woff2"))
    cmap = set()
    for t in f["cmap"].tables:
        cmap |= set(t.cmap.keys())
    missing = [c for c in text if ord(c) not in cmap]
    return missing


def main():
    text = collect()
    print(f"chars: {len(text)}")
    bad = 0
    for src, stem in FONTS:
        if not os.path.exists(src):
            print("  missing source:", src)
            bad += 1
            continue
        sizes = build(src, stem, text)
        missing = verify(stem, text)
        print(f"  {stem}.woff2 {sizes['.woff2']/1024:.0f} KB · "
              f"{stem}.ttf {sizes['.ttf']/1024:.0f} KB  "
              f"(源 {os.path.getsize(src)/1024/1024:.1f} MB)")
        if missing:
            bad += 1
            print(f"  !! 缺 {len(missing)} 字: {''.join(missing)[:200]}")
    if bad:
        sys.exit(1)
    print("coverage: 100%")


if __name__ == "__main__":
    main()
