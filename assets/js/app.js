/* 線上展廳 · 共用交互 */
(function () {
  "use strict";

  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));

  /* ---------------------------------------------------- 頂欄 */
  function chrome() {
    const bar = $(".topbar");
    if (!bar) return;
    const onScroll = () => bar.classList.toggle("is-stuck", window.scrollY > 12);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });

    // 錨點高亮
    const links = $$(".nav a[data-sec]");
    if (!links.length) return;
    const secs = links.map(a => document.getElementById(a.dataset.sec)).filter(Boolean);
    const io = new IntersectionObserver(entries => {
      entries.forEach(e => {
        if (!e.isIntersecting) return;
        links.forEach(a => a.classList.toggle("is-active", a.dataset.sec === e.target.id));
      });
    }, { rootMargin: "-45% 0px -50% 0px" });
    secs.forEach(s => io.observe(s));
  }

  /* ---------------------------------------------------- 進場 */
  function reveals() {
    const els = $$(".rise:not(.is-in)");
    if (!els.length) return;
    const show = el => el.classList.add("is-in");

    // 已经在视口里的，直接显示，不等观察器回调（否则首屏内容会空白一拍）
    const vh = window.innerHeight || 800;
    els.forEach(el => {
      const r = el.getBoundingClientRect();
      if (r.top < vh * 0.96 && r.bottom > 0) show(el);
    });

    if (!("IntersectionObserver" in window)) { els.forEach(show); return; }
    const io = new IntersectionObserver(entries => {
      entries.forEach(e => {
        if (e.isIntersecting) { show(e.target); io.unobserve(e.target); }
      });
    }, { rootMargin: "0px 0px -8% 0px", threshold: 0.06 });
    els.forEach(el => { if (!el.classList.contains("is-in")) io.observe(el); });

    // 兜底：观察器异常时也不让内容永久隐形
    setTimeout(() => $$(".rise:not(.is-in)").forEach(show), 1600);
  }

  /* ---------------------------------------------------- 燈箱 · 圖片查看器 */
  const LB = {
    root: null, stage: null, img: null, info: null,
    items: [], idx: 0, cfg: null,
    s: 1, tx: 0, ty: 0, natS: 1, maxS: 16,
    slide: 0, sliding: false, slideBusy: false, _slideTimer: null, ghost: null, _pendingFull: null,
    pointers: new Map(), dragBase: null, pinch: null, moved: 0,
    base: { w: 1, h: 1 }, lastTap: 0, _token: 0, _fullSrc: null, _fullReady: false, _fullOn: false, _afterFull: null,
    _shown: false, _prefT: null,
    _cache: new Map(), _cacheMax: 12, _loadTimer: null, loadEl: null,
    markEl: null, markT: null, markNo: null, _markGeom: null, _markRetry: null, _markTries: 0,

    init() {
      if (this.root) return;
      const root = document.createElement("div");
      root.className = "lb";
      root.setAttribute("role", "dialog");
      root.setAttribute("aria-modal", "true");
      root.setAttribute("aria-label", "作品查看器");
      root.innerHTML = `
        <button class="lb__close" aria-label="关闭">✕</button>
        <button class="lb__info-btn" aria-label="信息面板">ⓘ</button>
        <div class="lb__stage">
          <button class="lb__nav prev" aria-label="上一张">‹</button>
          <div class="lb__canvas">
            <img class="lb__img" alt="" draggable="false">
            <img class="lb__ghost" alt="" draggable="false" hidden>
            <div class="lb__mark" hidden><span class="lb__mark__t"></span><span class="lb__mark__no"></span></div>
          </div>
          <div class="lb__load" role="status" aria-live="polite">
            <div class="lb__load-in">
              <svg class="lb__spin" width="34" height="34" viewBox="0 0 40 40" aria-hidden="true">
                <circle class="ring" cx="20" cy="20" r="17"></circle>
                <circle class="arc" cx="20" cy="20" r="17"></circle>
              </svg>
              <span class="lb__load-t">载入中</span>
            </div>
          </div>
          <button class="lb__nav next" aria-label="下一张">›</button>
          <div class="lb__tools">
            <button data-act="out" aria-label="缩小" title="缩小（-）">−</button>
            <button class="pct" data-act="reset" title="适应窗口（0）">100%</button>
            <button data-act="in" aria-label="放大" title="放大（+）">＋</button>
            <span class="lb__sep"></span>
            <button data-act="fit" aria-label="适应窗口" title="适应窗口">⤢</button>
            <button data-act="one" aria-label="原始大小" title="1:1 原始像素">1:1</button>
            <button data-act="full" aria-label="显示原图" title="显示原图（O）· 原始分辨率与原始编码">原图</button>
            <span class="lb__sep"></span>
            <button data-act="dl" aria-label="下载原图" title="下载原图（D）">↓</button>
            <button data-act="fs" aria-label="全屏查看" title="全屏（F）">⛶</button>
          </div>
        </div>
        <aside class="lb__info"></aside>`;
      document.body.appendChild(root);

      this.root = root;
      this.stage = $(".lb__stage", root);
      this.img = $(".lb__img", root);
      this.ghost = $(".lb__ghost", root);
      this.info = $(".lb__info", root);
      this.loadEl = $(".lb__load", root);
      this.markEl = $(".lb__mark", root);
      this.markT = $(".lb__mark__t", root);
      this.markNo = $(".lb__mark__no", root);

      $(".lb__close", root).addEventListener("click", () => this.close());
      $(".lb__info-btn", root).addEventListener("click", () => root.classList.toggle("info-off"));
      this.info.addEventListener("click", e => {
        const b = e.target.closest(".lb__prompt-t");
        if (b) this.togglePrompt(b);
      });
      $(".prev", root).addEventListener("click", e => { e.stopPropagation(); this.go(-1); });
      $(".next", root).addEventListener("click", e => { e.stopPropagation(); this.go(1); });

      $$(".lb__tools button", root).forEach(b => {
        b.addEventListener("click", e => {
          e.stopPropagation();
          const a = b.dataset.act;
          if (a === "in") this.zoomBy(1.4);
          else if (a === "out") this.zoomBy(1 / 1.4);
          else if (a === "reset" || a === "fit") this.reset();
          else if (a === "one") this.actualSize();
          else if (a === "full") this.toggleFull(b);
          else if (a === "dl") this.download(b);
          else if (a === "fs") this.toggleFullscreen();
        });
      });

      const onFsChange = () => {
        if (!root.classList.contains("is-open")) return;
        this.refreshRect();
        this.clampPan();
        this.apply(false);
      };
      document.addEventListener("fullscreenchange", onFsChange);
      document.addEventListener("webkitfullscreenchange", onFsChange);

      this.bindPointer();
      this.bindWheel();

      document.addEventListener("keydown", e => {
        if (!root.classList.contains("is-open")) return;
        if (e.key === "Escape") this.close();
        else if (e.key === "ArrowLeft") this.go(-1);
        else if (e.key === "ArrowRight") this.go(1);
        else if (e.key === "+" || e.key === "=") this.zoomBy(1.4);
        else if (e.key === "-") this.zoomBy(1 / 1.4);
        else if (e.key === "0") this.reset();
        else if (e.key === "o" || e.key === "O") this.toggleFull($('[data-act="full"]', root));
        else if (e.key === "d" || e.key === "D") {
          const b = $('[data-act="dl"]', root);
          this.download(b);
        }
        else if (e.key === "f" || e.key === "F") this.toggleFullscreen();
        else if (e.key === "i" || e.key === "I") root.classList.toggle("info-off");
      });
      window.addEventListener("resize", () => {
        if (!root.classList.contains("is-open")) return;
        this.refreshRect();
        this.reset();
      });
      // 位图真正上屏（含灯箱档 ⇄ 原图档就地换图）是「几何尺寸此刻才算准」的时刻：
      // 换 src 的那一帧 clientWidth 可能还是 0，量到的都是废值，重排一次才收口。
      this.img.addEventListener("load", () => {
        if (!root.classList.contains("is-open") || this.slideBusy) return;
        this.measure();
        this.apply(false);
      });
    },

    /* ---------------- 指针：拖动 + 双指捏合 ---------------- */
    bindPointer() {
      const st = this.stage;
      st.addEventListener("pointerdown", e => {
        if (e.target.closest("button")) return;
        // 指针可能在这一刻已经失效（快速抬手 / 合成事件），抛错会连累后续逻辑
        try { st.setPointerCapture(e.pointerId); } catch (err) { /* 捕获失败不影响拖动 */ }
        this.pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
        this.moved = 0;
        if (this.pointers.size === 1) {
          this.dragBase = { x: e.clientX, y: e.clientY, tx: this.tx, ty: this.ty };
          this.downPt = { x: e.clientX, y: e.clientY };
          if (this.s > 1) st.classList.add("is-dragging");
        } else if (this.pointers.size === 2) {
          this.dragBase = null;
          this.pinch = this.pinchInfo();
        }
      });

      st.addEventListener("pointermove", e => {
        if (!this.pointers.has(e.pointerId)) return;
        this.pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });

        if (this.pointers.size >= 2 && this.pinch) {
          const p = this.pinchInfo();
          if (this.pinch.dist > 0 && p.dist > 0) {
            this.zoomTo(this.pinch.scale * (p.dist / this.pinch.dist), p.cx, p.cy, false);
            this.tx = this.pinch.tx + (p.cx - this.pinch.cx);
            this.ty = this.pinch.ty + (p.cy - this.pinch.cy);
            this.apply(false);
          }
          this.moved = 99;
          return;
        }

        if (this.dragBase && this.s > 1) {
          const dx = e.clientX - this.dragBase.x;
          const dy = e.clientY - this.dragBase.y;
          this.moved = Math.max(this.moved, Math.abs(dx) + Math.abs(dy));
          this.tx = this.dragBase.tx + dx;
          this.ty = this.dragBase.ty + dy;
          this.apply(false);
        } else if (this.dragBase && this.items.length > 1) {
          // 未放大：横向拖动直接带画面，跟手；纵向或斜向不抢
          const dx = e.clientX - this.dragBase.x;
          const dy = e.clientY - this.dragBase.y;
          if (!this.sliding) {
            // 起手判定：横向位移要明显大于纵向，且超过 8px 才进入滑动
            if (Math.abs(dx) < 8 || Math.abs(dx) < Math.abs(dy) * 1.3) return;
            this.sliding = true;
          }
          this.moved = Math.max(this.moved, Math.abs(dx));
          const W = (st.clientWidth || window.innerWidth) * 0.92;
          this.img.classList.remove("is-slide");
          this.slide = Math.max(-W, Math.min(W, dx * 0.92));
          this.apply(false);
        }
      });

      const end = e => {
        const wasSingle = this.pointers.size === 1;
        this.pointers.delete(e.pointerId);
        if (this.pointers.size < 2) this.pinch = null;
        if (this.pointers.size === 0) {
          if (this.sliding) {
            // 松手：够远就让画面继续滑出去完成切换，否则回弹。两种都不算"点空白关闭"。
            const dx = this.slide;
            const W = (st.clientWidth || window.innerWidth) * 0.92;
            // 阈值要有下限：只按宽度算，窄屏/异常布局下会退化到几像素，轻碰就切图
            const need = Math.max(48, Math.min(120, W * 0.18));
            const commit = Math.abs(dx) > need;
            this.sliding = false;
            this.downPt = null;
            this.dragBase = null;
            this.settleSlide(commit ? (dx < 0 ? 1 : -1) : 0, dx);
            return;
          }
          this.downPt = null;
          this.dragBase = null;
          st.classList.remove("is-dragging");
        } else if (this.pointers.size === 1) {
          const [id] = this.pointers.keys();
          const p = this.pointers.get(id);
          this.dragBase = { x: p.x, y: p.y, tx: this.tx, ty: this.ty };
        }
        // 触摸双击（浏览器不一定派发 dblclick）
        if (wasSingle && e.pointerType !== "mouse" && this.moved < 8) {
          const now = Date.now();
          if (now - this.lastTap < 320) {
            this.lastTap = 0;
            if (this.s > 1.05) this.reset();
            else this.zoomTo(this.natS, e.clientX, e.clientY, true);
          } else {
            this.lastTap = now;
          }
        }
      };
      st.addEventListener("pointerup", end);
      st.addEventListener("pointercancel", end);

      // 点空白处关闭（拖动过则不算点击）
      st.addEventListener("click", e => {
        if (e.target.closest("button")) return;
        if (e.target === this.img) return;
        if (this.moved < 6) this.close();
      });

      st.addEventListener("dblclick", e => {
        if (e.target.closest("button")) return;
        e.preventDefault();
        if (this.s > 1.05) this.reset();
        else this.zoomTo(this.natS, e.clientX, e.clientY, true);
      });
    },

    pinchInfo() {
      const [a, b] = [...this.pointers.values()];
      return {
        dist: Math.hypot(a.x - b.x, a.y - b.y),
        cx: (a.x + b.x) / 2, cy: (a.y + b.y) / 2,
        scale: this.s, tx: this.tx, ty: this.ty
      };
    },

    /* ---------------- 滚轮 ---------------- */
    bindWheel() {
      this.stage.addEventListener("wheel", e => {
        if (e.target.closest("button")) return;
        e.preventDefault();
        const k = e.deltaMode === 1 ? 0.06 : 0.0016;
        this.zoomTo(this.s * Math.exp(-e.deltaY * k * 1.6), e.clientX, e.clientY, false);
      }, { passive: false });
    },

    /* ---------------- 变换 ---------------- */
    measure() {
      // clientWidth 不受 transform 影响，始终是“适应窗口”时的基准尺寸
      this.base.w = this.img.clientWidth || 1;
      this.base.h = this.img.clientHeight || 1;
      // 百分比按「原生像素」算：100% 就是一个图像像素对一个 CSS 像素，
      // 跟看图软件一致。按“适应窗口=100%”算的话，8K 图在 100% 时其实只有 7%，
      // 会让人以为已经是原图了 —— 这正是「大图不像 8K」的来源。
      const it = this.items[this.idx] || {};
      const nat = it.fw || it.w || this.img.naturalWidth || this.base.w;
      // 低清占位为了撑住最终版位会拉成整宽（object-fit: contain 会留边），
      // 所以按「实际画出来的宽度」算，免得占位期间百分比跳一下再跳回来
      const ar = (it.fw && it.fh) ? it.fw / it.fh
               : (this.img.naturalWidth && this.img.naturalHeight)
                 ? this.img.naturalWidth / this.img.naturalHeight : 0;
      const drawn = ar ? Math.min(this.base.w, this.base.h * ar) : this.base.w;
      this.natS = Math.max(1, nat / (drawn || 1));
      this.maxS = Math.max(2, this.natS * 2);   // 最多放到原生的 200%
    },

    /** 以屏幕坐标 (cx, cy) 为锚点缩放到 target */
    zoomTo(target, cx, cy, anim) {
      this.measure();
      const s2 = clamp(target, 1, this.maxS || this.natS * 2 || 16);
      const ox = cx == null ? 0 : cx - (this._rl + this._rw / 2);
      const oy = cy == null ? 0 : cy - (this._rt + this._rh / 2);
      const k = s2 / this.s;
      this.tx = ox - (ox - this.tx) * k;
      this.ty = oy - (oy - this.ty) * k;
      this.s = s2;
      if (this.s <= 1.001) { this.s = 1; this.tx = 0; this.ty = 0; }
      this.apply(anim);
    },

    zoomBy(f) {
      this.zoomTo(this.s * f, this._rl + this._rw / 2, this._rt + this._rh / 2, true);
    },

    reset() {
      this.s = 1; this.tx = 0; this.ty = 0;
      this.apply(true);
    },

    actualSize() {
      const it = this.items[this.idx] || {};
      // 1:1 的语义是「一个原始像素对一个 CSS 像素」。灯箱档被限幅时，
      // 只有原图真在屏上才谈得上 1:1 —— 所以按需取原图，落地后再放大，
      // 而不是把 3000 的位图拉成 5312 还显示 100%。
      const capped = (it.fw || it.w) > (it.lw || it.fw || it.w);
      if (this._fullSrc && capped && !this._fullOn) {
        this._afterFull = () => this.zoomNat();
        this.toggleFull($('[data-act="full"]', this.root));
        return;
      }
      this.zoomNat();
    },

    zoomNat() {
      this.measure();
      this.s = 1; this.tx = 0; this.ty = 0;
      this.zoomTo(this.natS,
                 this._rl + this._rw / 2, this._rt + this._rh / 2, true);
    },

    /** 还没要原图时，信息栏说什么 */
    resIdle(it) {
      const fw = it.fw || it.w, fh = it.fh || it.h;
      const lw = it.lw || fw, lh = it.lh || fh;
      return lw < fw
        ? `原图 ${fw} × ${fh} · 当前 ${lw} × ${lh}，按 O 取原图`
        : `原图 ${fw} × ${fh} · 按 O 取原始编码`;
    },

    setFullBtn() {
      const b = $('[data-act="full"]', this.root);
      if (!b) return;
      const on = !!this._fullOn;
      b.classList.toggle("is-on", on);
      b.setAttribute("aria-pressed", on ? "true" : "false");
      // 长边不超过 FULL_MIN_EDGE 的那些没有独立原图档（灯箱档就是原图）：
      // 按钮必须显式禁用并说明原因，按下去没反应是最让人怀疑坏掉的做法。
      const has = !!this._fullSrc;
      b.disabled = !has;
      b.title = !has ? "灯箱档即原图，无更高编码档"
                     : on ? "已显示原图（再按一次退回灯箱档）"
                          : "显示原图（O）· 原始分辨率与原始编码";
    },

    /** 原图档：显式请求，到位后就地替换；再按一次退回灯箱档 */
    toggleFull(btn) {
      const it = this.items[this.idx] || {};
      const src = this._fullSrc;
      if (!src) return;
      const token = this._token;
      if (this._fullOn) {
        this._fullOn = false;
        this.img.src = it.large || it.thumb;
        this.setRes(this.resIdle(it), "idle");
        this.setFullBtn();
        requestAnimationFrame(() => { this.measure(); this.apply(false); });
        return;
      }
      const land = () => {
        if (token !== this._token) return;
        this._fullReady = true; this._fullOn = true;
        this.hideLoad();
        if (this.slideBusy) { this._pendingFull = src; this.setFullBtn(); return; }
        this.img.src = src;
        this.setRes(`原图 · ${it.fw || it.w} × ${it.fh || it.h}`, "ready");
        this.setFullBtn();
        // rAF 在页面不可见时不跑（后台标签页、被节流的窗口），
        // 只挂 rAF 会让「原图已到位但 1:1 没跟上」这种状态卡住；补一次兜底，
        // 跑两遍无害（measure/apply 幂等，_afterFull 第二次已经空了）。
        const after = () => {
          this.measure(); this.apply(false);
          if (this._afterFull) { const f = this._afterFull; this._afterFull = null; f(); }
        };
        requestAnimationFrame(after);
        setTimeout(after, 120);
      };
      const e = this.preload(src);
      if (!e) return;
      if (e.ready) { land(); return; }
      this.showLoad(0);
      this.setRes("载入原图…", "loading");
      e.el.addEventListener("load", land, { once: true });
      e.el.addEventListener("error", () => {
        this.hideLoad();
        if (token === this._token) this.setRes("原图载入失败", "error");
      }, { once: true });
    },

    /** 舞台尺寸只在打开 / 尺寸变化 / 图片切换后量一次，拖动时不再读布局 */
    refreshRect() {
      const r = this.stage.getBoundingClientRect();
      this._rw = r.width;
      this._rh = r.height;
      this._rl = r.left;
      this._rt = r.top;
    },

    clampPan() {
      const rw = this._rw || this.stage.clientWidth;
      const rh = this._rh || this.stage.clientHeight;
      const mx = Math.max(0, (this.base.w * this.s - rw) / 2) + 24;
      const my = Math.max(0, (this.base.h * this.s - rh) / 2) + 24;
      this.tx = clamp(this.tx, -mx, mx);
      this.ty = clamp(this.ty, -my, my);
    },

    /** 下载：文件名沿用源目录的原始输出名，方便和本地图库对照。
        带 AI 标识的系列由 canvas 现场合成「画面 + 黑条」再导出 ——
        发布的图片文件保持干净像素，标识只在交付那一刻加上。 */
    download(btn) {
      const it = this.items[this.idx] || {};
      const src = it.full || it.large || it.thumb;
      if (!src) return;
      const stem = String(it.file || "image").replace(/\.[^.]+$/, "");
      if (!it.ai) { this.linkDownload(src, stem + "." + this.extOf(src), btn); return; }
      this.showLoad(0);
      this.setRes("生成带标识文件…", "loading");
      this.composeWithMark(it, src).then(res => {
        this.hideLoad();
        if (res && res.url) {
          this.linkDownload(res.url, stem + "." + res.ext, btn, true);
          this.setRes(`已导出带标识文件 · ${res.px}`, "ready");
        } else {
          // 浏览器画不动（超大画幅）时退回原始文件，并说清楚它没有黑条
          this.linkDownload(src, stem + "." + this.extOf(src), btn);
          this.setRes("画幅太大合成不了，已导出原始文件（无标识条）", "error");
        }
      });
    },

    extOf(src) {
      return (String(src).match(/\.(webp|jpe?g|png)$/i) || [, "webp"])[1].toLowerCase();
    },

    linkDownload(href, name, btn, revoke) {
      const a = document.createElement("a");
      a.href = href;
      a.download = name;
      a.rel = "noopener";
      a.style.display = "none";
      document.body.appendChild(a);
      a.click();
      setTimeout(() => { a.remove(); if (revoke) URL.revokeObjectURL(href); }, 0);
      if (btn) {
        const t = btn.textContent;
        btn.classList.add("is-done");
        btn.textContent = "✓";
        setTimeout(() => { btn.classList.remove("is-done"); btn.textContent = t; }, 1100);
      }
    },

    /** 画面 + 黑条 合成一张导出图。超大画幅（>24M 像素）浏览器会画崩，
        直接返回 null 让调用方退回原始文件。 */
    composeWithMark(it, src) {
      return this.ensureImage(src).then(img => {
        const w = img.naturalWidth, h = img.naturalHeight;
        if (!w || !h || w * h > 24e6) return null;
        const bar = Math.max(24, Math.round(h * 0.045));
        const fs = Math.max(12, Math.round(bar * 0.52));
        const cv = document.createElement("canvas");
        cv.width = w; cv.height = h + bar;
        const g = cv.getContext("2d");
        g.fillStyle = "#000";
        g.fillRect(0, 0, cv.width, cv.height);
        g.drawImage(img, 0, 0, w, h);
        g.fillStyle = "#c9a227";
        g.textBaseline = "middle";
        g.font = `700 ${fs}px "Source Han Sans SC", "Noto Sans SC", sans-serif`;
        g.fillText(it.ai, Math.round(bar * 0.3), h + bar / 2);
        if (it.id) {
          g.font = `${Math.round(fs * 0.8)}px ui-monospace, Consolas, monospace`;
          g.globalAlpha = 0.62;
          const tw = g.measureText(it.id).width;
          g.fillText(it.id, w - Math.round(bar * 0.3) - tw, h + bar / 2);
          g.globalAlpha = 1;
        }
        const asBlob = type => new Promise(done => {
          try { cv.toBlob(b => done(b), type, 0.92); } catch (err) { done(null); }
        });
        return asBlob("image/webp").then(b => b ? [b, "webp"] : asBlob("image/jpeg").then(b2 => b2 ? [b2, "jpg"] : null))
          .then(pair => pair && {url: URL.createObjectURL(pair[0]), ext: pair[1], px: `${w} × ${h + bar}`});
      }).catch(() => null);
    },

    /** 取一张已解码的位图用于合成：优先用预取缓存，省一次重复请求 */
    ensureImage(src) {
      const e = this.preload(src);
      if (e && e.el && e.el.naturalWidth) return Promise.resolve(e.el);
      const im = new Image();
      return new Promise((res, rej) => {
        im.onload = () => res(im);
        im.onerror = rej;
        im.src = src;
      });
    },

    /** 全屏：把灯箱本体推进全屏，省掉浏览器边框，图能多占一截 */
    toggleFullscreen() {
      const d = document;
      const fs = d.fullscreenElement || d.webkitFullscreenElement;
      if (fs) {
        const exit = d.exitFullscreen || d.webkitExitFullscreen;
        if (exit) exit.call(d);
        return;
      }
      const req = this.root.requestFullscreen || this.root.webkitRequestFullscreen;
      if (!req) return;                       // iOS Safari 不支持元素全屏，静默跳过
      const r = req.call(this.root);
      if (r && r.catch) r.catch(() => {});
    },

    /** 百分比只写 DOM，不动画面 —— 首帧布局还没稳定时用它补一次 */
    syncPct() {
      // 换图的那一帧 clientWidth 还是 0/1，算出来会是 0%，等一帧再算
      if (!this.base.w || this.base.w < 2) {
        clearTimeout(this._pctT);
        this._pctT = setTimeout(() => { this.measure(); this.syncPct(); }, 60);
        return;
      }
      const p = Math.round(this.s / (this.natS || 1) * 100);
      if (p !== this._pct) {
        this._pct = p;
        const el = $(".pct", this.root);
        if (el) el.textContent = p + "%";
      }
    },

    apply(anim) {
      this.clampPan();
      const im = this.img;
      // 滑动切换期间由 .is-slide 驱动 transform，不能再挂 .is-anim（两者抢同一个属性）
      im.classList.toggle("is-anim", !!anim && !this.slide);
      im.style.transform = `translate3d(${this.tx + this.slide}px, ${this.ty}px, 0) scale(${this.s})`;
      this.stage.classList.toggle("is-zoomed", this.s > 1.001);
      this.syncPct();
      this.syncMark();
      if (anim) {
        clearTimeout(this._t);
        this._t = setTimeout(() => { im.classList.remove("is-anim"); this.syncMark(); }, 240);
      }
    },

    /* ---------------- AI 显式标识：前端画的黑条 ----------------
       图片文件本身是干净像素，条由 DOM 贴在画面下缘，位置用与图片完全相同的
       变换算出来，所以缩放平移时它始终贴着底边、和画面一起放大。
       图片绕自身中心缩放（底缘下移 bh/2·(s-1)），黑条绕自身顶边缩放。 */
    syncMark() {
      const m = this.markEl;
      if (!m) return;
      const im = this.img;
      m.classList.toggle("is-anim", im.classList.contains("is-anim"));
      m.classList.toggle("is-quick", im.classList.contains("is-quick"));
      m.classList.toggle("is-slide", im.classList.contains("is-slide"));
      const it = this.items[this.idx] || {};
      this.root.classList.toggle("has-mark", !!it.ai);
      if (!it.ai) {
        m.hidden = true;
        this._markGeom = null;
        clearTimeout(this._markRetry); this._markRetry = null;
        return;
      }
      const bw = this.base.w, bh = this.base.h;
      // 换档的那一帧（灯箱档 ⇄ 原图档、占位 → 真图）可能量到 0：measure() 会把它
      // 兜成 1，于是条会塌成 1px 宽 —— 看起来就像「显示原图时黑条没了」。
      // 所以量不到时绝不动几何：保留上一次画好的条，补一次布局再回来。
      if (!(bw > 1 && bh > 1)) {
        // 已经画好过一条：保持原样就行 —— 新位图 load 时会再量一次，
        // 不该在这里留一个每 60ms 自转的定时器（视口尺寸为 0 时会转个不停）。
        if (this._markGeom) { m.hidden = false; return; }
        // 一条都还没画出来：补测，但设上限，绝不让它变成无限重试
        if (!this._markRetry && (this._markTries || 0) < 8) {
          this._markTries = (this._markTries || 0) + 1;
          this._markRetry = setTimeout(() => {
            this._markRetry = null;
            this.measure(); this.apply(false);
          }, 60);
        }
        return;
      }
      // 上限 48px：再高就超出舞台为它预留的下边距，会压到工具条
      const bar = Math.min(48, Math.max(22, Math.round(bh * 0.045)));
      const fs = Math.max(11, Math.round(bar * 0.52));
      m.hidden = false;
      m.style.width = bw + "px";
      m.style.height = bar + "px";
      m.style.padding = "0 " + Math.round(bar * 0.3) + "px";
      m.style.fontSize = fs + "px";
      if (this.markT) this.markT.textContent = it.ai;
      if (this.markNo) this.markNo.textContent = it.id || "";
      m.style.transform = `translate3d(${this.tx + this.slide}px, ` +
        `${this.ty + (bh / 2) * (this.s - 1)}px, 0) scale(${this.s})`;
      this._markGeom = { w: bw, h: bar };
      this._markTries = 0;
    },

    setRes(text, state) {
      const el = $(".lb__res", this.root);
      if (!el) return;
      el.textContent = text;
      el.dataset.state = state || "";
    },

    /* ---------------- 载入提示 ----------------
       图片没到位时舞台原本只有一片黑（或停着上一张），看不出任何反馈。
       这里给一个短延迟的提示：快取命中时根本不会出现，慢的时候才浮出来。 */
    showLoad(delay = 110) {
      clearTimeout(this._loadTimer);
      this._loadTimer = setTimeout(() => {
        this._loadTimer = null;
        if (this.loadEl) this.loadEl.classList.add("is-on");
      }, delay);
    },
    hideLoad() {
      clearTimeout(this._loadTimer);
      this._loadTimer = null;
      if (this.loadEl) this.loadEl.classList.remove("is-on");
    },

    /** 首次打开时的低清占位：缩略图本来就在页面里，模糊压暗当作背景，好过纯黑 */
    placeholder(src) {
      const im = this.img;
      // 版位必须跟最终尺寸一模一样，否则清晰图到位时画面会「长大一圈」。
      // 画布是 grid 居中、宽度收缩到内容，所以只能按可用宽高把宽度算出来写死。
      const it = this.items[this.idx] || {};
      // 版位按「即将到位的那一档」算：灯箱档出图尺寸。
      // 黑条是 DOM，不参与位图尺寸，所以这里不再给它留高度 ——
      // 但占位与清晰图必须同一比例，否则到位瞬间画面会「长大一圈」。
      const lw = it.lw || it.fw || it.w;
      const lh = it.lh || it.fh || it.h;
      const ar = (lw && lh) ? lw / lh : 0;
      if (ar) {
        const cs = getComputedStyle(im);
        const ss = getComputedStyle(this.stage);
        const maxH = parseFloat(cs.maxHeight) || this.stage.clientHeight;
        const availW = this.stage.clientWidth
          - parseFloat(ss.paddingLeft || 0) - parseFloat(ss.paddingRight || 0);
        const w = Math.min(availW, maxH * ar);
        if (w > 0) im.style.width = w + "px";
      }
      im.classList.add("is-ph");
      im.src = src;
      im.classList.add("is-in");
      this.measure();
      this.apply(false);
    },

    /* ---------------- 打开 / 切换 ---------------- */
    open(items, i, cfg, groups) {
      this.init();
      this.items = items; this.cfg = cfg || {};
      this.groups = groups || [];
      this.root.classList.add("is-open");
      document.documentElement.style.overflow = "hidden";

      // 每次打开都按「首次进入」处理：清掉上一轮的画面与节奏，避免从上一次的图滑过来
      clearTimeout(this._slideTimer);
      this._lastNav = 0;
      this.slide = 0;
      this.sliding = false;
      this.slideBusy = false;
      this._pendingFull = null;
      this._fullOn = false;
      this._afterFull = null;
      clearTimeout(this._markRetry); this._markRetry = null;
      this._markGeom = null; this._markTries = 0;
      if (this.markEl) this.markEl.hidden = true;
      clearTimeout(this._prefT);
      this.hideLoad();
      const g = this.ghost;
      if (g) { g.hidden = true; g.removeAttribute("src"); g.classList.remove("is-slide"); }
      this.img.classList.remove("is-in", "is-slide", "is-quick", "is-anim", "is-ph");
      this.img.style.width = "";
      this.img.removeAttribute("src");

      this.refreshRect();
      this.show(i);
    },
    close() {
      this.root.classList.remove("is-open");
      document.documentElement.style.overflow = "";
      clearTimeout(this._slideTimer);
      this.sliding = false;
      this.slideBusy = false;
      this._pendingFull = null;
      this.slide = 0;
      clearTimeout(this._markRetry); this._markRetry = null;
      this._markGeom = null; this._markTries = 0;
      if (this.markEl) { this.markEl.hidden = true; this.markEl.className = "lb__mark"; }
      this.hideLoad();
      this.img.classList.remove("is-ph");
      this.ghost.hidden = true;
      this.ghost.removeAttribute("src");
      this.ghost.classList.remove("is-slide");
      this.img.classList.remove("is-slide");
      this.s = 1; this.tx = 0; this.ty = 0;
      this.img.style.transform = "";
      this._pct = null;
      this.syncPct();
    },
    go(d, dx = 0) {
      const n = this.items.length;
      this.show((this.idx + d + n) % n, d, dx);
    },
    show(i, dir = 1, dx = 0) {
      this.idx = i;
      const it = this.items[i];
      const cfg = this.cfg;
      this.s = 1; this.tx = 0; this.ty = 0;
      this._pct = null;
      this.syncPct();

      // 已有画面在位时才做滑动交接；首次打开仍是从容淡入
      const prevSrc = this.img.getAttribute("src") || "";
      const hadPrev = !!prevSrc && this.img.classList.contains("is-in");

      const token = ++this._token;
      const mode = dx ? "slide" : this.navMode();
      const largeSrc = it.large || it.thumb;
      const fullSrc = it.full && it.full !== it.large ? it.full : null;
      this._fullSrc = fullSrc;
      this._fullReady = false;
      this._fullOn = false;
      this._afterFull = null;
      clearTimeout(this._prefT);
      this._shown = false;
      this.setFullBtn();

      this.img.alt = it.title || "";
      const hit = this._cache.get(largeSrc);
      if (hit && hit.ready) {
        this.hideLoad();
        // 已预取并解码：直接同步上屏，点击即切换
        if (mode === "cut") this.cutTo(largeSrc);
        else if (mode === "quick") this.quickTo(largeSrc, dir);
        else this.paintNext(it, { src: largeSrc }, hadPrev, prevSrc, dir, dx);
        this.preloadNeighbors(i);
      } else {
      // 位图还没到手：先挂提示（有旧画面时稍等一下再浮出，避免一闪而过）
      this.showLoad(hadPrev ? 120 : 70);
      if (!hadPrev && it.thumb) this.placeholder(it.thumb);
      const next = new Image();
      next.onload = () => {
        if (token !== this._token) return;
        let painted = false;
        const paint = () => {
          if (painted || token !== this._token) return;
          painted = true;
          if (mode === "cut") this.cutTo(next.src);
          else if (mode === "quick") this.quickTo(next.src, dir);
          else this.paintNext(it, next, hadPrev, prevSrc, dir, dx);
        };
        // 解码完成再动画面，避免新 img 先顶着旧位图滑进来再被顶掉；
        // decode 在某些情况下不 settle，所以加一个短兜底，绝不卡住
        if (typeof next.decode === "function") {
          next.decode().then(paint, paint);
          setTimeout(paint, 120);
        } else paint();
      };
      next.onerror = () => {
        // 载入失败：收起提示，保留当前画面（首次打开则停在低清占位上），不白屏
        if (token === this._token) this.hideLoad();
      };
      next.src = largeSrc;
      this.img.alt = it.title || "";
      this.preloadNeighbors(i);
      }

      // 原图不再自动接管。灯箱档本身就是原分辨率（超大源按 VIEW_CAP 限幅），
      // 原图只在按「原图」/O、或 1:1 真需要原始像素时才请求 ——
      // 一张 8K 原图 3–5 MB，让每次翻页的人都替这张图付带宽，是这次改造要消掉的开销。
      const resText = fullSrc ? this.resIdle(it) : `原图 · ${it.fw || it.w} × ${it.fh || it.h}`;
      const resState = fullSrc ? "idle" : "ready";

      const rows = (cfg.rows ? cfg.rows(it) : []).filter(r => r && r[1] != null && r[1] !== "");
      const prompt = cfg.prompt ? cfg.prompt(it) : null;
      // 序列跨组时，标出当前这张属于哪一组，免得连着切的时候失去方位感
      const multi = new Set(this.groups.filter(Boolean)).size > 1;
      const grp = multi ? (this.groups[i] || "") : "";
      this.info.innerHTML = `
        <div class="lb__no">${String(i + 1).padStart(2, "0")} / ${String(this.items.length).padStart(2, "0")}</div>
        ${grp ? `<div class="lb__grp">${esc(grp)}</div>` : ""}
        <h3 class="lb__title">${esc(it.title || "")}</h3>
        <div class="lb__file">${esc(it.file || "")}</div>
        <div class="lb__res" data-state="${resState}">${resText}</div>
        <dl class="lb__rows">
          ${rows.map(([k, v]) => `<div class="lb__row"><dt>${esc(k)}</dt><dd>${esc(String(v))}</dd></div>`).join("")}
        </dl>
        ${prompt ? `<div class="lb__prompt-h"><span>原始提示词 · ${prompt.length} 字符</span>
          <button class="lb__prompt-t" type="button">展开</button></div>
        <pre class="lb__prompt is-clamped">${esc(prompt)}</pre>` : ""}`;
      this.info.scrollTop = 0;
      this.syncMark();
    },

    togglePrompt(btn) {
      const pre = $(".lb__prompt", this.info);
      if (!pre) return;
      const clamped = pre.classList.toggle("is-clamped");
      btn.textContent = clamped ? "展开" : "收起";
    },

    /** 切图节奏：cut=极快连击，quick=较快，slide=正常（保留完整滑动） */
    navMode() {
      const now = performance.now();
      const gap = now - (this._lastNav || 0);
      this._lastNav = now;
      if (gap < 130) return "cut";
      if (gap < 380) return "quick";
      return "slide";
    },

    /** 上一次滑动还没结束时的连击：不重放整段滑出动画，就地换图（否则每点一次都把画面甩出屏幕，看起来像卡住） */
    cutTo(src) {
      clearTimeout(this._slideTimer);
      this.slideBusy = false;
      this._pendingFull = null;
      const g = this.ghost;
      g.hidden = true;
      g.removeAttribute("src");
      g.classList.remove("is-slide");
      this.img.classList.remove("is-slide", "is-anim", "is-ph");
      this.img.style.width = "";
      this.slide = 0;
      this.img.src = src;
      this._shown = true;
      this.hideLoad();
      this.img.classList.add("is-in");
      this.measure();
      this.refreshRect();
      this.apply(false);
    },

    /** 连击时的短滑入：只偏 6% 再归位，既有方向感又不至于把画面甩出屏幕 */
    quickTo(src, dir) {
      clearTimeout(this._slideTimer);
      this.slideBusy = true;
      this._pendingFull = null;
      const g = this.ghost;
      g.hidden = true;
      g.removeAttribute("src");
      g.classList.remove("is-slide");

      this.img.classList.remove("is-anim", "is-slide", "is-quick", "is-ph");
      this.img.style.width = "";
      this.img.src = src;
      this._shown = true;
      this.hideLoad();
      this.img.classList.add("is-in");
      this.measure();
      this.refreshRect();

      const off = (dir >= 0 ? 1 : -1) * Math.max(24, (this._rw || 800) * 0.06);
      this.slide = off;
      this.apply(false);
      void this.img.offsetWidth;          // 先把起点画上去
      this.img.classList.add("is-quick");
      this.slide = 0;
      this.apply(false);

      this._slideTimer = setTimeout(() => {
        this.img.classList.remove("is-quick");
        this.slideBusy = false;
        this.measure();
        if (this._pendingFull) {
          const p = this._pendingFull;
          this._pendingFull = null;
          this.img.src = p;
          requestAnimationFrame(() => { this.measure(); this.apply(false); });
        }
      }, 150);
    },

    /** 预取并预解码：左右切换要用的下一张，提前放进内存，点击时零等待 */
    preload(src) {
      if (!src) return null;
      let e = this._cache.get(src);
      if (e) {
        // 命中就挪到队尾（LRU）
        this._cache.delete(src);
        this._cache.set(src, e);
        return e;
      }
      const im = new Image();
      e = { el: im, ready: false };
      const done = () => { e.ready = true; };
      im.addEventListener("load", done, { once: true });
      im.addEventListener("error", done, { once: true });
      im.src = src;
      if (typeof im.decode === "function") im.decode().then(done, done);
      this._cache.set(src, e);
      if (this._cache.size > this._cacheMax) {
        const oldest = this._cache.keys().next().value;
        if (oldest !== src) this._cache.delete(oldest);
      }
      return e;
    },

    /** 预取分两级：左右两张的缩略图（几十 KB）立刻拿，翻页至少不空白；
        灯箱档（几百 KB–1 MB）等用户停下来再预取；原图档永不预取 —— 那是显式动作。 */
    preloadNeighbors(i) {
      const n = this.items.length;
      if (n < 2) return;
      const at = k => this.items[(k + n) % n];
      const a = at(i + 1), b = at(i - 1);
      this.preload(a.thumb); this.preload(b.thumb);
      clearTimeout(this._prefT);
      this._prefT = setTimeout(() => {
        if (performance.now() - (this._lastNav || 0) < 400) return;   // 还在连着翻，别抢带宽
        this.preload(a.large || a.thumb);
        setTimeout(() => this.preload(b.large || b.thumb), 120);
      }, 650);
    },

    /** 位图就绪后真正上屏 */
    paintNext(it, next, hadPrev, prevSrc, dir, dx) {
      const src = next.src;
      this._shown = true;
      this.hideLoad();
      // 占位图直接换成清晰图：不再重放淡入，模糊层自己会退掉
      const wasPh = this.img.classList.contains("is-ph");
      this.img.classList.remove("is-ph");
      this.img.style.width = "";
      if (hadPrev) {
        this.slideTo(src, dir, dx, prevSrc);
      } else {
        this.img.src = src;
        if (!wasPh) {
          this.img.classList.remove("is-in");
          void this.img.offsetWidth;            // 强制重算，否则淡入会被合并掉
        }
        this.img.classList.add("is-in");
        this.slide = 0;
        this.measure();
        this.refreshRect();
        this.apply(false);
      }
      // 新图刚换上去时 clientWidth 还是旧的，下一帧再量一次
      requestAnimationFrame(() => { this.measure(); this.syncPct(); });
    },

    /** 滑动交接：旧画面交给 ghost 继续往手势方向滑出，新画面从另一侧滑入。
        dir=+1 看下一张（新图自右来），dir=-1 看上一张；dx 是手指已经拖出的位移。 */
    slideTo(newSrc, dir, dx, prevSrc) {
      const W = (this.stage.clientWidth || window.innerWidth) * 0.92;
      const outX = (dir >= 0 ? -1 : 1) * W;
      const g = this.ghost;

      clearTimeout(this._slideTimer);
      this.slideBusy = true;
      this._pendingFull = null;
      g.classList.remove("is-slide");
      g.src = prevSrc;
      g.hidden = false;
      g.style.transform = `translate3d(${dx}px, 0, 0)`;

      this.img.classList.remove("is-anim", "is-slide");
      this.img.src = newSrc;
      this.slide = -outX + dx;          // 新图摆到与手指连续的位置
      this.apply(false);
      this.img.classList.add("is-in");

      // 关键一步：强制样式重算。少了它，同一帧里"摆到起点 + 滑到 0"会被合并，
      // 于是命中缓存的图（往回翻最容易命中）直接瞬移 —— 就是那个反向切换的 bug。
      void this.img.offsetWidth;

      g.classList.add("is-slide");
      this.img.classList.add("is-slide");
      g.style.transform = `translate3d(${dx + outX}px, 0, 0)`;
      this.slide = 0;
      this.apply(false);

      requestAnimationFrame(() => this.measure());
      this._slideTimer = setTimeout(() => {
        g.hidden = true;
        g.removeAttribute("src");
        g.classList.remove("is-slide");
        this.img.classList.remove("is-slide");
        this.slideBusy = false;
        this.measure();
        this.refreshRect();
        if (this._pendingFull) {           // 滑完再把原图补上
          const src = this._pendingFull;
          this._pendingFull = null;
          this.img.src = src;
          requestAnimationFrame(() => { this.measure(); this.apply(false); });
        }
      }, 520);
    },

    /** 未放大时的回弹 / 收尾：把 slide 归零 */
    settleSlide(commitDir, dx) {
      const W = (this.stage.clientWidth || window.innerWidth) * 0.92;
      if (commitDir) { this.go(commitDir, dx); return; }
      this.img.classList.add("is-slide");
      this.slide = 0;
      this.apply(false);
      this.slideBusy = true;
      clearTimeout(this._slideTimer);
      this._slideTimer = setTimeout(() => {
        this.img.classList.remove("is-slide");
        this.slideBusy = false;
        if (this._pendingFull) {
          const src = this._pendingFull;
          this._pendingFull = null;
          this.img.src = src;
          requestAnimationFrame(() => { this.measure(); this.apply(false); });
        }
      }, 480);
    }
  };

  function esc(s) {
    return String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  }

  /* ---------------------------------------------------- 展牆 */
  function isShown(el) {
    for (let n = el; n && n !== document.documentElement; n = n.parentElement) {
      if (getComputedStyle(n).display === "none") return false;
    }
    return true;
  }

  function shotGroup(el) {
    const sec = el.closest(".grp, .block, section");
    if (!sec) return "";
    const h = $(".grp__name", sec) || $("h2", sec);
    return h ? h.textContent.trim() : "";
  }

  /** 灯箱的连续序列 = 页面上当前"看得见"的所有作品，按 DOM 顺序。
      这样左右切换会跨子主题连着走；筛成一组时又自然退回只在这一组里转。 */
  function shotSequence() {
    const shots = $$(".shot").filter(isShown);
    return { items: shots.map(s => s.__item), groups: shots.map(shotGroup) };
  }

  function wall(el, items, cfg) {
    const frag = document.createDocumentFragment();
    items.forEach((it, i) => {
      const d = document.createElement("div");
      d.className = "shot";
      d.__item = it;
      d.innerHTML = `
        <img src="${it.thumb}" alt="${esc(it.title || "")}" loading="lazy" decoding="async">
        <div class="shot__cap">
          <div><b>${esc(it.title || "")}</b><small>${esc(it.sub || it.file || "")}</small></div>
          ${it.badge ? `<span class="shot__tag">${esc(it.badge)}</span>` : ""}
        </div>`;
      const img = $("img", d);
      const done = () => { img.classList.add("is-in"); d.classList.add("is-loaded"); };
      img.addEventListener("load", done, { once: true });
      img.addEventListener("error", done, { once: true });
      if (img.complete) done();
      d.addEventListener("click", () => {
        const seq = shotSequence();
        const idx = Math.max(0, seq.items.indexOf(it));
        LB.open(seq.items, idx, cfg, seq.groups);
      });
      frag.appendChild(d);
    });
    el.appendChild(frag);
    // 兜底：任何情况下 2.5s 后都让图片显形，避免加载事件丢失导致空白
    setTimeout(() => {
      $$(".shot", el).forEach(d => {
        const im = $("img", d);
        if (im) im.classList.add("is-in");
        d.classList.add("is-loaded");
      });
    }, 2500);
  }

  /* ---------------------------------------------------- 篩選 */
  function filters(nav, wallEl) {
    if (!nav) return;
    const btns = $$("button", nav);
    btns.forEach(b => b.addEventListener("click", () => {
      btns.forEach(x => x.classList.toggle("is-on", x === b));
      const g = b.dataset.g;
      $$(".shot", wallEl).forEach(s => {
        s.style.display = (g === "*" || s.dataset.group === g) ? "" : "none";
      });
    }));
  }

  /** 筛选后如果当前滚动位置已经越过第一个可见分组，把它拉回视野 */
  function jumpToFirstVisible(root) {
    const first = Array.from(root.children).find(el => el.style.display !== "none");
    if (!first) return;
    const top = first.getBoundingClientRect().top;
    if (top < 70) {
      const y = window.scrollY + top - 78;
      window.scrollTo({ top: y, behavior: "smooth" });
    }
  }

  window.Site = { $, $$, esc, chrome, reveals, wall, filters, LB, jumpToFirstVisible };
  document.addEventListener("DOMContentLoaded", () => { chrome(); reveals(); });
})();
