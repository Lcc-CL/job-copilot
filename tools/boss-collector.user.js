// ==UserScript==
// @name         Job-Copilot Boss采集器
// @namespace    job-copilot
// @version      1.3
// @description  你正常浏览 Boss直聘 搜索页，脚本把页面自己加载的职位数据存到本地。不驱动浏览器、不破解反爬——采集的就是你本人正常看到的公开职位。
// @author       job-copilot
// @match        *://www.zhipin.com/*
// @run-at       document-start
// @grant        none
// ==/UserScript==

(function () {
  'use strict';
  console.log('[JC] Boss采集器 v1.3 已加载');

  // ---- 内存累积：按职位ID去重，跨翻页累加，最后一次性导出 ----
  const store = new Map(); // key: encryptJobId, value: 原始job对象(+采集上下文)

  function currentContext() {
    // 从当前页面地址解析本次搜索的关键词与城市码，随职位一起留档
    const qs = new URLSearchParams(location.search);
    return {
      _kw: qs.get('query') || '',
      _cityCode: qs.get('city') || '',
    };
  }

  // 判断一个数组是不是"职位列表"：元素是对象且带 Boss 职位的标志字段
  function isJobArray(arr) {
    if (!Array.isArray(arr) || arr.length === 0) return false;
    const s = arr[0];
    return s && typeof s === 'object' &&
      (s.encryptJobId || s.jobName || (s.jobId && (s.brandName || s.salaryDesc)));
  }

  // 深扫任意 JSON，找出第一个"职位列表"数组（对接口改名/字段路径变化免疫）
  function findJobArray(node, depth) {
    if (depth > 6 || node == null || typeof node !== 'object') return null;
    if (isJobArray(node)) return node;
    for (const k in node) {
      try {
        const v = node[k];
        if (v && typeof v === 'object') {
          const hit = findJobArray(v, depth + 1);
          if (hit) return hit;
        }
      } catch (e) { /* getter 抛错等，跳过 */ }
    }
    return null;
  }

  function ingest(payload, url) {
    try {
      const jobs = findJobArray(payload, 0);
      if (!jobs) return;
      const ctx = currentContext();
      let added = 0;
      for (const j of jobs) {
        const id = j.encryptJobId || j.jobId || j.jobIdCry;
        if (!id) continue;
        if (!store.has(String(id))) added++;
        store.set(String(id), Object.assign({}, j, ctx));
      }
      if (added > 0) updateBadge();
    } catch (e) { /* 静默：非目标响应 */ }
  }

  function maybeJson(contentType) {
    return typeof contentType === 'string' && contentType.indexOf('json') !== -1;
  }

  // ---- 钩 fetch：按响应形状识别，不依赖接口名 ----
  try {
    const _fetch = window.fetch;
    window.fetch = function (...args) {
      const url = (args[0] && args[0].url) || args[0];
      return _fetch.apply(this, args).then((resp) => {
        try {
          if (maybeJson(resp.headers.get('content-type'))) {
            resp.clone().json().then((p) => ingest(p, url)).catch(() => {});
          }
        } catch (e) {}
        return resp;
      });
    };
  } catch (e) { console.log('[JC] fetch 钩挂载失败', e); }

  // ---- 钩 XHR：按响应形状识别 ----
  try {
    const _open = XMLHttpRequest.prototype.open;
    const _send = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function (method, url) {
      this.__jc_url = url;
      return _open.apply(this, arguments);
    };
    XMLHttpRequest.prototype.send = function () {
      const self = this;
      this.addEventListener('load', function () {
        try {
          const ct = self.getResponseHeader && self.getResponseHeader('content-type');
          const txt = self.responseText;
          if (txt && (maybeJson(ct) || txt.charAt(0) === '{')) {
            ingest(JSON.parse(txt), self.__jc_url);
          }
        } catch (e) {}
      });
      return _send.apply(this, arguments);
    };
  } catch (e) { console.log('[JC] XHR 钩挂载失败', e); }

  // ---- 悬浮控制条 ----
  const BADGE_ID = 'jc-badge-root';
  let badge;

  // 用 createElement 逐个建 DOM，不碰 innerHTML —— 绕开 Boss 页面可能启用的
  // Trusted Types CSP（该策略会让字符串赋值给 innerHTML 直接抛错，导致 UI 建不出来）
  function styleOf(el, css) { el.style.cssText = css; return el; }

  function buildUI() {
    try {
      if (!document.body) return;                       // body 还没就绪，等下一轮
      if (document.getElementById(BADGE_ID)) return;    // 已存在，别重复建

      badge = styleOf(document.createElement('div'), [
        'position:fixed', 'right:16px', 'bottom:16px', 'z-index:2147483647',
        'background:#00bebd', 'color:#fff', 'font:13px/1.4 -apple-system,sans-serif',
        'padding:10px 12px', 'border-radius:10px', 'box-shadow:0 4px 16px rgba(0,0,0,.25)',
        'user-select:none',
      ].join(';'));
      badge.id = BADGE_ID;

      const count = styleOf(document.createElement('div'), 'font-weight:600;margin-bottom:6px');
      count.id = 'jc-count';
      count.textContent = '已抓 0 个职位';

      const exportBtn = styleOf(document.createElement('button'),
        'cursor:pointer;border:0;border-radius:6px;padding:5px 10px;margin-right:6px;background:#fff;color:#00807f;font-weight:600');
      exportBtn.textContent = '导出JSON';
      exportBtn.onclick = exportJson;

      const clearBtn = styleOf(document.createElement('button'),
        'cursor:pointer;border:0;border-radius:6px;padding:5px 10px;background:rgba(255,255,255,.25);color:#fff');
      clearBtn.textContent = '清空';
      clearBtn.onclick = () => { store.clear(); updateBadge(); };

      badge.appendChild(count);
      badge.appendChild(exportBtn);
      badge.appendChild(clearBtn);
      document.body.appendChild(badge);
      updateBadge();
      console.log('[JC] 悬浮条已挂载');
    } catch (e) {
      console.log('[JC] 建悬浮条失败：', e);
    }
  }

  function updateBadge() {
    const el = document.getElementById('jc-count');
    if (el) el.textContent = '已抓 ' + store.size + ' 个职位';
  }

  // 定时自愈：不论页面何时就绪、SPA 何时重绘掉，都能把悬浮条挂回去
  setInterval(buildUI, 1000);

  function exportJson() {
    if (store.size === 0) { alert('还没抓到职位，先在搜索页翻几页再导出。'); return; }
    const arr = Array.from(store.values());
    const blob = new Blob([JSON.stringify(arr, null, 0)], { type: 'application/json' });
    const a = document.createElement('a');
    const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
    a.href = URL.createObjectURL(blob);
    a.download = 'boss-jobs-' + ts + '.json';
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  }

  buildUI();
  document.addEventListener('DOMContentLoaded', buildUI);
})();
