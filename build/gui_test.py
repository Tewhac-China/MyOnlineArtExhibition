# -*- coding: utf-8 -*-
"""GUI 自测：把测试脚本注入页面，headless 跑一遍，把结果写进 <pre id="T">。"""
import subprocess, os, sys, re, json, html as htmlmod

EDGE = r"C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

COMMON = r"""
var R=[];
function ok(name, cond, detail){ R.push((cond?"PASS":"FAIL")+"  "+name+(detail?"  :: "+detail:"")); }
function wait(ms){ return new Promise(function(r){ setTimeout(r,ms); }); }
function finish(){ var pre=document.createElement('pre'); pre.id='T'; pre.textContent=R.join('\n'); document.body.appendChild(pre); }
"""

INDEX_T = r"""
(async function(){
  try{
    await wait(900);
    var cards=document.querySelectorAll('.card');
    ok('卡片数量=3', cards.length===3, cards.length);
    ok('卡片链接', cards[0].getAttribute('href')==='comfyui.html' && cards[2].getAttribute('href')==='backgrounds.html');
    var imgs=[].map.call(cards, function(c){ return c.querySelector('img'); });
    ok('封面图已加载', imgs.every(function(i){ return i.naturalWidth>0; }), imgs.map(function(i){return i.naturalWidth;}).join(','));
    var bg=document.querySelectorAll('#heroBg div');
    ok('首屏三联背景', [].every.call(bg, function(d){ return /url\(/.test(d.style.backgroundImage); }));
    ok('总数文案', /^\d+$/.test(document.getElementById('statTotal').textContent), document.getElementById('statTotal').textContent);
    ok('无横向溢出(1440)', document.documentElement.scrollWidth<=document.documentElement.clientWidth+1,
       document.documentElement.scrollWidth+'/'+document.documentElement.clientWidth);
    ok('无 JS 报错', ERRS.length===0, ERRS.join('|'));
  }catch(e){ R.push('THROW '+e.message); }
  finish();
})();
"""

COMFY_T = r"""
(async function(){
  try{
    await wait(900);
    var L=Site.LB, secs=document.querySelectorAll('.grp'), chips=document.querySelectorAll('#filters button');
    ok('主题分组数>0', secs.length>0, secs.length);
    ok('筛选按钮=分组+1', chips.length===secs.length+1, chips.length+'/'+secs.length);
    // 筛选
    chips[1].click(); await wait(200);
    var vis=[].filter.call(secs, function(s){ return s.style.display!=='none'; });
    ok('筛选后只剩一组', vis.length===1, vis.length);
    var shownShots=[].filter.call(document.querySelectorAll('.shot'), function(s){
      for(var n=s;n&&n!==document.documentElement;n=n.parentElement){ if(getComputedStyle(n).display==='none') return false; }
      return true; });
    ok('筛选后可见张数=该组张数', shownShots.length===+chips[1].querySelector('.c').textContent, shownShots.length);
    chips[0].click(); await wait(200);
    // 灯箱
    var all=document.querySelectorAll('.shot');
    all[5].click(); await wait(1200);
    ok('灯箱已打开', L.root.classList.contains('is-open'));
    ok('灯箱序列=全部作品', L.items.length===all.length, L.items.length+'/'+all.length);
    ok('打开的是第 6 张', L.idx===5, L.idx);
    var src0=document.querySelector('.lb__img').src;
    document.querySelector('.lb__nav.next').click(); await wait(900);
    ok('下一张 idx+1', L.idx===6, L.idx);
    ok('下一张换了图', document.querySelector('.lb__img').src!==src0);
    document.querySelector('.lb__nav.prev').click(); await wait(900);
    ok('上一张 idx-1', L.idx===5, L.idx);
    // 缩放（百分比按原生像素算：100% = 一个图像像素对一个 CSS 像素）
    var pct=function(){ return parseInt(document.querySelector('.pct').textContent); };
    var fitPct=pct();
    ok('适应窗口 < 100%（8K 缩到窗口里本来就不到原生）', fitPct<100 && fitPct>0, fitPct);
    document.querySelector('.lb__tools [data-act="in"]').click(); await wait(400);
    ok('放大按钮生效', pct()>fitPct, pct()+' vs '+fitPct);
    document.querySelector('.lb__tools [data-act="one"]').click(); await wait(600);
    ok('1:1 = 原生 100%', pct()===100, pct());
    document.querySelector('.lb__tools [data-act="fit"]').click(); await wait(400);
    ok('适应窗口回到初始比例', pct()===fitPct, pct()+' vs '+fitPct);
    // 原图
    ok('原图标签就绪', /原图 · \d+ × \d+/.test(document.querySelector('.lb__res').textContent),
       document.querySelector('.lb__res').textContent);
    var im=document.querySelector('.lb__img');
    ok('显示的是原图分辨率', im.naturalWidth===2048, im.naturalWidth);
    // 信息面板
    document.querySelector('.lb__info-btn').click(); await wait(300);
    ok('信息面板可收起', getComputedStyle(document.querySelector('.lb__info')).display==='none');
    document.querySelector('.lb__info-btn').click(); await wait(300);
    // ESC
    document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true})); await wait(400);
    ok('ESC 关闭', !L.root.classList.contains('is-open'));
    // 版本视图
    document.querySelector('#modeSwitch [data-mode="version"]').click(); await wait(600);
    ok('切换版本视图', document.querySelectorAll('.grp').length>0, document.querySelectorAll('.grp').length);
    ok('无横向溢出(1440)', document.documentElement.scrollWidth<=document.documentElement.clientWidth+1,
       document.documentElement.scrollWidth+'/'+document.documentElement.clientWidth);
    ok('无 JS 报错', ERRS.length===0, ERRS.join('|'));
  }catch(e){ R.push('THROW '+e.message+' @'+(e.stack||'').split('\n')[1]); }
  finish();
})();
"""

COLLAGE_T = r"""
(async function(){
  try{
    await wait(900);
    var L=Site.LB, all=document.querySelectorAll('.shot');
    ok('作品数=6', all.length===6, all.length);
    ok('层序图存在', !!document.querySelector('#proc img'), '');
    all[0].click(); await wait(1500);
    ok('灯箱打开', L.root.classList.contains('is-open'));
    ok('序列=6', L.items.length===6, L.items.length);
    ok('原图 5312 宽', document.querySelector('.lb__img').naturalWidth===5312, document.querySelector('.lb__img').naturalWidth);
    ok('原图标签', /5312 × 8704/.test(document.querySelector('.lb__res').textContent), document.querySelector('.lb__res').textContent);
    ok('文案字段齐全', /這一天算什麼/.test(document.querySelector('.lb__info').textContent), '');
    document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true})); await wait(300);
    ok('无横向溢出(1440)', document.documentElement.scrollWidth<=document.documentElement.clientWidth+1,
       document.documentElement.scrollWidth+'/'+document.documentElement.clientWidth);
    ok('无 JS 报错', ERRS.length===0, ERRS.join('|'));
  }catch(e){ R.push('THROW '+e.message); }
  finish();
})();
"""

BG_T = r"""
(async function(){
  try{
    await wait(900);
    var L=Site.LB, secs=document.querySelectorAll('#seriesWrap .block'), chips=document.querySelectorAll('#filters button');
    var all=document.querySelectorAll('.shot');
    ok('系列数=5', secs.length===5, secs.length);
    ok('筛选按钮=系列+1', chips.length===secs.length+1, chips.length);
    ok('作品数>100', all.length>100, all.length);
    chips[1].click(); await wait(250);
    var vis=[].filter.call(secs, function(s){ return s.style.display!=='none'; });
    ok('筛选只剩一个系列', vis.length===1, vis.length);
    chips[0].click(); await wait(250);
    all[3].click(); await wait(1500);
    ok('灯箱打开', L.root.classList.contains('is-open'));
    ok('序列=全部作品', L.items.length===all.length, L.items.length+'/'+all.length);
    ok('原图标签', /原图 · \d+ × \d+/.test(document.querySelector('.lb__res').textContent), document.querySelector('.lb__res').textContent);
    document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true})); await wait(300);
    ok('无横向溢出(1440)', document.documentElement.scrollWidth<=document.documentElement.clientWidth+1,
       document.documentElement.scrollWidth+'/'+document.documentElement.clientWidth);
    ok('无 JS 报错', ERRS.length===0, ERRS.join('|'));
  }catch(e){ R.push('THROW '+e.message); }
  finish();
})();
"""

PAGES = {
    "index.html": INDEX_T,
    "comfyui.html": COMFY_T,
    "collage.html": COLLAGE_T,
    "backgrounds.html": BG_T,
}

WRAP = r"""<script>var ERRS=[];window.onerror=function(m){ERRS.push(m)};window.addEventListener('unhandledrejection',function(e){ERRS.push('reject:'+e.reason)});</script>"""


def run(page, script, w=1440, h=900, extra_flags=()):
    src = os.path.join(ROOT, page)
    html = open(src, encoding="utf-8").read()
    html = html.replace("</head>", WRAP + "</head>")
    html = html.replace("</body>", "<script>" + COMMON + script + "</script></body>")
    tmp = os.path.join(ROOT, "_t.html")
    open(tmp, "w", encoding="utf-8").write(html)
    out = subprocess.run(
        [EDGE, "--headless=new", "--disable-gpu", "--force-device-scale-factor=1",
         f"--window-size={w},{h}", "--virtual-time-budget=30000", "--dump-dom",
         *extra_flags, "file:///" + tmp.replace("\\", "/")],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    os.remove(tmp)
    m = re.search(r'<pre id="T">(.*?)</pre>', out.stdout, re.S)
    if not m:
        return ["NO OUTPUT (page may have crashed)"]
    return htmlmod.unescape(m.group(1)).split("\n")


if __name__ == "__main__":
    only = sys.argv[1] if len(sys.argv) > 1 else None
    total_fail = 0
    for page, script in PAGES.items():
        if only and only not in page:
            continue
        print(f"\n=== {page} ===")
        for line in run(page, script):
            print(" ", line)
            if line.startswith("FAIL") or line.startswith("THROW") or line.startswith("NO OUTPUT"):
                total_fail += 1
    print(f"\n合计失败：{total_fail}")
