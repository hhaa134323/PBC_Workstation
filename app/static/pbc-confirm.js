/* 待归档 · HITL 归档前确认
   原地把待复核页签换成待归档，接 pending-confirm 系列接口。
   不改 index.html，不碰 pbc-enhance 两件套。前缀 pbcg-cf- */
(function () {
  'use strict';
  if (window.__pbcgConfirm) return;

  var OLD_TAB = '待复核';
  var NEW_TAB = '待归档';
  var state = { items: [], loading: false, err: '', sel: {}, open: {}, done: {}, fail: {}, busy: false, loaded: false };

  function pid() {
    try {
      var r = document.querySelector('[x-data]');
      var d = r && (r._x_dataStack ? r._x_dataStack[0] : (r.__x && r.__x.$data));
      if (d && d.projectId) return d.projectId;
      if (d && d.currentProject) return d.currentProject;
    } catch (e) {}
    var m = location.search.match(/[?&]project=([^&]+)/);
    return m ? decodeURIComponent(m[1]) : 'demo';
  }
  var API = {
    list: function (p) { return '/api/files/' + p + '/pending-confirm'; },
    confirm: function (p, i) { return '/api/files/' + p + '/confirm/' + i; },
    batch: function (p) { return '/api/files/' + p + '/batch-confirm'; },
    skip: function (p, i) { return '/api/files/' + p + '/skip-confirm/' + i; },
    reclass: function (p, i) { return '/api/files/' + p + '/reclassify-confirm/' + i; },
    ai: '/api/config/ai'
  };
  function jget(u) { return fetch(u).then(function (r) { return r.json(); }); }
  function jpost(u, b) {
    return fetch(u, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b || {}) })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, body: j }; }); });
  }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  var SVG_OK = '<svg width="14" height="14" viewBox="0 0 16 16" fill="none"><path d="M3.4 8.4 6.6 11.6 12.8 5" stroke="#8C8C99" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>';

  /* ---------- 依据文案：不用颜色分档，只用文字 ---------- */
  function whyText(it) {
    var d = (it.decision || '').toLowerCase();
    if (d === 'auto') return { t: '内容和清单描述高度吻合', s: true };
    if (d === 'suggest') return { t: '有几处对得上，不完全确定', s: false };
    if (d === 'llm') return { t: '靠模型读内容推断', s: false };
    if (d === 'walkthrough') return { t: '整个文件夹一起收进来的', s: false };
    return { t: '文件名里就带这个编号', s: true };
  }
  function hasConflict(it) {
    var c = it.conflict_signal;
    if (!c) return false;
    if (typeof c === 'object' && !Object.keys(c).length) return false;
    return true;
  }
  function normal(it) { return !hasConflict(it) && !state.done[it.id] && !state.fail[it.id]; }

  /* ---------- 页签 ---------- */
  function tabNodes() {
    var out = [];
    var all = document.querySelectorAll('nav a, nav button, nav div, .tabs a, .tabs button, .tabs div');
    for (var i = 0; i < all.length; i++) {
      var n = all[i];
      if (n.children.length > 2) continue;
      var t = (n.textContent || '').replace(/\s|\d/g, '');
      if (t === OLD_TAB || t === NEW_TAB) out.push(n);
    }
    return out;
  }
  function renameTab() {
    var ns = tabNodes();
    for (var i = 0; i < ns.length; i++) {
      var n = ns[i];
      if (n.getAttribute('data-pbcg-cf') === '1') continue;
      walkText(n, OLD_TAB, NEW_TAB);
      n.setAttribute('data-pbcg-cf', '1');
      n.addEventListener('click', function () { setTimeout(sync, 0); setTimeout(sync, 60); });
    }
    return ns.length > 0;
  }
  function walkText(node, from, to) {
    if (node.nodeType === 3) {
      if (node.nodeValue.indexOf(from) >= 0) node.nodeValue = node.nodeValue.replace(from, to);
      return;
    }
    for (var i = 0; i < node.childNodes.length; i++) walkText(node.childNodes[i], from, to);
  }
  function paintCount() {
    var ns = tabNodes();
    for (var i = 0; i < ns.length; i++) {
      var badge = ns[i].querySelector('span:last-child');
      if (badge && /^\s*\d+\s*$/.test(badge.textContent)) badge.textContent = String(state.items.length);
    }
  }
  function tabActive() {
    var ns = tabNodes();
    for (var i = 0; i < ns.length; i++) {
      var n = ns[i], c = n.className || '';
      if (/active|on\b|border-b-2|font-semibold|font-bold/.test(c)) return true;
      if (n.getAttribute('aria-selected') === 'true') return true;
      var cs = getComputedStyle(n);
      if (cs.borderBottomWidth && parseFloat(cs.borderBottomWidth) >= 2 && cs.borderBottomStyle === 'solid') {
        var col = cs.borderBottomColor || '';
        if (col && col.indexOf('rgba(0, 0, 0, 0)') < 0 && col !== 'transparent') return true;
      }
    }
    return false;
  }

  /* ---------- 挂载点 ---------- */
  function host() {
    var h = document.getElementById('pbcg-cf-host');
    if (h) return h;
    var ns = tabNodes();
    if (!ns.length) return null;
    var bar = ns[0].parentNode;
    var anchor = bar && bar.parentNode;
    if (!anchor) return null;
    h = document.createElement('div');
    h.id = 'pbcg-cf-host';
    h.style.display = 'none';
    if (anchor.nextSibling) anchor.parentNode.insertBefore(h, anchor.nextSibling);
    else anchor.parentNode.appendChild(h);
    return h;
  }
  function siblings(h, hide) {
    var p = h.parentNode; if (!p) return;
    for (var i = 0; i < p.children.length; i++) {
      var c = p.children[i];
      if (c === h) continue;
      if (c.contains(document.querySelector('[data-pbcg-cf="1"]'))) continue;
      if (hide) {
        if (c.getAttribute('data-pbcg-cf-hid') === '1') continue;
        if (getComputedStyle(c).display === 'none') continue;
        c.setAttribute('data-pbcg-cf-hid', '1');
        c.setAttribute('data-pbcg-cf-d', c.style.display || '');
        c.style.display = 'none';
      } else if (c.getAttribute('data-pbcg-cf-hid') === '1') {
        c.style.display = c.getAttribute('data-pbcg-cf-d') || '';
        c.removeAttribute('data-pbcg-cf-hid');
        c.removeAttribute('data-pbcg-cf-d');
      }
    }
  }

  /* ---------- 渲染 ---------- */
  function rowHtml(it) {
    var conf = hasConflict(it), done = state.done[it.id], fail = state.fail[it.id];
    var w = whyText(it);
    var cls = 'pbcg-cf-row' + (conf || fail ? ' flag' : '') + (done ? ' done' : '');
    var c0 = done ? SVG_OK : (conf || fail ? '' : '<span class="pbcg-cf-ck' + (state.sel[it.id] ? ' on' : '') + '" data-ck="' + it.id + '"></span>');
    var why = done ? '<span class="pbcg-cf-why">已归档</span>'
      : fail ? '<span class="pbcg-cf-why r">没归成，' + esc(fail) + '</span>'
      : conf ? '<span class="pbcg-cf-why r">编号对不上，请单独看</span>'
      : '<span class="pbcg-cf-why' + (w.s ? ' strong' : '') + '">' + esc(w.t) + '</span>';
    var tid = it.suggested_item_id || '';
    var name = it.item_name || it.doc_name || '';
    var right = done && it.archived_path
      ? '<div class="pbcg-cf-tn"><span class="pbcg-cf-id">' + esc(tid) + '</span>\u3000' + esc(name) + '</div><div class="pbcg-cf-path">' + esc(it.archived_path) + '</div>'
      : tid
        ? '<div class="pbcg-cf-tn"><span class="pbcg-cf-id">' + esc(tid) + '</span>\u3000' + esc(name) + '</div><div class="pbcg-cf-path">' + esc(preview(it)) + '</div>'
        : '<div class="pbcg-cf-tn" style="font-weight:400;color:hsl(var(--muted-foreground))">没配到清单项，需要你指一个</div>';
    var acts = done
      ? '<button class="pbcg-cf-btn" data-open="' + esc(it.file_path || '') + '">打开位置</button>'
      : conf
        ? '<button class="pbcg-cf-btn" data-skip="' + it.id + '">跳过</button>'
        : '<button class="pbcg-cf-btn" data-re="' + it.id + '">改</button><button class="pbcg-cf-btn" data-skip="' + it.id + '">跳过</button><button class="pbcg-cf-btn pri" data-ok="' + it.id + '">确认</button>';
    var h = '<div class="' + cls + '" data-row="' + it.id + '"><div class="pbcg-cf-main">'
      + '<span class="pbcg-cf-c0">' + c0 + '</span>'
      + '<div class="pbcg-cf-c1"><div class="pbcg-cf-fn">' + esc(it.file_name || '') + '</div><div class="pbcg-cf-meta">' + esc(fromDir(it)) + '</div></div>'
      + '<div class="pbcg-cf-c2" data-det="' + it.id + '">' + why + '</div>'
      + '<div class="pbcg-cf-c3">' + right + '</div>'
      + '<div class="pbcg-cf-c4">' + acts + '</div>'
      + '</div>';
    if (conf && !done) h += conflictHtml(it);
    if (state.open[it.id] && !conf) h += detHtml(it);
    return h + '</div>';
  }
  function fromDir(it) {
    var p = it.file_path || '';
    var parts = p.replace(/\\/g, '/').split('/');
    parts.pop();
    return parts.slice(-2).join(' / ') || '客户共享文件夹';
  }
  function preview(it) {
    if (it.archive_preview) return it.archive_preview;
    var id = it.suggested_item_id || '', n = it.item_name || it.doc_name || '', c = it.category || '';
    var ext = (it.file_name || '').match(/\.[a-z0-9]+$/i);
    if (!id) return '';
    var base = id + (n ? '_' + n : '') + (it.required_period ? '_' + it.required_period : '') + '_v1' + (ext ? ext[0] : '');
    return (c ? c + ' / ' : '') + id + (n ? '_' + n : '') + ' / ' + base;
  }
  function conflictHtml(it) {
    var c = it.conflict_signal || {};
    var a = c.detected_item_id || '', b = c.matched_item_id || it.suggested_item_id || '';
    var hint = c.hint || '文件名里的编号和内容读出来的编号对不上。';
    var pills = '';
    if (a) pills += '<span class="pbcg-cf-pill" data-pick="' + it.id + '|' + esc(a) + '"><b>' + esc(a) + '</b></span>';
    if (b && b !== a) pills += '<span class="pbcg-cf-pill" data-pick="' + it.id + '|' + esc(b) + '"><b>' + esc(b) + '</b></span>';
    pills += '<span class="pbcg-cf-pill" data-re="' + it.id + '">自己挑一个</span>';
    return '<div class="pbcg-cf-flagbox"><div class="pbcg-cf-flagt">这份要你单独看一眼</div>'
      + '<div class="pbcg-cf-flagd">' + esc(hint) + ' 这种情况不会自动归档，也不参与批量确认。</div>'
      + '<div class="pbcg-cf-pick"><span class="pbcg-cf-txt" style="margin-right:2px">归到哪个：</span>' + pills + '</div></div>';
  }
  function bar(l, v) {
    var pct = Math.max(0, Math.min(1, Number(v) || 0)) * 100;
    return '<div class="pbcg-cf-sc"><span class="pbcg-cf-sl">' + esc(l) + '</span><span class="pbcg-cf-sb"><span class="pbcg-cf-sf" style="width:' + pct.toFixed(0) + '%"></span></span><span class="pbcg-cf-sv">' + (Number(v) || 0).toFixed(2) + '</span></div>';
  }
  function detHtml(it) {
    var sb = it.score_breakdown, left = '';
    if (sb && typeof sb === 'object') {
      left = '<div class="pbcg-cf-dh">四项打分</div>'
        + bar('所在文件夹', sb.F1_folder_vs_category)
        + bar('文件名', sb.F2_filename_vs_doc_name)
        + bar('正文内容', sb.F3_content_vs_description)
        + bar('期间', sb.F4_folder_vs_period)
        + '<div class="pbcg-cf-sc tot"><span class="pbcg-cf-sl">合计</span><span class="pbcg-cf-sb"><span class="pbcg-cf-sf" style="width:'
        + (Math.max(0, Math.min(1, Number(sb.total) || 0)) * 100).toFixed(0) + '%"></span></span><span class="pbcg-cf-sv">'
        + (Number(sb.total) || 0).toFixed(2) + '</span></div>';
      if (it.all_scores && it.all_scores.length) {
        left += '<div class="pbcg-cf-alt"><div class="pbcg-cf-dh">其他候选</div>';
        for (var i = 0; i < Math.min(3, it.all_scores.length); i++) {
          var s = it.all_scores[i];
          left += bar(s.item_id || s.id || '', s.score != null ? s.score : s.total);
        }
        left += '</div>';
      }
    } else {
      left = '<div class="pbcg-cf-dh">四项打分</div><div class="pbcg-cf-vv">这条接口还没返回打分明细，'
        + '把握度 ' + (it.confidence != null ? Number(it.confidence).toFixed(2) : '未知') + '</div>';
    }
    var kv = '';
    function add(k, v) { if (v) kv += '<div class="pbcg-cf-kv"><span class="pbcg-cf-kk">' + k + '</span><span class="pbcg-cf-vv">' + esc(v) + '</span></div>'; }
    add('清单描述', it.description);
    add('要求期间', it.required_period);
    add('归档后叫', preview(it).split('/').pop());
    add('进来时间', it.created_at);
    var notes = it.advisory_notes;
    if (notes && notes.length) {
      var txt = [];
      for (var j = 0; j < notes.length; j++) txt.push(notes[j].hint || notes[j].trigger || String(notes[j]));
      add('提醒', txt.join('；'));
    }
    if (!kv) kv = '<div class="pbcg-cf-vv">没有更多信息</div>';
    return '<div class="pbcg-cf-det"><div class="pbcg-cf-dcol">' + left + '</div>'
      + '<div class="pbcg-cf-dcol r"><div class="pbcg-cf-dh">其他信息</div>' + kv + '</div></div>';
  }

  function render() {
    var h = host(); if (!h) return;
    if (state.loading && !state.loaded) {
      h.innerHTML = '<div class="pbcg-cf-wrap"><div class="pbcg-cf-empty"><div class="d">正在读待归档的文件</div></div></div>';
      return;
    }
    if (state.err) {
      h.innerHTML = '<div class="pbcg-cf-wrap"><div class="pbcg-cf-empty"><div class="t">读不到待归档的清单</div><div class="d">'
        + esc(state.err) + '</div></div></div>';
      return;
    }
    var items = state.items;
    if (!items.length) {
      h.innerHTML = '<div class="pbcg-cf-wrap"><div class="pbcg-cf-h1">待归档</div>'
        + '<div class="pbcg-cf-sub">这些文件已经读过了，还没动。确认之后才会重命名并放进归档目录。</div>'
        + '<div class="pbcg-cf-empty"><div class="t">这会儿没有要确认的文件</div>'
        + '<div class="d">扫描之后如果有文件配上了清单项，会先停在这里等你点确认。</div></div></div>';
      return;
    }
    var norm = items.filter(normal), sel = norm.filter(function (i) { return state.sel[i.id]; });
    var conflicts = items.filter(function (i) { return hasConflict(i) && !state.done[i.id]; });
    var rest = items.filter(function (i) { return !hasConflict(i) || state.done[i.id]; });
    var allOn = norm.length > 0 && sel.length === norm.length;
    var html = '<div class="pbcg-cf-wrap"><div class="pbcg-cf-h1">待归档</div>'
      + '<div class="pbcg-cf-sub">这些文件已经读过了，还没动。确认之后才会重命名并放进归档目录。</div>'
      + '<div class="pbcg-cf-bar"><span class="pbcg-cf-ck' + (allOn ? ' on' : '') + '" data-all="1"></span>'
      + '<span class="pbcg-cf-txt">已选 ' + sel.length + ' 份，共 ' + items.length + ' 份</span>'
      + (conflicts.length ? '<span class="pbcg-cf-txt pbcg-cf-warn">' + conflicts.length + ' 份要你单独看，没算进批量</span>' : '')
      + '<span class="sp"></span>'
      + '<button class="pbcg-cf-btn" data-skipall="1"' + (sel.length ? '' : ' disabled') + '>跳过选中的</button>'
      + '<button class="pbcg-cf-btn lg pri" data-batch="1"' + (sel.length && !state.busy ? '' : ' disabled') + '>'
      + (state.busy ? '正在归档' : '确认归档选中的 ' + sel.length + ' 份') + '</button></div>';
    if (state.busy) html += '<div class="pbcg-cf-bar" style="display:block"><div class="pbcg-cf-txt">一次请求发出去了，完成之后整批一起回来</div><div class="pbcg-cf-prog"><span class="pbcg-cf-progf" style="width:60%"></span></div></div>';
    html += '<div class="pbcg-cf-tbl"><div class="pbcg-cf-hd"><span class="pbcg-cf-c0"></span>'
      + '<span class="pbcg-cf-c1">客户交来的文件</span><span class="pbcg-cf-c2">判断依据</span>'
      + '<span class="pbcg-cf-c3">归到清单哪一项</span><span class="pbcg-cf-c4"></span></div>';
    conflicts.concat(rest).forEach(function (it) { html += rowHtml(it); });
    h.innerHTML = html + '</div></div>';
  }

  /* ---------- 事件 ---------- */
  function onClick(e) {
    var h = document.getElementById('pbcg-cf-host');
    if (!h || !h.contains(e.target)) return;
    var t = e.target.closest('[data-ck],[data-all],[data-det],[data-ok],[data-skip],[data-re],[data-batch],[data-skipall],[data-pick],[data-open]');
    if (!t) return;
    e.preventDefault(); e.stopPropagation();
    var v;
    if ((v = t.getAttribute('data-ck'))) { state.sel[v] = !state.sel[v]; return render(); }
    if (t.getAttribute('data-all')) {
      var norm = state.items.filter(normal);
      var on = norm.every(function (i) { return state.sel[i.id]; });
      norm.forEach(function (i) { state.sel[i.id] = !on; });
      return render();
    }
    if ((v = t.getAttribute('data-det'))) { state.open[v] = !state.open[v]; return render(); }
    if ((v = t.getAttribute('data-ok'))) return doConfirm(v);
    if ((v = t.getAttribute('data-skip'))) return doSkip(v);
    if ((v = t.getAttribute('data-re'))) return dlg(v);
    if (t.getAttribute('data-batch')) return doBatch();
    if (t.getAttribute('data-skipall')) return doSkipAll();
    if ((v = t.getAttribute('data-pick'))) { var a = v.split('|'); return doReclass(a[0], a[1], true); }
    if ((v = t.getAttribute('data-open'))) return openPath(v);
  }
  function openPath(p) {
    if (!p) return;
    fetch('/api/files/' + pid() + '/open-folder-path', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path: p })
    }).catch(function () {});
  }
  function mark(id, r) {
    if (r && r.ok) {
      state.done[id] = true;
      var it = find(id);
      if (it && r.body) { it.archived_path = r.body.archived_path || it.archived_path; }
      delete state.sel[id];
    } else {
      state.fail[id] = (r && r.body && (r.body.detail || r.body.message)) || '接口没通过';
    }
  }
  function find(id) {
    for (var i = 0; i < state.items.length; i++) if (String(state.items[i].id) === String(id)) return state.items[i];
    return null;
  }
  function doConfirm(id) {
    var it = find(id); if (!it) return;
    jpost(API.confirm(pid(), id), {}).then(function (r) { mark(id, r); render(); })
      .catch(function (e) { state.fail[id] = String(e); render(); });
  }
  function doSkip(id) {
    jpost(API.skip(pid(), id), {}).then(function (r) {
      if (r.ok) { state.items = state.items.filter(function (i) { return String(i.id) !== String(id); }); delete state.sel[id]; }
      else state.fail[id] = (r.body && (r.body.detail || r.body.message)) || '跳过没成功，后端这个接口可能还没接好';
      render(); paintCount();
    }).catch(function (e) { state.fail[id] = String(e); render(); });
  }
  function doSkipAll() {
    var ids = Object.keys(state.sel).filter(function (k) { return state.sel[k]; });
    if (!ids.length) return;
    var n = 0;
    ids.forEach(function (id) {
      jpost(API.skip(pid(), id), {}).then(function (r) {
        if (r.ok) { state.items = state.items.filter(function (i) { return String(i.id) !== String(id); }); delete state.sel[id]; }
        else state.fail[id] = '跳过没成功';
        if (++n === ids.length) { render(); paintCount(); }
      });
    });
  }
  function doBatch() {
    var ids = state.items.filter(normal).filter(function (i) { return state.sel[i.id]; }).map(function (i) { return i.id; });
    if (!ids.length) return;
    state.busy = true; render();
    jpost(API.batch(pid()), { confirm_ids: ids }).then(function (r) {
      state.busy = false;
      var b = r.body || {};
      (b.results || []).forEach(function (x) {
        state.done[x.confirm_id] = true;
        var it = find(x.confirm_id);
        if (it) it.archived_path = x.archived_path;
        delete state.sel[x.confirm_id];
      });
      (b.errors || []).forEach(function (msg) {
        var m = String(msg).match(/id=(\d+)\s*(.*)/);
        if (m) state.fail[m[1]] = m[2] || '没归成';
      });
      render(); paintCount();
    }).catch(function (e) { state.busy = false; state.err = ''; alert('批量确认没发出去：' + e); render(); });
  }
  function doReclass(id, newId, thenConfirm) {
    if (!newId) return;
    jpost(API.reclass(pid(), id), { new_item_id: newId }).then(function (r) {
      if (!r.ok) { state.fail[id] = (r.body && (r.body.detail || r.body.message)) || '这个编号在清单里找不到'; return render(); }
      var it = find(id);
      if (it) { it.suggested_item_id = newId; it.item_name = ''; it.conflict_signal = null; }
      render();
    });
  }
  function dlg(id) {
    var it = find(id); if (!it) return;
    var m = document.createElement('div');
    m.className = 'pbcg-cf-mask';
    m.innerHTML = '<div class="pbcg-cf-dlg"><div class="hd">换一个清单项</div><div class="bd">'
      + '<div class="pbcg-cf-txt" style="margin-bottom:8px">' + esc(it.file_name || '') + '</div>'
      + '<input class="pbcg-cf-inp" placeholder="填清单编号，比如 B-07" value="' + esc(it.suggested_item_id || '') + '">'
      + '<div class="pbcg-cf-txt" style="margin-top:9px">改完还停在待归档，要再点一次确认才真的归。</div>'
      + '</div><div class="ft"><button class="pbcg-cf-btn" data-x="1">算了</button>'
      + '<button class="pbcg-cf-btn pri" data-y="1">改成这个</button></div></div>';
    document.body.appendChild(m);
    var inp = m.querySelector('input');
    inp.focus(); inp.select();
    function close() { m.remove(); }
    m.addEventListener('click', function (e) {
      if (e.target === m || e.target.getAttribute('data-x')) return close();
      if (e.target.getAttribute('data-y')) { doReclass(id, inp.value.trim()); close(); }
    });
    inp.addEventListener('keydown', function (e) { if (e.key === 'Enter') { doReclass(id, inp.value.trim()); close(); } });
  }

  /* ---------- 拉数据 ---------- */
  function load(force) {
    if (state.loading) return;
    if (state.loaded && !force) return;
    state.loading = true; state.err = '';
    if (!state.loaded) render();
    jget(API.list(pid())).then(function (j) {
      state.loading = false; state.loaded = true;
      state.items = (j && j.items) || [];
      state.items.forEach(function (i) { if (normal(i) && state.sel[i.id] == null) state.sel[i.id] = true; });
      render(); paintCount();
    }).catch(function (e) {
      state.loading = false; state.loaded = true;
      state.err = String(e);
      render();
    });
  }

  /* ---------- 待初检副标题：原文案与代码对不上 ---------- */
  function fixTriageSub() {
    var ns = document.querySelectorAll('p,div,span');
    for (var i = 0; i < ns.length; i++) {
      var n = ns[i];
      if (n.children.length) continue;
      var t = (n.textContent || '').trim();
      if (t.indexOf('AI 已自动分类归档') === 0 || t.indexOf('AI已自动分类归档') === 0) {
        n.textContent = '客户还没交，也还没到期的清单项。';
        n.setAttribute('data-pbcg-cf-sub', '1');
      }
    }
  }

  /* ---------- AI 配置：只加一个开关 ---------- */
  function fixAiPanel() {
    if (document.getElementById('pbcg-cf-auto')) return;
    var box = null, ns = document.querySelectorAll('div');
    for (var i = 0; i < ns.length; i++) {
      var n = ns[i];
      if (n.offsetParent === null) continue;
      var t = n.textContent || '';
      if (t.indexOf('模型') >= 0 && (t.indexOf('接口地址') >= 0 || t.indexOf('base_url') >= 0 || t.indexOf('API Key') >= 0 || t.indexOf('密钥') >= 0)) {
        if (t.length < 2600) box = n;
      }
    }
    if (!box) return;
    var w = document.createElement('div');
    w.id = 'pbcg-cf-auto';
    w.className = 'pbcg-cf-cfg';
    w.innerHTML = '<span class="pbcg-cf-sw"></span><div><div class="t">自动归档高把握度文件</div>'
      + '<div class="d">开启后，内容与清单高度吻合的文件会直接归档，不进待归档。<br>发现编号矛盾时仍然会拦下来等你确认。</div></div>';
    box.appendChild(w);
    var sw = w.querySelector('.pbcg-cf-sw');
    jget(API.ai).then(function (j) {
      var on = j && j.config && j.config.auto_confirm_enabled;
      if (on) sw.classList.add('on');
    }).catch(function () {});
    sw.addEventListener('click', function () {
      var next = !sw.classList.contains('on');
      sw.classList.toggle('on', next);
      fetch(API.ai, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ auto_confirm_enabled: next })
      }).then(function (r) { if (!r.ok) sw.classList.toggle('on', !next); })
        .catch(function () { sw.classList.toggle('on', !next); });
    });
  }

  /* ---------- 同步 ---------- */
  function sync() {
    if (!renameTab()) return;
    var h = host(); if (!h) return;
    fixTriageSub();
    fixAiPanel();
    if (tabActive()) {
      h.style.display = '';
      siblings(h, true);
      load(false);
    } else {
      h.style.display = 'none';
      siblings(h, false);
    }
  }

  function boot() {
    document.addEventListener('click', onClick, true);
    var mo = new MutationObserver(function () { sync(); });
    mo.observe(document.body, { childList: true, subtree: true });
    var n = 0, t = setInterval(function () { sync(); if (++n > 40) clearInterval(t); }, 250);
    sync();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();

  window.__pbcgConfirm = { reload: function () { load(true); }, state: state };
})();
