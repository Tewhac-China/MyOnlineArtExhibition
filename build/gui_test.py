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
    var sk=document.querySelector('.skip');
    ok('有「阅读介绍」按钮', !!sk);
    var bar = sk ? getComputedStyle(sk, '::before') : null;
    ok('「阅读介绍」跳到图集之后', !!sk && sk.getAttribute('href')==='#how', sk && sk.getAttribute('href'));
    ok('图集排在介绍之前', document.querySelector('#works').compareDocumentPosition(document.querySelector('#how')) & 4, 'works→how');
    ok('「直接欣赏」有强调竖条', !!bar && bar.backgroundColor !== 'rgba(0, 0, 0, 0)' && parseFloat(bar.width) >= 2, bar && (bar.backgroundColor + ' / ' + bar.width));
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
    // 下载 / 全屏
    var dl=document.querySelector('[data-act="dl"]');
    ok('有下载按钮', !!dl);
    var rec=null, oc=HTMLAnchorElement.prototype.click;
    HTMLAnchorElement.prototype.click=function(){ rec={href:this.getAttribute('href'), name:this.getAttribute('download')}; };
    dl.click(); HTMLAnchorElement.prototype.click=oc;
    ok('下载指向原图', !!rec && rec.href===L.items[L.idx].full, rec && rec.href);
    ok('下载文件名沿用原始名', !!rec && /\.webp$/.test(rec.name) && rec.name.indexOf(L.items[L.idx].file.replace(/\.png$/,''))===0, rec && rec.name);
    ok('有全屏按钮', !!document.querySelector('[data-act="fs"]'));

    // 载入提示
    var ld=document.querySelector('.lb__load'), spin=document.querySelector('.lb__spin');
    ok('有载入提示层', !!ld && !!spin);
    ok('载入提示默认不挡画面', !!ld && !ld.classList.contains('is-on') && getComputedStyle(ld).visibility==='hidden');
    ok('转圈动画已注册', !!spin && getComputedStyle(spin).animationName==='lbSpin', spin && getComputedStyle(spin).animationName);
    L.showLoad(0); await wait(80);
    ok('载入提示能浮出', !!ld && ld.classList.contains('is-on'), ld && ld.className);
    L.hideLoad(); await wait(80);
    ok('载入提示能收起', !!ld && !ld.classList.contains('is-on'), ld && ld.className);
    ok('占位模糊已退掉', !document.querySelector('.lb__img').classList.contains('is-ph'));

    // 原图
    ok('原图标签就绪', /原图 · \d+ × \d+/.test(document.querySelector('.lb__res').textContent),
       document.querySelector('.lb__res').textContent);
    var im=document.querySelector('.lb__img');
    ok('显示的是原图分辨率', im.naturalWidth===L.items[L.idx].fw, im.naturalWidth+' vs '+L.items[L.idx].fw);
    // 信息面板
    document.querySelector('.lb__info-btn').click(); await wait(300);
    ok('信息面板可收起', getComputedStyle(document.querySelector('.lb__info')).display==='none');
    document.querySelector('.lb__info-btn').click(); await wait(300);
    // ESC
    document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true})); await wait(400);
    ok('ESC 关闭', !L.root.classList.contains('is-open'));

    // 慢网：把 Image 的 src 延迟 700ms，验证「载入提示 + 低清占位」这条路径
    var RealImage=window.Image;
    window.Image=function(){
      var im=new RealImage();
      var desc=Object.getOwnPropertyDescriptor(HTMLImageElement.prototype,'src');
      Object.defineProperty(im,'src',{ configurable:true,
        set:function(v){ setTimeout(function(){ desc.set.call(im,v); }, 700); },
        get:function(){ return desc.get.call(im); } });
      return im;
    };
    document.querySelectorAll('.shot')[20].click(); await wait(180);
    var ld2=document.querySelector('.lb__load'), im3=document.querySelector('.lb__img');
    ok('慢网下浮出载入提示', !!ld2 && ld2.classList.contains('is-on'), ld2 && ld2.className);
    ok('载入提示可见', !!ld2 && getComputedStyle(ld2).visibility==='visible', ld2 && getComputedStyle(ld2).visibility);
    ok('首次打开先铺低清占位', im3.classList.contains('is-ph'), im3.className);
    var phPct=parseInt(document.querySelector('.pct').textContent);
    await wait(2000);
    ok('加载完成后提示收起', !ld2.classList.contains('is-on'), ld2.className);
    ok('清晰图到位后模糊退掉', !im3.classList.contains('is-ph') && im3.naturalWidth>0, im3.className+'/'+im3.naturalWidth);
    ok('占位期间百分比不跳变', Math.abs(parseInt(document.querySelector('.pct').textContent)-phPct)<=2,
       phPct+' -> '+document.querySelector('.pct').textContent);
    window.Image=RealImage;
    document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true})); await wait(400);
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
    var note=document.querySelector('#note');
    ok('有「关于节点」一节', !!note && /关于节点/.test(note.textContent));
    ok('感悟分段齐全', !!note && note.querySelectorAll('.note p').length>=7, note && note.querySelectorAll('.note p').length);
    ok('收尾段有强调线', !!note && !!note.querySelector('.note .close'));
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
    ok('系列图集在介绍之前', !!document.querySelector('#seriesWrap') &&
       !!(document.querySelector('#seriesWrap').compareDocumentPosition(document.querySelector('#how')) & 4), 'seriesWrap→how');
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
