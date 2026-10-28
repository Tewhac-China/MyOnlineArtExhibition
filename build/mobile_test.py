# -*- coding: utf-8 -*-
"""竖屏（390×844）自测：用 iframe 把页面装进真实 390px 视口，父页读结果。"""
import subprocess, os, re, html as H, sys

EDGE = r"C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

HARNESS = """<!DOCTYPE html><html><head><meta charset="utf-8">
<style>html,body{margin:0;background:#111}iframe{width:390px;height:844px;border:0;display:block}</style>
</head><body><iframe id="f" src="__SRC__"></iframe>
<script>
var R=[];
function ok(n,c,d){ R.push((c?"PASS":"FAIL")+"  "+n+(d?"  :: "+d:"")); }
function wait(ms){ return new Promise(function(r){setTimeout(r,ms)}); }
(async function(){
  var f=document.getElementById('f');
  await wait(1200);
  try{
    var d=f.contentDocument, w=f.contentWindow, de=d.documentElement;
    ok('无横向溢出', de.scrollWidth<=de.clientWidth+1, de.scrollWidth+'/'+de.clientWidth);
    // 找出所有越界的可见元素
    var over=[];
    d.querySelectorAll('body *').forEach(function(el){
      var r=el.getBoundingClientRect();
      var scroller=false;
      for(var a=el.parentElement;a;a=a.parentElement){
        var cs2=getComputedStyle(a);
        if(cs2.overflowX==='auto'||cs2.overflowX==='scroll'){ scroller=true; break; }
        // 被祖先裁掉的装饰层（比如放大 3% 的首屏背景）不算越界
        if(cs2.overflow==='hidden'||cs2.overflowX==='hidden'){ scroller=true; break; }
      }
      if(!scroller && r.width>0 && r.right>de.clientWidth+1 && getComputedStyle(el).position!=='fixed'){
        over.push(el.tagName+'.'+String(el.className).slice(0,18)+'@'+Math.round(r.right));
      }
    });
    ok('无越界元素', over.length===0, over.slice(0,4).join(', '));
    // 顶栏导航是否放得下
    var nav=d.querySelector('.nav'), nb=nav?nav.getBoundingClientRect():null;
    ok('顶栏导航未溢出', !nb || nb.right<=de.clientWidth+1, nb?Math.round(nb.right):'no nav');
    // 可点区域
    var small=[];
    d.querySelectorAll('button, .nav a, .skip, .card, .shot, .filters button').forEach(function(el){
      var r=el.getBoundingClientRect();
      if(r.width>0 && r.height>0 && (r.height<28||r.width<28)) small.push((el.textContent||'').trim().slice(0,8)+':'+Math.round(r.width)+'x'+Math.round(r.height));
    });
    ok('可点区域不过小(<28px)', small.length===0, small.slice(0,5).join(', '));
    // 首屏标题不溢出
    var h1=d.querySelector('h1');
    ok('标题在视口内', !h1 || h1.getBoundingClientRect().right<=de.clientWidth+1,
       h1?Math.round(h1.getBoundingClientRect().right)+'/'+de.clientWidth:'no h1');
    // 灯箱：打开后工具条可用
    var shot=d.querySelector('.shot');
    if(shot){
      shot.click(); await wait(1500);
      var lb=d.querySelector('.lb');
      ok('灯箱可打开', lb && lb.classList.contains('is-open'));
      var tools=d.querySelector('.lb__tools'), tr=tools.getBoundingClientRect();
      ok('工具条在视口内', tr.left>=0 && tr.right<=de.clientWidth+1, Math.round(tr.left)+'~'+Math.round(tr.right));
      var tb=[].map.call(tools.querySelectorAll('button'), function(b){ return b.getBoundingClientRect().height; });
      ok('工具按钮≥32px', tb.every(function(h){ return h>=32; }), tb.join(','));
      var im=d.querySelector('.lb__img').getBoundingClientRect();
      ok('图片未超出视口', im.width<=de.clientWidth+1, Math.round(im.width)+'/'+de.clientWidth);
      var info=d.querySelector('.lb__info').getBoundingClientRect();
      ok('信息面板不遮满屏', info.height<=de.clientHeight*0.5, Math.round(info.height)+'/'+de.clientHeight);
    }
    ok('无 JS 报错', !w.ERRS || w.ERRS.length===0, (w.ERRS||[]).join('|'));
  }catch(e){ R.push('THROW '+e.message); }
  var pre=document.createElement('pre'); pre.id='T'; pre.textContent=R.join('\\n'); document.body.appendChild(pre);
})();
</script></body></html>"""

PAGES = ["index.html", "comfyui.html", "collage.html", "backgrounds.html"]


def run(page):
    src = page
    open(os.path.join(ROOT, "_h.html"), "w", encoding="utf-8").write(HARNESS.replace("__SRC__", src))
    # 页面本身要注入错误收集
    p = os.path.join(ROOT, page)
    html = open(p, encoding="utf-8").read()
    html = html.replace("</head>", "<script>window.ERRS=[];window.onerror=function(m){ERRS.push(m)};</script></head>")
    open(os.path.join(ROOT, "_m_" + page), "w", encoding="utf-8").write(html)
    open(os.path.join(ROOT, "_h.html"), "w", encoding="utf-8").write(HARNESS.replace("__SRC__", "_m_" + page))
    out = subprocess.run(
        [EDGE, "--headless=new", "--disable-gpu", "--force-device-scale-factor=1",
         "--allow-file-access-from-files", "--window-size=420,900",
         "--virtual-time-budget=30000", "--dump-dom",
         "file:///" + os.path.join(ROOT, "_h.html").replace("\\", "/")],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    for f in ("_h.html", "_m_" + page):
        try: os.remove(os.path.join(ROOT, f))
        except OSError: pass
    m = re.search(r'<pre id="T">(.*?)</pre>', out.stdout, re.S)
    return H.unescape(m.group(1)).split("\n") if m else ["NO OUTPUT"]


if __name__ == "__main__":
    fails = 0
    for page in (sys.argv[1:] or PAGES):
        print(f"\n=== 竖屏 390 · {page} ===")
        for line in run(page):
            print(" ", line)
            if line.startswith(("FAIL", "THROW", "NO OUTPUT")):
                fails += 1
    print(f"\n合计失败：{fails}")
