# -*- coding: utf-8 -*-
"""把两套标题字體裁成子集，供 @font-face 的 url() 兜底使用。

页面优先用 local() 直接调系统已装字體（零下载）；若系统没装，
则回落到这里裁出来的子集（只含本站实际用到的字）。
"""
import os, re, glob

from fontTools import subset
from fontTools.ttLib import TTFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets", "fonts")
os.makedirs(OUT, exist_ok=True)

WINDOWS_FONTS = os.path.join(
    os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts")

FONTS = [
    (os.path.join(WINDOWS_FONTS, "京華老宋体v3.0.ttf"), "kinghwa-sub.ttf"),
]

CJK = re.compile(r"[\u3000-\u303f\u3400-\u4dbf\u4e00-\u9fff\uff00-\uffef]")
ASCII_EXTRA = ("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
               "0123456789 .,:;!?/\\|-–—_()[]{}<>+=*&%#@'\"·×÷→←↑↓°′″"
               "áéíóúàèìòùâêîôûäëïöüñçÅÉÎÕÜ")


def collect():
    chars = set(ASCII_EXTRA)
    files = glob.glob(os.path.join(ROOT, "*.html")) + glob.glob(os.path.join(ROOT, "assets", "data", "*.js"))
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


def build(src, dst, text):
    font = TTFont(src, fontNumber=0)
    opts = subset.Options()
    opts.layout_features = ["*"]
    opts.name_IDs = ["*"]
    opts.notdef_outline = True
    opts.recalc_bounds = True
    opts.drop_tables += ["DSIG"]
    sub = subset.Subsetter(options=opts)
    sub.populate(text=text)
    sub.subset(font)
    font.flavor = None
    font.save(dst)
    return os.path.getsize(dst)


def main():
    text = collect()
    print(f"chars: {len(text)}")
    for src, name in FONTS:
        if not os.path.exists(src):
            print("  missing:", src)
            continue
        dst = os.path.join(OUT, name)
        size = build(src, dst, text)
        print(f"  {name}: {size/1024:.0f} KB  ({os.path.getsize(src)/1024/1024:.1f} MB -> subset)")


if __name__ == "__main__":
    main()
