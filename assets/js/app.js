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
    const io = new IntersectionObserver(entries => {
      entries.forEach(e => {
        if (e.isIntersecting) { e.target.classList.add("is-in"); io.unobserve(e.target); }
      });
    }, { rootMargin: "0px 0px -8% 0px", threshold: 0.06 });
    els.forEach(el => io.observe(el));
  }

  /* ---------------------------------------------------- 燈箱 · 圖片查看器 */
  const LB = {
    root: null, stage: null, img: null, info: null,
    items: [], idx: 0, cfg: null,
    s: 1, tx: 0, ty: 0, MAX: 16,
    pointers: new Map(), dragBase: null, pinch: null, moved: 0,
    base: { w: 1, h: 1 }, lastTap: 0, _token: 0,

    init() {
      if (this.root) return;
      const root = document.createElement("div");
      root.className = "lb";
      root.innerHTML = `
        <button class="lb__close" aria-label="关闭">✕</button>
        <button class="lb__info-btn" aria-label="信息面板">ⓘ</button>
        <div class="lb__stage">
          <button class="lb__nav prev" aria-label="上一张">‹</button>
          <img alt="" draggable="false">
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
      this.img = $("img", root);
      this.info = $(".lb__info", root);

      $(".lb__close", root).addEventListener("click", () => this.close());
      $(".lb__info-btn", root).addEventListener("click", () => root.classList.toggle("info-off"));
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
      window.addEventListener("resize", () => { if (root.classList.contains("is-open")) this.reset(); });
    },

    /* ---------------- 指针：拖动 + 双指捏合 ---------------- */
    bindPointer() {
      const st = this.stage;
      st.addEventListener("pointerdown", e => {
        if (e.target.closest("button")) return;
        st.setPointerCapture(e.pointerId);
        this.pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
        this.moved = 0;
        if (this.pointers.size === 1) {
          this.dragBase = { x: e.clientX, y: e.clientY, tx: this.tx, ty: this.ty };
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
        }
      });

      const end = e => {
        const wasSingle = this.pointers.size === 1;
        this.pointers.delete(e.pointerId);
        if (this.pointers.size < 2) this.pinch = null;
        if (this.pointers.size === 0) {
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
      const r = this.stage.getBoundingClientRect();
      const ox = cx == null ? 0 : cx - (r.left + r.width / 2);
      const oy = cy == null ? 0 : cy - (r.top + r.height / 2);
      const k = s2 / this.s;
      this.tx = ox - (ox - this.tx) * k;
      this.ty = oy - (oy - this.ty) * k;
      this.s = s2;
      if (this.s <= 1.001) { this.s = 1; this.tx = 0; this.ty = 0; }
      this.apply(anim);
    },

    zoomBy(f) {
      const r = this.stage.getBoundingClientRect();
      this.zoomTo(this.s * f, r.left + r.width / 2, r.top + r.height / 2, true);
    },

    reset() {
      this.s = 1; this.tx = 0; this.ty = 0;
      this.apply(true);
    },

    actualSize() {
      this.measure();
      const it = this.items[this.idx] || {};
      const nat = it.fw || it.w || this.img.naturalWidth || this.base.w;
      const r = this.stage.getBoundingClientRect();
      this.s = 1; this.tx = 0; this.ty = 0;
      this.zoomTo(clamp(nat / this.base.w, 1, this.MAX), r.left + r.width / 2, r.top + r.height / 2, true);
    },

    clampPan() {
      const r = this.stage.getBoundingClientRect();
      const mx = Math.max(0, (this.base.w * this.s - r.width) / 2) + 24;
      const my = Math.max(0, (this.base.h * this.s - r.height) / 2) + 24;
      this.tx = clamp(this.tx, -mx, mx);
      this.ty = clamp(this.ty, -my, my);
    },

    apply(anim) {
      this.clampPan();
      const im = this.img;
      im.classList.toggle("is-anim", !!anim);
      im.style.transform = `translate3d(${this.tx}px, ${this.ty}px, 0) scale(${this.s})`;
      this.stage.classList.toggle("is-zoomed", this.s > 1.001);
      const pct = $(".pct", this.root);
      if (pct) pct.textContent = Math.round(this.s * 100) + "%";
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
    open(items, i, cfg) {
      this.init();
      this.items = items; this.cfg = cfg || {};
      this.root.classList.add("is-open");
      document.documentElement.style.overflow = "hidden";
      this.show(i);
    },
    close() {
      this.root.classList.remove("is-open");
      document.documentElement.style.overflow = "";
      this.s = 1; this.tx = 0; this.ty = 0;
      this.img.style.transform = "";
      const pct0 = $(".pct", this.root);
      if (pct0) pct0.textContent = "100%";
    },
    go(d) {
      const n = this.items.length;
      this.show((this.idx + d + n) % n);
    },
    show(i) {
      this.idx = i;
      const it = this.items[i];
      const cfg = this.cfg;
      this.s = 1; this.tx = 0; this.ty = 0;
      this.img.style.transform = "";
      const pct0 = $(".pct", this.root);
      if (pct0) pct0.textContent = "100%";

      this.img.classList.remove("is-in");
      const next = new Image();
      next.onload = () => {
        this.img.src = next.src;
        requestAnimationFrame(() => {
          this.img.classList.add("is-in");
          this.measure();
          this.apply(false);
        });
      };
      next.src = it.large || it.thumb;
      this.img.alt = it.title || "";

      // 原图（原始分辨率）随后接管，保证大图展示时是最清晰的版本
      const fullSrc = it.full && it.full !== it.large ? it.full : null;
      const token = ++this._token;
      if (fullSrc) {
        this.setRes("载入原图…", "loading");
        const big = new Image();
        big.onload = () => {
          if (token !== this._token) return;
          this.img.src = big.src;
          this.setRes(`原图 · ${big.naturalWidth} × ${big.naturalHeight}`, "ready");
          requestAnimationFrame(() => { this.measure(); this.apply(false); });
        };
        big.onerror = () => { if (token === this._token) this.setRes("原图载入失败", "error"); };
        big.src = fullSrc;
      } else {
        this.setRes(`原图 · ${it.fw || it.w} × ${it.fh || it.h}`, "ready");
      }

      const rows = (cfg.rows ? cfg.rows(it) : []).filter(r => r && r[1] != null && r[1] !== "");
      const prompt = cfg.prompt ? cfg.prompt(it) : null;
      this.info.innerHTML = `
        <div class="lb__no">${String(i + 1).padStart(2, "0")} / ${String(this.items.length).padStart(2, "0")}</div>
        <h3 class="lb__title">${esc(it.title || "")}</h3>
        <div class="lb__file">${esc(it.file || "")}</div>
        <div class="lb__res" data-state="loading">载入原图…</div>
        <dl class="lb__rows">
          ${rows.map(([k, v]) => `<div class="lb__row"><dt>${esc(k)}</dt><dd>${esc(String(v))}</dd></div>`).join("")}
        </dl>
        ${prompt ? `<div class="lb__prompt-h"><span>原始提示词</span><span>${prompt.length} 字符</span></div>
        <pre class="lb__prompt">${esc(prompt)}</pre>` : ""}`;
      this.info.scrollTop = 0;
    }
  };

  function esc(s) {
    return String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  }

  /* ---------------------------------------------------- 展牆 */
  function wall(el, items, cfg) {
    const frag = document.createDocumentFragment();
    items.forEach((it, i) => {
      const d = document.createElement("div");
      d.className = "shot";
      d.innerHTML = `
        <img src="${it.thumb}" alt="${esc(it.title || "")}" loading="lazy" decoding="async">
        <div class="shot__cap">
          <div><b>${esc(it.title || "")}</b><small>${esc(it.sub || it.file || "")}</small></div>
          ${it.badge ? `<span class="shot__tag">${esc(it.badge)}</span>` : ""}
        </div>`;
      const img = $("img", d);
      img.addEventListener("load", () => img.classList.add("is-in"), { once: true });
      img.addEventListener("error", () => img.classList.add("is-in"), { once: true });
      if (img.complete) img.classList.add("is-in");
      d.addEventListener("click", () => LB.open(items, i, cfg));
      frag.appendChild(d);
    });
    el.appendChild(frag);
    // 兜底：任何情况下 2.5s 后都让图片显形，避免加载事件丢失导致空白
    setTimeout(() => {
      $$(".shot img", el).forEach(im => im.classList.add("is-in"));
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

  window.Site = { $, $$, esc, chrome, reveals, wall, filters, LB };
  document.addEventListener("DOMContentLoaded", () => { chrome(); reveals(); });
})();
