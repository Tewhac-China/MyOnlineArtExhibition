# -*- coding: utf-8 -*-
"""真渲染自检：断言 + 截图，用一台「确实肯出图」的 chromium。

为什么不用 msedge：这台机上 Edge 的 CLI 从 bash 或 .bat 起都是 0.07 秒退、
--dump-dom / --screenshot 一律 0 字节（连 --version 都不吐字），所以
mobile_test.py / gui_test.py 那两个 harness 一直是假通过（NO OUTPUT）。
Playwright 的 chrome-headless-shell 在同机同参数下能给出真实视口（390×844
量到 rect=200），断言与截图都可用 —— 视觉判断必须靠它。

用法：
  python build/visual_check.py assert  comfyui.html            # 竖屏断言
  python build/visual_check.py shots   comfyui.html            # 出图到 .preview/shots/
  python build/visual_check.py shots   https://…/comfyui.html  # 线上同一套
可选 --w 390 --h 844 --dsf 2
"""
import argparse
import glob
import http.server
import os
import re
import shutil
import socketserver
import subprocess
import sys
import threading
import html as H

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PREVIEW = os.path.join(ROOT, ".preview")
PORT = 8799

# ---------------------------------------------------------------- 找浏览器
# 站点文件是要公开发布的，脚本里不写死任何用户目录
_LOCAL = os.environ.get("LOCALAPPDATA", "").replace("\\", "/")
CANDIDATES = [
    _LOCAL + "/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-win64/chrome-headless-shell.exe",
    _LOCAL + "/ms-playwright/chromium-*/chrome-win64/chrome.exe",
    "C:/Program Files/Google/Chrome/Application/chrome.exe",
    "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
]


def find_browser():
    """优先 headless shell（专为此用），版本目录取最新。"""
    for pat in CANDIDATES:
        hits = sorted(glob.glob(pat))
        if hits:
            return hits[-1]
    raise SystemExit("找不到可用的 chromium：检查 ms-playwright 缓存目录")


def works(binpath):
    """能 dump 出真实视口才算可用 —— Edge 也会返回 rc=0，但一个字都没有。"""
    probe = os.path.join(PREVIEW, "_probe.html")
    os.makedirs(PREVIEW, exist_ok=True)
    open(probe, "w", encoding="utf-8").write(
        '<!DOCTYPE html><meta charset=utf-8><body><pre id=T>x</pre>'
        '<script>document.getElementById("T").textContent="VW"+innerWidth</script>')
    out = run([binpath, "--headless", "--no-sandbox", "--disable-gpu",
                       "--disk-cache-size=1",
               "--user-data-dir=" + prof(),
               "--window-size=390,844", "--virtual-time-budget=2000", "--dump-dom",
               "file:///" + probe.replace("\\", "/")])
    return "VW390" in (out or "")


def prof():
    """独立 profile 目录：省得复用到上一轮的 HTTP 缓存（改完 CSS 量不到新样式）。"""
    d = os.path.join(PREVIEW, "_prof_%d" % os.getpid())
    os.makedirs(d, exist_ok=True)
    return d


def run(cmd, timeout=180):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        return (p.stdout or "") + (p.stderr or "")
    except Exception as e:
        return "LAUNCH FAIL " + str(e)


# ---------------------------------------------------------------- harness
BASE = """<!DOCTYPE html><html><head><meta charset="utf-8">
<style>html,body{margin:0;padding:0;background:#0b0b0c;overflow:hidden}
iframe{width:__W__px;height:__H__px;border:0;display:block}
#T{position:fixed;left:-9999px;top:0}</style></head>
<body><iframe id=f src="__SRC__"></iframe><pre id="T">_</pre>
<script>
var R=[];
function ok(n,c,d){R.push((c?"PASS":"FAIL")+"  "+n+(d?"  :: "+d:""))}
function wait(ms){return new Promise(function(r){setTimeout(r,ms)})}
function geo(w){
  var d=w.document, im=w.Site.LB.img, mk=w.Site.LB.markEl, st=w.Site.LB.stage;
  var tl=w.document.querySelector('.lb__tools');
  var a=im.getBoundingClientRect(), b=mk.getBoundingClientRect(), c=st.getBoundingClientRect();
  var t=tl?tl.getBoundingClientRect():null;
  return {imgBottom:Math.round(a.bottom),imgH:Math.round(a.height),imgW:Math.round(a.width),
          markTop:Math.round(b.top),markBottom:Math.round(b.bottom),markH:Math.round(b.height),
          markW:Math.round(b.width),stageBottom:Math.round(c.bottom),
          toolsTop:t?Math.round(t.top):-1,hidden:mk.hidden,
          disp:getComputedStyle(mk).display,pb:getComputedStyle(st).paddingBottom};
}
async function boot(ms){
  var f=document.getElementById('f');
  await wait(ms);
  var w=f.contentWindow;
  if(!w.Site||!w.Site.LB){R.push("FAIL  页面未就绪");return null}
  w.windowErrors=w.windowErrors||[];
  w.onerror=function(m){w.windowErrors.push(String(m))};
  return w;
}
function finish(){document.getElementById('T').textContent=R.join('\\n')||'NO CHECKS'}
__SCENE__
</script></body></html>"""

SCENES = {
    # 结构断言：溢出、可点区域、黑条与工具条的几何关系（灯箱档 → 原图档）
    "assert": """
(async function(){
  var w=await boot(1600); if(!w) return finish();
  var d=w.document, de=d.documentElement;
  ok('视口真实', w.innerWidth>300, w.innerWidth+'x'+w.innerHeight);
  ok('无横向溢出', de.scrollWidth<=de.clientWidth+1, de.scrollWidth+'/'+de.clientWidth);
  var over=[];
  d.querySelectorAll('body *').forEach(function(el){
    var r=el.getBoundingClientRect(), sc=false;
    for(var a=el.parentElement;a;a=a.parentElement){
      var cs2=w.getComputedStyle(a);
      if(/auto|scroll|hidden/.test(cs2.overflowX)||/auto|scroll|hidden/.test(cs2.overflow)){sc=true;break}
    }
    if(!sc&&r.width>0&&r.right>de.clientWidth+1&&w.getComputedStyle(el).position!=='fixed')
      over.push(el.tagName+'.'+String(el.className).slice(0,16)+'@'+Math.round(r.right));
  });
  ok('无越界元素', over.length===0, over.slice(0,3).join(', '));
  var small=[];
  d.querySelectorAll('button, .nav a, .card, .shot').forEach(function(el){
    var r=el.getBoundingClientRect();
    if(r.width>0&&r.height>0&&(r.height<28||r.width<28)) small.push((el.textContent||'').trim().slice(0,6)+':'+Math.round(r.width)+'x'+Math.round(r.height));
  });
  ok('可点区域不过小', small.length===0, small.slice(0,3).join(', '));
  // 开灯箱
  d.querySelector('.shot').click();
  await wait(3000);
  var LB=w.Site.LB, it=LB.items[LB.idx];
  ok('灯箱已开', LB.root.classList.contains('is-open'));
  var A=geo(w);
  if(it.ai){
    ok('灯箱档：黑条在画', A.hidden===false && A.disp!=='none', A.hidden+'/'+A.disp);
    ok('灯箱档：条贴画面底缘', Math.abs(A.markTop-A.imgBottom)<=2, A.markTop+' vs '+A.imgBottom);
    ok('灯箱档：条不压工具条', A.markBottom<=A.toolsTop+1, A.markBottom+' vs '+A.toolsTop);
    ok('灯箱档：条在舞台内未被裁', A.markBottom<=A.stageBottom+1, A.markBottom+' vs '+A.stageBottom);
    ok('灯箱档：条宽=图宽', Math.abs(A.markW-A.imgW)<=2, A.markW+'/'+A.imgW);
  } else {
    ok('灯箱档：无标识作品不画条', A.hidden===true, A.hidden);
  }
  ok('灯箱档：画面未被工具条压住', A.imgBottom<=A.toolsTop+1, A.imgBottom+' vs '+A.toolsTop);
  // 换原图档
  d.querySelector('.lb__tools button[data-act="full"]').click();
  await wait(6000);
  var B=geo(w);
  ok('原图档：已换上 f_', /^f_/.test((LB.img.currentSrc||LB.img.src).split('/').pop())||!LB._fullOn,
     (LB.img.currentSrc||LB.img.src).split('/').pop()+' fullOn='+LB._fullOn);
  if(it.ai){
    ok('原图档：黑条仍在', B.hidden===false && B.disp!=='none', B.hidden+'/'+B.disp);
    ok('原图档：条贴底缘', Math.abs(B.markTop-B.imgBottom)<=2, B.markTop+' vs '+B.imgBottom);
    ok('原图档：条不压工具条', B.markBottom<=B.toolsTop+1, B.markBottom+' vs '+B.toolsTop);
    ok('原图档：条未被裁', B.markBottom<=B.stageBottom+1, B.markBottom+' vs '+B.stageBottom);
    ok('原图档：尺寸未塌', B.markW>200 && B.markH>=22, B.markW+'x'+B.markH);
    LB.zoomTo(2,null,null,false); await wait(400);
    var C=geo(w);
    ok('原图档放大2x：条跟着走', Math.abs(C.markTop-C.imgBottom)<=3, C.markTop+' vs '+C.imgBottom);
    LB.zoomTo(1,null,null,false); await wait(300);
  } else {
    ok('无标识作品：条不出现', B.hidden===true, B.hidden);
    ok('无标识作品：未多留白', parseFloat(B.pb)<=parseFloat(A.pb)+1, A.pb+' -> '+B.pb);
  }
  ok('无 JS 报错', !(w.windowErrors||[]).length, (w.windowErrors||[]).join('|'));
  finish();
})();""",
}

SHOTS = {
    "wall": """
(async function(){var w=await boot(2600); if(!w) return finish();
  var d=w.document; var g=d.querySelector('.wall, .grp');
  if(g) g.scrollIntoView();
  await wait(1400); finish();})();""",
    "lb_view": """
(async function(){var w=await boot(1600); if(!w) return finish();
  w.document.querySelector('.shot').click(); await wait(3500); finish();})();""",
    "lb_full": """
(async function(){var w=await boot(1600); if(!w) return finish();
  var d=w.document; d.querySelector('.shot').click(); await wait(3200);
  var b=d.querySelector('.lb__tools button[data-act="full"]');
  if(b&&!b.disabled){b.click(); await wait(6000);} else {await wait(500);}
  finish();})();""",
    "lb_full_zoom": """
(async function(){var w=await boot(1600); if(!w) return finish();
  var d=w.document; d.querySelector('.shot').click(); await wait(3200);
  var b=d.querySelector('.lb__tools button[data-act="full"]');
  if(b&&!b.disabled){b.click(); await wait(6000);}
  w.Site.LB.zoomTo(2,null,null,false); await wait(600); finish();})();""",
    "hero": """
(async function(){await boot(2600); finish();})();""",
}


def harness(page, scene_js, w, h, src):
    os.makedirs(PREVIEW, exist_ok=True)
    p = os.path.join(PREVIEW, "_vh.html")
    open(p, "w", encoding="utf-8").write(
        BASE.replace("__W__", str(w)).replace("__H__", str(h))
            .replace("__SRC__", src).replace("__SCENE__", scene_js))
    return "http://127.0.0.1:%d/.preview/_vh.html" % PORT


def serve_root():
    """loopback 静态服务：harness 必须与被测页同源才能读 contentWindow。"""
    os.chdir(ROOT)

    class Q(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

    h = type("H", (http.server.SimpleHTTPRequestHandler,),
             {"log_message": lambda *a: None})
    srv = Q(("127.0.0.1", PORT), h)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def results(out):
    m = re.search(r'<pre id="T">(.*?)</pre>', out or "", re.S)
    return H.unescape(m.group(1)).split("\n") if m else ["NO OUTPUT（浏览器没渲染出来）"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["assert", "shots", "probe"])
    ap.add_argument("target", nargs="?", default="comfyui.html")
    ap.add_argument("--w", type=int, default=390)
    ap.add_argument("--h", type=int, default=844)
    ap.add_argument("--dsf", type=float, default=2.0)
    a = ap.parse_args()

    binpath = find_browser()
    if a.mode == "probe":
        print("browser:", binpath)
        print("usable:", "YES" if works(binpath) else "NO")
        return
    if not works(binpath):
        print("警告：", binpath, "量不到真实视口，结果不可信")

    remote = a.target.startswith("http")
    srv = None if remote else serve_root()
    src = a.target if remote else "/".join(["http://127.0.0.1:%d" % PORT] + a.target.split("/"))
    fails = 0
    try:
        if a.mode == "assert":
            p = harness(a.target, SCENES["assert"], a.w, a.h, src)
            out = run([binpath, "--headless", "--no-sandbox", "--disable-gpu",
                       "--disk-cache-size=1",
                       "--force-device-scale-factor=%g" % a.dsf,
                       "--allow-file-access-from-files",
                       "--user-data-dir=" + prof(),
                       "--window-size=%d,%d" % (a.w + 30, a.h + 30),
                       "--virtual-time-budget=40000", "--dump-dom", p], 240)
            print("=== assert %s (%dx%d dsf%g) ===" % (a.target, a.w, a.h, a.dsf))
            for line in results(out):
                print(" ", line)
                if line.startswith(("FAIL", "NO OUTPUT", "THROW")):
                    fails += 1
        else:
            d = os.path.join(PREVIEW, "shots")
            os.makedirs(d, exist_ok=True)
            stem = re.sub(r"[^A-Za-z0-9_-]", "", os.path.basename(a.target.split("?")[0]) or "page")
            stem = stem.replace(".html", "") or "page"
            tag = "%s_%dx%d" % (stem, a.w, a.h)
            for name, js in SHOTS.items():
                p = harness(a.target, js, a.w, a.h, src)
                png = os.path.join(d, "%s_%s.png" % (tag, name))
                run([binpath, "--headless", "--no-sandbox", "--disable-gpu",
                       "--disk-cache-size=1",
                     "--hide-scrollbars", "--force-device-scale-factor=%g" % a.dsf,
                     "--user-data-dir=" + prof(),
                     "--window-size=%d,%d" % (a.w, a.h),
                     "--virtual-time-budget=40000", "--screenshot=" + png, p], 240)
                sz = os.path.getsize(png) if os.path.exists(png) else 0
                print("%-14s %s  %d bytes" % (name, png, sz))
                for line in [l for l in results(run([binpath, "--headless", "--no-sandbox",
                                                     "--disable-gpu", "--disk-cache-size=1",
                                                     "--user-data-dir=" + prof(),
                                                     "--window-size=%d,%d" % (a.w + 30, a.h + 30),
                                                     "--virtual-time-budget=40000",
                                                     "--dump-dom", p], 240))
                             if l.startswith(("FAIL", "NO OUTPUT"))]:
                    print("   !", line)
                    fails += 1
    finally:
        if srv:
            srv.shutdown()
    print("合计失败：%d" % fails)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
