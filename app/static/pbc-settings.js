/* PBC 增强 · 模块五：客户共享文件夹设置弹窗按钮收敛
 * 原状：右上角 × / 保存客户文件夹 / 关闭 / 保存归档目录，共 4 个按钮
 * 改后：右上角 × + 底部唯一一个保存
 * 保存时比对两段路径哪段动过，动过的才复用原生按钮发请求，后端接口零改动
 * 不改 index.html，纯运行时接管
 */
(function () {
  if (window.__pbcgSettings) return;

  var TITLE = '客户共享文件夹设置';
  var T_SAVE = '保存客户文件夹';
  var T_ARC = '保存归档目录';
  var snap = ['', ''];
  var vis = false;

  function css() {
    if (document.getElementById('pbcg-set-css')) return;
    var s = document.createElement('style');
    s.id = 'pbcg-set-css';
    s.textContent =
      '.pbcg-set-hid{display:none !important}' +
      '.pbcg-set-ft{display:flex;justify-content:flex-end;align-items:center;' +
      'padding:16px 22px;margin-top:18px;border-top:1px solid var(--border);' +
      'background:var(--soft);border-radius:0 0 12px 12px}';
    document.head.appendChild(s);
  }

  function findModal() {
    var ovs = document.querySelectorAll('.overlay');
    for (var i = 0; i < ovs.length; i++) {
      var ov = ovs[i];
      if (getComputedStyle(ov).display === 'none') continue;
      var tt = ov.querySelector('.modal-h .tt');
      if (tt && tt.textContent.indexOf(TITLE) >= 0) return ov.querySelector('.modal');
    }
    return null;
  }

  function btn(m, t) {
    var bs = m.querySelectorAll('button');
    for (var i = 0; i < bs.length; i++) {
      if ((bs[i].textContent || '').trim() === t) return bs[i];
    }
    return null;
  }

  function inputs(m) {
    return Array.prototype.slice.call(m.querySelectorAll('input[type="text"]'));
  }

  function takeSnap(m) {
    var i = inputs(m);
    snap = [i[0] ? i[0].value : '', i[1] ? i[1].value : ''];
  }

  function doSave(m, bSave, bArc) {
    var i = inputs(m);
    var c0 = !!i[0] && i[0].value !== snap[0];
    var c1 = !!i[1] && i[1].value !== snap[1];
    if (!c0 && !c1) {
      var x = m.querySelector('.modal-h .x');
      if (x) x.click();
      return;
    }
    if (c0) bSave.click();
    if (c1) setTimeout(function () { bArc.click(); }, c0 ? 260 : 0);
    setTimeout(function () { takeSnap(m); }, c0 && c1 ? 400 : 120);
  }

  function patch(m) {
    if (m.getAttribute('data-pbcg-set') === '1') return;
    var bSave = btn(m, T_SAVE);
    var bArc = btn(m, T_ARC);
    if (!bSave || !bArc) return;
    m.setAttribute('data-pbcg-set', '1');
    css();

    if (bSave.parentElement) bSave.parentElement.classList.add('pbcg-set-hid');
    if (bArc.parentElement) bArc.parentElement.classList.add('pbcg-set-hid');

    var ft = document.createElement('div');
    ft.className = 'pbcg-set-ft';
    var b = document.createElement('button');
    b.type = 'button';
    b.className = 'btn btn-pri';
    b.textContent = '保存';
    b.addEventListener('click', function () { doSave(m, bSave, bArc); });
    ft.appendChild(b);
    m.appendChild(ft);
  }

  function tick() {
    var m = findModal();
    if (m) {
      patch(m);
      if (!vis) { vis = true; takeSnap(m); }
    } else {
      vis = false;
    }
  }

  function boot() {
    tick();
    setInterval(tick, 400);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }

  window.__pbcgSettings = { tick: tick };
})();
