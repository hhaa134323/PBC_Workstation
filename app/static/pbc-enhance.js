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
  var folded = true; // 默认收起
  var currentPid = ''; // 当前项目ID（用于 localStorage key）

  /* ---------- localStorage 持久化（per project） ---------- */
  function getPid() {
    var el = document.querySelector('[x-data]');
    if (el && el._x_dataStack && el._x_dataStack[0]) {
      return el._x_dataStack[0].currentProjectId || '';
    }
    if (window.Alpine && window.Alpine.$data) {
      try { return window.Alpine.$data(el).currentProjectId || ''; } catch (e) {}
    }
    return '';
  }

  function loadFoldState() {
    var pid = getPid();
    if (!pid) return true; // 默认收起
    var key = 'pbc_brief_folded_' + pid;
    try {
      var v = localStorage.getItem(key);
      return v === null ? true : v === '1'; // 默认收起
    } catch (e) { return true; }
  }

  function saveFoldState(folded) {
    var pid = getPid();
    if (!pid) return;
    var key = 'pbc_brief_folded_' + pid;
    try { localStorage.setItem(key, folded ? '1' : '0'); } catch (e) {}
  }

  /* ---------- 上次查看时间（per project） ---------- */
  function getLastSeen() {
    var pid = getPid();
    if (!pid) return 0;
    try {
      var v = localStorage.getItem('pbc_brief_seen_' + pid);
      return v ? parseFloat(v) : 0;
    } catch (e) { return 0; }
  }

  function saveLastSeen(ts) {
    var pid = getPid();
    if (!pid) return;
    try { localStorage.setItem('pbc_brief_seen_' + pid, String(ts)); } catch (e) {}
  }

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function root() {
    var el = document.querySelector('[x-data]');
    if (!el) return null;
    if (el._x_dataStack && el._x_dataStack[0]) return el._x_dataStack[0];
    if (window.Alpine && window.Alpine.$data) {
      try { return window.Alpine.$data(el); } catch (e) {}
    }
    return null;
  }

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
    // 从 Alpine data 读 PBC 清单的真实未提供数（不数简报卡片里的条目）
    var d = root();
    var total = 0;
    var high = 0;
    if (d && d.pbcList) {
      for (var i = 0; i < d.pbcList.length; i++) {
        var st = d.pbcList[i].status_normalized || d.pbcList[i].status || '';
        if (st === '未提供') {
          total++;
          var od = d.pbcList[i].overdue_days || 0;
          if (od > 30) high++;
        }
      }
    }
    // fallback: 如果拿不到 pbcList，数简报卡片
    if (total === 0) {
      var items = card ? card.querySelectorAll('.brief-item') : [];
      for (var j = 0; j < items.length; j++) {
        if (items[j].classList.contains('high')) high++;
      }
      total = items.length;
    }
    return { total: total, high: high };
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

    // 检查是否有新变化（自上次查看以来）
    var lastSeen = getLastSeen();
    var now = Date.now() / 1000;
    var hasNewChanges = false;
    var newCount = 0;

    // 从 Alpine data 拿 changePanel 数据判断是否有新变化
    var d = root();
    if (d && d.changePanel && d.changePanel.items) {
      var items = d.changePanel.items;
      for (var i = 0; i < items.length; i++) {
        var ts = items[i].changed_at || '';
        if (ts) {
          var tsDate = new Date(String(ts).replace(' ', 'T'));
          if (!isNaN(tsDate.getTime())) {
            var tsSec = tsDate.getTime() / 1000;
            if (tsSec > lastSeen) {
              hasNewChanges = true;
              newCount++;
            }
          }
        }
      }
    }

    // 上次查看时间格式化
    var seenStr = '';
    if (lastSeen > 0) {
      var diff = now - lastSeen;
      if (diff < 3600) seenStr = Math.floor(diff / 60) + ' 分钟前';
      else if (diff < 86400) seenStr = Math.floor(diff / 3600) + ' 小时前';
      else seenStr = Math.floor(diff / 86400) + ' 天前';
    }

    if (hasNewChanges) {
      // 有新变化：黄色边框 + 增量提示
      bar.className = 'pbcg-brief-bar alert';
      bar.innerHTML =
        '<span class="pbcg-bb-dot"></span>' +
        '<span class="pbcg-bb-name">今日简报</span>' +
        '<span class="pbcg-bb-txt">新增 <b>' + newCount + '</b> 条变化，待查看</span>' +
        (seenStr ? '<span class="pbcg-bb-meta">上次查看 ' + esc(seenStr) + '</span>' : '') +
        '<span class="pbcg-bb-act">展开' + ICO_DOWN + '</span>';
    } else {
      // 无新变化：平时态
      bar.className = 'pbcg-brief-bar';
      bar.innerHTML =
        '<span class="pbcg-bb-dot calm"></span>' +
        '<span class="pbcg-bb-name">今日简报</span>' +
        '<span class="pbcg-bb-txt">无新变化。存量未提供 <b>' + c.total + '</b> 项，详情看下方表格</span>' +
        (seenStr ? '<span class="pbcg-bb-meta">上次查看 ' + esc(seenStr) + '</span>' : '') +
        '<span class="pbcg-bb-act">展开' + ICO_DOWN + '</span>';
    }
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
    saveFoldState(folded);
    if (on) {
      card.classList.add('pbcg-brief-off');
      makeBar();
      paintBar();
      bar.style.display = hasData() ? 'flex' : 'none';
    } else {
      card.classList.remove('pbcg-brief-off');
      if (bar) bar.style.display = 'none';
      // 展开时记录查看时间
      saveLastSeen(Date.now() / 1000);
    }
  }

  /* ---------- 跟 Alpine 的显隐保持同步 ---------- */
  function sync() {
    if (!card || !bar) return;
    paintBar();
    // 检测是否有新变化→自动展开一次
    if (folded && hasData()) {
      var lastSeen = getLastSeen();
      var d = root();
      if (d && d.changePanel && d.changePanel.items) {
        var hasNew = false;
        var items = d.changePanel.items;
        for (var i = 0; i < items.length; i++) {
          var ts = items[i].changed_at || '';
          if (ts) {
            var tsDate = new Date(String(ts).replace(' ', 'T'));
            if (!isNaN(tsDate.getTime()) && tsDate.getTime() / 1000 > lastSeen) {
              hasNew = true;
              break;
            }
          }
        }
        if (hasNew) {
          // 有新变化→自动展开
          setFold(false);
          return;
        }
      }
    }
    bar.style.display = folded && hasData() ? 'flex' : 'none';
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
        // 读 localStorage 恢复折叠状态（默认收起）
        folded = loadFoldState();
        if (folded) {
          setFold(true);
        } else {
          // 展开时记录查看时间
          saveLastSeen(Date.now() / 1000);
        }
        watchCard();
        watchTabs();
        // 监听项目切换
        var oldPid = '';
        setInterval(function() {
          var newPid = getPid();
          if (newPid && newPid !== oldPid) {
            oldPid = newPid;
            folded = loadFoldState();
            if (folded) setFold(true);
          }
        }, 1000);
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
      if (t.indexOf('变更记录') >= 0 || t.indexOf('文件变更') >= 0) out.change = el;
      else if (t.indexOf('导出清单') >= 0) out.exp = el;
      else if (t.indexOf('生成汇报') >= 0) out.report = el;
      else if (t.indexOf('刷新') >= 0) out.reload = el;
      else if (t.indexOf('设置') >= 0) out.setting = el;
      else if (t.indexOf('AI') >= 0) out.ai = el;
      else if (t.indexOf('项目') >= 0) out.project = el;
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

    // v7.7: 文件变更在最左边不动，只排后面的按钮
    var order = [b.exp, b.report, line, b.reload, b.setting, b.ai, b.project];
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

/* ============================================================
   模块三：文件变更面板重做
   - 不再遮黑全屏，右侧面板打开时页面往左让位
   - 按日期分段，一条一行，点开才看细节
   - 点一条自动跳到表格里对应那一行并高亮
   - 只在运行时接管，不改 index.html
   ============================================================ */
(function(){
  'use strict';

  var TYPES = ['added','archived','reclassified','approved','missing','deleted'];
  var TYPE_TEXT = {
    added:'新增', archived:'归档', reclassified:'改分类',
    approved:'复核通过', deleted:'删除', missing:'文件缺失'
  };

  var panel = null, listEl = null, searchEl = null, filterEl = null;
  var raw = [], openKey = '';
  var currentTab = 'client'; // client=文件变更, auditor=操作日志

  function root(){
    var el = document.querySelector('[x-data]');
    if(!el) return null;
    if(el._x_dataStack && el._x_dataStack[0]) return el._x_dataStack[0];
    if(window.Alpine && window.Alpine.$data){
      try{ return window.Alpine.$data(el); }catch(e){}
    }
    return null;
  }

  function esc(s){
    return String(s == null ? '' : s)
      .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  function typeKey(t){
    return TYPES.indexOf(t) >= 0 ? t : 'other';
  }
  function typeText(t){
    return TYPE_TEXT[t] || t || '变更';
  }

  function parseTime(s){
    if(!s) return null;
    var d = new Date(String(s).replace(' ','T'));
    return isNaN(d.getTime()) ? null : d;
  }
  function pad(n){ return n < 10 ? '0' + n : String(n); }

  function dayLabel(d){
    if(!d) return '时间未知';
    var now = new Date();
    var a = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    var b = new Date(d.getFullYear(), d.getMonth(), d.getDate());
    var diff = Math.round((a - b) / 86400000);
    if(diff === 0) return '今天';
    if(diff === 1) return '昨天';
    if(diff > 1 && diff < 7) return diff + ' 天前';
    return (d.getMonth() + 1) + ' 月 ' + d.getDate() + ' 日';
  }
  function hhmm(d){
    return d ? pad(d.getHours()) + ':' + pad(d.getMinutes()) : '';
  }

  var SVG_HIST = '<svg viewBox="0 0 24 24"><path d="M3 3v5h5"/><path d="M3.05 13A9 9 0 1 0 6 5.3L3 8"/><path d="M12 7v5l4 2"/></svg>';
  var SVG_REFRESH = '<svg viewBox="0 0 24 24"><path d="M21 2v6h-6"/><path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><path d="M3 22v-6h6"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/></svg>';
  var SVG_CLOSE = '<svg viewBox="0 0 24 24"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>';
  var SVG_GO = '<svg viewBox="0 0 24 24"><path d="M5 12h14"/><path d="m12 5 7 7-7 7"/></svg>';

  function build(){
    if(panel) return panel;
    panel = document.createElement('aside');
    panel.className = 'pbcg-vh';
    var opts = '<option value="">全部类型</option>';
    for(var i = 0; i < TYPES.length; i++){
      opts += '<option value="' + TYPES[i] + '">' + TYPE_TEXT[TYPES[i]] + '</option>';
    }
    panel.innerHTML =
      '<div class="pbcg-vh-hd">' +
        '<span class="ic">' + SVG_HIST + '</span>' +
        '<div><b>变更记录</b><span class="sub">客户与审计员的操作记录</span></div>' +
        '<div class="sp">' +
          '<button class="pbcg-vh-ico" data-act="refresh" title="刷新">' + SVG_REFRESH + '</button>' +
          '<button class="pbcg-vh-ico" data-act="close" title="关闭">' + SVG_CLOSE + '</button>' +
        '</div>' +
      '</div>' +
      '<div class="pbcg-vh-tabs" style="display:flex;border-bottom:1px solid hsl(var(--border))">' +
        '<button class="pbcg-vh-tab" data-tab="client" style="flex:1;padding:10px;font-size:13px;font-weight:600;border:none;background:none;cursor:pointer;border-bottom:2px solid hsl(var(--primary));color:hsl(var(--primary))">文件变更</button>' +
        '<button class="pbcg-vh-tab" data-tab="auditor" style="flex:1;padding:10px;font-size:13px;font-weight:600;border:none;background:none;cursor:pointer;border-bottom:2px solid transparent;color:hsl(var(--muted-foreground))">操作日志</button>' +
      '</div>' +
      '<div class="pbcg-vh-tools">' +
        '<input type="text" placeholder="搜文件名或编号">' +
        '<select>' + opts + '</select>' +
      '</div>' +
      '<div class="pbcg-vh-list"></div>' +
      '<div class="pbcg-vh-foot" style="padding:12px 16px;border-top:1px solid hsl(var(--border));background:hsl(var(--soft));display:flex;gap:8px;align-items:center">' +
        '<button class="pbcg-vh-organize" style="flex:1;padding:8px 12px;font-size:13px;font-weight:600;border-radius:7px;border:1px solid hsl(var(--primary));background:hsl(var(--primary));color:hsl(var(--primary-foreground));cursor:pointer">整理新文件</button>' +
      '</div>';
    document.body.appendChild(panel);

    listEl = panel.querySelector('.pbcg-vh-list');
    searchEl = panel.querySelector('input');
    filterEl = panel.querySelector('select');

    searchEl.addEventListener('input', render);
    filterEl.addEventListener('change', render);
    panel.querySelector('[data-act="close"]').addEventListener('click', close);
    panel.querySelector('[data-act="refresh"]').addEventListener('click', function(){ load(true); });
    listEl.addEventListener('click', onRowClick);
    // 子页签切换
    var tabBtns = panel.querySelectorAll('.pbcg-vh-tab');
    for(var ti = 0; ti < tabBtns.length; ti++){
      tabBtns[ti].addEventListener('click', function(){
        currentTab = this.getAttribute('data-tab');
        // 更新页签样式
        for(var tj = 0; tj < tabBtns.length; tj++){
          if(tabBtns[tj].getAttribute('data-tab') === currentTab){
            tabBtns[tj].style.borderBottomColor = 'hsl(var(--primary))';
            tabBtns[tj].style.color = 'hsl(var(--primary))';
          } else {
            tabBtns[tj].style.borderBottomColor = 'transparent';
            tabBtns[tj].style.color = 'hsl(var(--muted-foreground))';
          }
        }
        render();
      });
    }
    // 整理新文件按钮
    var orgBtn = panel.querySelector('.pbcg-vh-organize');
    if(orgBtn){
      orgBtn.addEventListener('click', function(){
        var d = root();
        if(!d || typeof d.startScan !== 'function') return;
        // 可选链兼容：手动取值
        var active = d.scan && d.scan.active;
        if(active) return;
        var pc = d.pendingCount || 0;
        if(pc <= 0) return;
        // 立即更新按钮状态，不等 reload
        orgBtn.textContent = '整理中...';
        orgBtn.disabled = true;
        orgBtn.style.opacity = '0.6';
        // 异步调用，不等它完成
        Promise.resolve(d.startScan()).catch(function(){});
        // 轮询按钮状态：scan.active 可能要等下一 tick 才变 true
        var pollCount = 0;
        var btnPoll = setInterval(function(){
          var dd = root();
          var act = dd && dd.scan && dd.scan.active;
          if(act || pollCount > 10){
            clearInterval(btnPoll);
            load(true);
          }
          pollCount++;
        }, 300);
      });
    }
    return panel;
  }

  function visible(){
    var q = (searchEl && searchEl.value || '').trim().toLowerCase();
    var t = (filterEl && filterEl.value) || '';
    return raw.filter(function(m){
      // 子页签过滤：client=文件变更(sync), auditor=操作日志(非sync)
      if(currentTab === 'client' && m.changed_by !== 'sync') return false;
      if(currentTab === 'auditor' && m.changed_by === 'sync') return false;
      if(t && m.change_type !== t) return false;
      if(!q) return true;
      var hay = ((m.file_name || '') + ' ' + (m.item_id || '') + ' ' + (m.changed_by || '')).toLowerCase();
      return hay.indexOf(q) >= 0;
    });
  }

  function render(){
    if(!listEl) return;
    var items = visible();
    if(!items.length){
      var emptyMsg = currentTab === 'client'
        ? '客户共享文件夹没有新的变化。整理新文件后，新增/修改/删除会显示在这里'
        : '还没有操作记录。归档、改分类后会在操作日志里记录';
      listEl.innerHTML = '<div class="pbcg-vh-msg">' + emptyMsg + '</div>';
      return;
    }

    items.sort(function(a, b){
      return String(b.changed_at || '').localeCompare(String(a.changed_at || ''));
    });

    var html = '', curDay = null, buf = [], groups = [];
    items.forEach(function(m){
      var d = parseTime(m.changed_at);
      var lb = dayLabel(d);
      if(lb !== curDay){
        if(buf.length) groups.push({ label: curDay, rows: buf });
        curDay = lb; buf = [];
      }
      buf.push({ m: m, d: d });
    });
    if(buf.length) groups.push({ label: curDay, rows: buf });

    groups.forEach(function(g){
      html += '<div class="pbcg-vh-day">' + esc(g.label) + '<i>' + g.rows.length + ' 条</i></div>';
      g.rows.forEach(function(r, idx){
        var m = r.m;
        var k = typeKey(m.change_type);
        var key = String(m.changed_at || '') + '|' + String(m.item_id || '') + '|' + String(m.file_name || '');
        var last = idx === g.rows.length - 1 ? ' last' : '';
        var on = key === openKey ? ' on' : '';
        var det = '<div class="pbcg-vh-det"><dl>';
        if(m.item_id) det += '<div><dt>编号</dt><dd>' + esc(m.item_id) + '</dd></div>';
        if(m.version != null && m.version !== '') det += '<div><dt>版本</dt><dd>v' + esc(m.version) + '</dd></div>';
        if(m.changed_by) det += '<div><dt>操作人</dt><dd>' + esc(m.changed_by) + '</dd></div>';
        det += '</dl>';
        if(m.reason) det += '<div class="why">' + esc(m.reason) + '</div>';
        if(m.item_id) det += '<button class="pbcg-vh-go" data-go="' + esc(m.item_id) + '">在清单里看这一行' + SVG_GO + '</button>';
        det += '<div class="pbcg-vh-miss" hidden></div></div>';

        html +=
          '<div class="pbcg-vh-row' + last + on + '" data-key="' + esc(key) + '" data-item="' + esc(m.item_id || '') + '">' +
            '<span class="pbcg-vh-dot pbcg-d-' + k + '"></span>' +
            '<div class="pbcg-vh-main">' +
              '<div class="pbcg-vh-l1">' +
                '<span class="pbcg-vh-tag pbcg-t-' + k + '">' + esc(typeText(m.change_type)) + '</span>' +
                '<span class="pbcg-vh-name" title="' + esc(m.file_name || m.item_id || '') + '">' + esc(m.file_name || m.item_id || '未命名文件') + '</span>' +
                '<span class="pbcg-vh-time">' + esc(hhmm(r.d)) + '</span>' +
              '</div>' + det +
            '</div>' +
          '</div>';
      });
    });

    listEl.innerHTML = html;
  }

  function onRowClick(e){
    var go = e.target.closest ? e.target.closest('.pbcg-vh-go') : null;
    var row = e.target.closest ? e.target.closest('.pbcg-vh-row') : null;
    if(!row) return;
    if(go){
      e.stopPropagation();
      report(row, locate(go.getAttribute('data-go')));
      return;
    }
    var key = row.getAttribute('data-key');
    if(openKey === key){
      openKey = '';
      row.classList.remove('on');
      return;
    }
    openKey = key;
    var all = listEl.querySelectorAll('.pbcg-vh-row.on');
    for(var i = 0; i < all.length; i++) all[i].classList.remove('on');
    row.classList.add('on');
    report(row, locate(row.getAttribute('data-item')));
  }

  function report(row, ok){
    var tip = row.querySelector('.pbcg-vh-miss');
    if(!tip) return;
    if(ok){ tip.hidden = true; tip.textContent = ''; }
    else{ tip.hidden = false; tip.textContent = '这个文件不在当前页签的清单里，换个页签再点一次'; }
  }

  function locate(itemId){
    if(!itemId) return false;
    var old = document.querySelectorAll('.pbcg-vh-hit');
    for(var j = 0; j < old.length; j++) old[j].classList.remove('pbcg-vh-hit');

    var cells = document.querySelectorAll('table.tbl td.code');
    for(var i = 0; i < cells.length; i++){
      if((cells[i].textContent || '').trim() !== String(itemId).trim()) continue;
      var tr = cells[i].closest('tr');
      if(!tr) continue;
      try{ tr.scrollIntoView({ block:'center', behavior:'smooth' }); }catch(e){ tr.scrollIntoView(); }
      tr.classList.add('pbcg-vh-hit');
      setTimeout(function(){ tr.classList.remove('pbcg-vh-hit'); }, 2300);
      return true;
    }
    return false;
  }

  function loading(){
    if(listEl) listEl.innerHTML = '<div class="pbcg-vh-msg">正在读取变更记录</div>';
  }

  function load(force){
    var d = root();
    if(!d || !d.changePanel){
      if(listEl) listEl.innerHTML = '<div class="pbcg-vh-msg">页面还没准备好，稍后再试一次</div>';
      return;
    }
    if(force || !(d.changePanel.items || []).length) loading();

    var done = function(){
      raw = (d.changePanel.items || []).slice();
      if(d.changePanel.error){
        listEl.innerHTML = '<div class="pbcg-vh-msg">' + esc(d.changePanel.error) + '</div>';
        return;
      }
      render();
      // 更新整理新文件按钮状态
      var orgBtn = panel.querySelector('.pbcg-vh-organize');
      if(orgBtn){
        var pc = d.pendingCount || 0;
        var active = d.scan && d.scan.active;
        // 先用 Alpine 的 pendingArchive
        var pendingConfirm = (d.pendingArchive && d.pendingArchive.items) ? d.pendingArchive.items.length : 0;
        
        function updateBtn(pc, pendingConfirm, active){
          if(active){
            orgBtn.textContent = '整理中...';
            orgBtn.disabled = true;
            orgBtn.style.opacity = '0.6';
          } else if(pendingConfirm > 0){
            orgBtn.textContent = '请先处理待归档 (' + pendingConfirm + ')';
            orgBtn.disabled = true;
            orgBtn.style.opacity = '0.7';
          } else if(pc > 0){
            orgBtn.textContent = '整理新文件 (' + pc + ')';
            orgBtn.disabled = false;
            orgBtn.style.opacity = '1';
          } else {
            orgBtn.textContent = '无待整理文件';
            orgBtn.disabled = true;
            orgBtn.style.opacity = '0.5';
          }
        }
        
        updateBtn(pc, pendingConfirm, active);
        
        // 同步查 API 拿 pending-confirm（用 XMLHttpRequest 同步）
        if(!active && d.currentProjectId){
          try {
            var xhr = new XMLHttpRequest();
            xhr.open('GET', '/api/files/'+d.currentProjectId+'/pending-confirm', false);
            xhr.send(null);
            if(xhr.status === 200){
              var data = JSON.parse(xhr.responseText);
              var cnt = (data.items||[]).length;
              if(cnt > 0 || pendingConfirm > 0){
                updateBtn(pc, Math.max(cnt, pendingConfirm), false);
              }
            }
          } catch(e) {}
        }
      }
      if(typeof d.markChangesSeen === 'function'){
        try{ d.markChangesSeen(); }catch(e){}
      }
    };

    if(typeof d.loadChangeLog === 'function'){
      try{
        d.changePanel.filter = '';
        var p = d.loadChangeLog();
        if(p && typeof p.then === 'function'){ p.then(done, done); }
        else done();
      }catch(e){ done(); }
    }else{
      done();
    }
  }

  function open(){
    build();
    document.body.classList.add('pbcg-vh-open');
    var d = root();
    if(d && d.changePanel) d.changePanel.show = false;
    load(false);
  }

  function close(){
    document.body.classList.remove('pbcg-vh-open');
    var d = root();
    if(d && d.changePanel) d.changePanel.show = false;
  }

  /* 接管顶栏按钮的点击，不让旧的全屏弹窗弹出来 */
  function hook(){
    document.addEventListener('click', function(e){
      var btn = e.target.closest ? e.target.closest('button') : null;
      if(!btn) return;
      if(panel && panel.contains(btn)) return;
      var txt = (btn.textContent || '').replace(/\s/g,'');
      if(txt.indexOf('变更记录') < 0 && txt.indexOf('文件变更') < 0) return;
      e.preventDefault();
      e.stopPropagation();
      if(document.body.classList.contains('pbcg-vh-open')) close();
      else open();
    }, true);

    document.addEventListener('keydown', function(e){
      if(e.key === 'Escape' && document.body.classList.contains('pbcg-vh-open')) close();
    });

    /* 兜底：如果旧面板被别的路径打开了，把它按回去换成新的 */
    setInterval(function(){
      var d = root();
      if(d && d.changePanel && d.changePanel.show){
        d.changePanel.show = false;
        if(!document.body.classList.contains('pbcg-vh-open')) open();
      }
    }, 400);
  }

  if(document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', hook);
  }else{
    hook();
  }

  window.__pbcgChangePanel = { open: open, close: close, reload: function(){ load(true); } };
})();
