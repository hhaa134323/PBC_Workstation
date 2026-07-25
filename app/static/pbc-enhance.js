/* ============================================================
   PBC 前端增强模块
   独立文件，运行时挂钩接入现有 Alpine 应用，不改 index.html 逻辑
   ------------------------------------------------------------
   模块一：今日简报收起
   打开先完整看一屏，点进任意页签自动收成一条细摘要，随时可以再点开
   ============================================================ */
(function () {
  'use strict';

  var ICO_DOWN = '<svg viewBox="0 0 24 24"><path d="M18 15l-6-6-6 6"/></svg>';
  var ICO_UP   = '<svg viewBox="0 0 24 24"><path d="M6 9l6 6 6-6"/></svg>';

  var card = null;   // 今日简报大卡片
  var bar = null;    // 收起后的细摘要
  var folded = false;

  /* ---------- 定位今日简报卡片 ---------- */
  function findCard() {
    var list = document.querySelectorAll('main.wrap > div');
    for (var i = 0; i < list.length; i++) {
      if ((list[i].textContent || '').indexOf('今日简报') >= 0) return list[i];
    }
    return null;
  }

  /* 卡片本身是否该显示（Alpine 在没数据时会把它 display:none） */
  function hasData() {
    if (!card) return false;
    if (card.style.display === 'none') return false;
    return card.querySelectorAll('.brief-item').length > 0;
  }

  /* ---------- 统计条数 ---------- */
  function counts() {
    var items = card ? card.querySelectorAll('.brief-item') : [];
    var high = 0;
    for (var i = 0; i < items.length; i++) {
      if (items[i].classList.contains('high')) high++;
    }
    return { total: items.length, high: high };
  }

  /* ---------- 创建细摘要 ---------- */
  function makeBar() {
    if (bar) return;
    bar = document.createElement('div');
    bar.className = 'pbcg-brief-bar';
    bar.style.display = 'none';
    bar.addEventListener('click', function () { setFold(false); });
    card.parentNode.insertBefore(bar, card);
  }

  function paintBar() {
    if (!bar) return;
    var c = counts();
    var calm = c.high === 0;
    bar.innerHTML =
      '<span class="pbcg-bb-dot' + (calm ? ' calm' : '') + '"></span>' +
      '<span class="pbcg-bb-name">今日简报</span>' +
      '<span class="pbcg-bb-txt">已识别 <b>' + c.total + '</b> 条风险信号' +
        (c.high ? '，其中最高优 <b>' + c.high + '</b> 条' : '，暂无最高优') +
      '</span>' +
      '<span class="pbcg-bb-act">展开' + ICO_DOWN + '</span>';
  }

  /* ---------- 展开卡片右上角的收起按钮 ---------- */
  function addFoldBtn() {
    if (!card || card.querySelector('.pbcg-brief-fold')) return;
    var head = card.firstElementChild;
    if (!head) return;
    var b = document.createElement('button');
    b.type = 'button';
    b.className = 'pbcg-brief-fold';
    b.innerHTML = ICO_UP + '收起';
    b.addEventListener('click', function (e) {
      e.stopPropagation();
      setFold(true);
    });
    head.appendChild(b);
  }

  /* ---------- 切换展开收起 ---------- */
  function setFold(on) {
    if (!card) return;
    folded = on;
    if (on) {
      card.classList.add('pbcg-brief-off');
      makeBar();
      paintBar();
      bar.style.display = hasData() ? 'flex' : 'none';
    } else {
      card.classList.remove('pbcg-brief-off');
      if (bar) bar.style.display = 'none';
    }
  }

  /* ---------- 跟 Alpine 的显隐保持同步 ---------- */
  function sync() {
    if (!card || !folded || !bar) return;
    paintBar();
    bar.style.display = hasData() ? 'flex' : 'none';
  }

  function watchCard() {
    var mo = new MutationObserver(function () { sync(); });
    mo.observe(card, { attributes: true, attributeFilter: ['style'], childList: true, subtree: true });
  }

  /* ---------- 点页签就收起 ---------- */
  function watchTabs() {
    document.addEventListener('click', function (e) {
      var tab = e.target.closest ? e.target.closest('nav.tabs .tab') : null;
      if (!tab) return;
      if (folded) return;
      setTimeout(function () { setFold(true); }, 120);
    });
  }

  /* ---------- 启动 ---------- */
  function boot() {
    var tries = 0;
    var timer = setInterval(function () {
      tries++;
      var found = findCard();
      if (found) {
        clearInterval(timer);
        card = found;
        addFoldBtn();
        makeBar();
        watchCard();
        watchTabs();
      } else if (tries > 80) {
        clearInterval(timer);
      }
    }, 250);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();

/* ============================================================
   模块二：顶栏按钮统一
   重排顺序：文件变更 导出清单 生成汇报 分隔线 刷新 设置 AI 配置
   文件变更从实心黄降为浅黄底加黄描边
   只动 class 和节点位置，不碰任何 Alpine 绑定
   ============================================================ */
(function () {
  'use strict';

  function pick(nav) {
    var out = {};
    var list = nav.children;
    for (var i = 0; i < list.length; i++) {
      var el = list[i];
      if (el.tagName !== 'BUTTON') continue;
      var t = (el.textContent || '').replace(/\s+/g, '');
      if (t.indexOf('文件变更') >= 0) out.change = el;
      else if (t.indexOf('导出清单') >= 0) out.exp = el;
      else if (t.indexOf('生成汇报') >= 0) out.report = el;
      else if (t.indexOf('刷新') >= 0) out.reload = el;
      else if (t.indexOf('设置') >= 0) out.setting = el;
      else if (t.indexOf('AI') >= 0) out.ai = el;
    }
    return out;
  }

  function tidy() {
    var nav = document.querySelector('.nav-top');
    if (!nav || nav.classList.contains('pbcg-nav-tidy')) return !!nav;

    var b = pick(nav);
    if (!b.change || !b.reload) return false;

    var line = document.createElement('span');
    line.className = 'pbcg-nav-div';

    // 按新顺序重新挂到末尾，项目、品牌、进度条位置不变
    var order = [b.change, b.exp, b.report, line, b.reload, b.setting, b.ai];
    for (var i = 0; i < order.length; i++) {
      if (order[i]) nav.appendChild(order[i]);
    }

    // 文件变更降一档
    b.change.classList.remove('btn-pri');
    b.change.classList.add('pbcg-nav-chg');

    nav.classList.add('pbcg-nav-tidy');
    return true;
  }

  function boot() {
    var tries = 0;
    var timer = setInterval(function () {
      tries++;
      if (tidy() || tries > 80) clearInterval(timer);
    }, 250);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
