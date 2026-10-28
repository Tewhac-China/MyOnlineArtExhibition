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
    s: 1, tx: 0, ty: 0, MAX: 16,
    slide: 0, sliding: false, slideBusy: false, _slideTimer: null, ghost: null, _pendingFull: null,
    pointers: new Map(), dragBase: null, pinch: null, moved: 0,
    base: { w: 1, h: 1 }, lastTap: 0, _token: 0, _fullSrc: null, _fullReady: false, _shown: false,
    _cache: new Map(), _cacheMax: 12,

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
          </div>
          <button class="lb__nav next" aria-label="下一张">›</button>
          <div class="lb__tools">
            <button data-act="out" aria-label="缩小" title="缩小（-）">−</button>
            <button class="pct" data-act="reset" title="适应窗口（0）">100%</button>
            <button data-act="in" aria-label="放大" title="放大（+）">＋</button>
            <span class="lb__sep"></span>
            <button data-act="fit" aria-label="适应窗口" title="适应窗口">⤢</button>
            <button data-act="one" aria-label="原始大小" title="1:1 原始像素">1:1</button>
          </div>
          <div class="lb__hint">滚轮 / 双指缩放 · 拖动平移 · 双击放大</div>
        </div>
        <aside class="lb__info"></aside>`;
      document.body.appendChild(root);

      this.root = root;
      this.stage = $(".lb__stage", root);
      this.img = $(".lb__img", root);
      this.ghost = $(".lb__ghost", root);
      this.info = $(".lb__info", root);

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
        });
      });

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
      });
      window.addEventListener("resize", () => {
        if (!root.classList.contains("is-open")) return;
        this.refreshRect();
        this.reset();
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
            else this.zoomTo(2.5, e.clientX, e.clientY, true);
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
        else this.zoomTo(2.5, e.clientX, e.clientY, true);
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
    },

    /** 以屏幕坐标 (cx, cy) 为锚点缩放到 target */
    zoomTo(target, cx, cy, anim) {
      this.measure();
      const s2 = clamp(target, 1, this.MAX);
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
      this.measure();
      const it = this.items[this.idx] || {};
      const nat = it.fw || it.w || this.img.naturalWidth || this.base.w;
      this.s = 1; this.tx = 0; this.ty = 0;
      this.zoomTo(clamp(nat / this.base.w, 1, this.MAX),
                 this._rl + this._rw / 2, this._rt + this._rh / 2, true);
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

    apply(anim) {
      this.clampPan();
      const im = this.img;
      // 滑动切换期间由 .is-slide 驱动 transform，不能再挂 .is-anim（两者抢同一个属性）
      im.classList.toggle("is-anim", !!anim && !this.slide);
      im.style.transform = `translate3d(${this.tx + this.slide}px, ${this.ty}px, 0) scale(${this.s})`;
      this.stage.classList.toggle("is-zoomed", this.s > 1.001);
      const p = Math.round(this.s * 100);
      if (p !== this._pct) {
        this._pct = p;
        const pct = $(".pct", this.root);
        if (pct) pct.textContent = p + "%";
      }
      if (anim) {
        clearTimeout(this._t);
        this._t = setTimeout(() => im.classList.remove("is-anim"), 240);
      }
    },

    setRes(text, state) {
      const el = $(".lb__res", this.root);
      if (!el) return;
      el.textContent = text;
      el.dataset.state = state || "";
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
      const g = this.ghost;
      if (g) { g.hidden = true; g.removeAttribute("src"); g.classList.remove("is-slide"); }
      this.img.classList.remove("is-in", "is-slide", "is-quick", "is-anim");
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
      this.ghost.hidden = true;
      this.ghost.removeAttribute("src");
      this.ghost.classList.remove("is-slide");
      this.img.classList.remove("is-slide");
      this.s = 1; this.tx = 0; this.ty = 0;
      this.img.style.transform = "";
      const pct0 = $(".pct", this.root);
      if (pct0) pct0.textContent = "100%";
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
      const pct0 = $(".pct", this.root);
      if (pct0) pct0.textContent = "100%";

      // 已有画面在位时才做滑动交接；首次打开仍是从容淡入
      const prevSrc = this.img.getAttribute("src") || "";
      const hadPrev = !!prevSrc && this.img.classList.contains("is-in");

      const token = ++this._token;
      const mode = dx ? "slide" : this.navMode();
      const largeSrc = it.large || it.thumb;
      const fullSrc = it.full && it.full !== it.large ? it.full : null;
      this._fullSrc = fullSrc;
      this._fullReady = false;
      this._shown = false;

      this.img.alt = it.title || "";
      const hit = this._cache.get(largeSrc);
      if (hit && hit.ready) {
        // 已预取并解码：直接同步上屏，点击即切换
        if (mode === "cut") this.cutTo(largeSrc);
        else if (mode === "quick") this.quickTo(largeSrc, dir);
        else this.paintNext(it, { src: largeSrc }, hadPrev, prevSrc, dir, dx);
        this.preloadNeighbors(i);
      } else {
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
      next.onerror = () => { /* 载入失败保持当前画面，不白屏 */ };
      next.src = largeSrc;
      this.img.alt = it.title || "";
      this.preloadNeighbors(i);
      }

      // 原图（原始分辨率）随后接管，保证大图展示时是最清晰的版本
      const resText = fullSrc ? "载入原图…" : `原图 · ${it.fw || it.w} × ${it.fh || it.h}`;
      const resState = fullSrc ? "loading" : "ready";
      if (fullSrc) {
        const big = new Image();
        big.onload = () => {
          if (token !== this._token) return;
          this._fullReady = true;
          this.setRes(`原图 · ${big.naturalWidth} × ${big.naturalHeight}`, "ready");
          // 画面已经铺开就地替换；还没铺开就等 next.onload 直接用原图
          if (!this._shown) return;
          if (this.slideBusy) { this._pendingFull = big.src; return; }
          this.img.src = big.src;
          requestAnimationFrame(() => { this.measure(); this.apply(false); });
        };
        big.onerror = () => { if (token === this._token) this.setRes("原图载入失败", "error"); };
        big.src = fullSrc;
      }

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
      this.img.classList.remove("is-slide", "is-anim");
      this.slide = 0;
      this.img.src = src;
      this._shown = true;
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

      this.img.classList.remove("is-anim", "is-slide", "is-quick");
      this.img.src = src;
      this._shown = true;
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

    /** 预取前后各一张（下一张优先，上一张次之） */
    preloadNeighbors(i) {
      const n = this.items.length;
      if (n < 2) return;
      const at = k => this.items[(k + n) % n];
      const a = at(i + 1), b = at(i - 1);
      this.preload(a.large || a.thumb);
      setTimeout(() => this.preload(b.large || b.thumb), 60);
    },

    /** 位图就绪后真正上屏：原图若先到就直接上原图，否则先上快图再替换 */
    paintNext(it, next, hadPrev, prevSrc, dir, dx) {
      const src = this._fullReady && this._fullSrc ? this._fullSrc : next.src;
      this._shown = true;
      if (hadPrev) {
        this.slideTo(src, dir, dx, prevSrc);
      } else {
        this.img.src = src;
        this.img.classList.remove("is-in");
        void this.img.offsetWidth;            // 强制重算，否则淡入会被合并掉
        this.img.classList.add("is-in");
        this.slide = 0;
        this.measure();
        this.refreshRect();
        this.apply(false);
      }
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
