const puppeteer = require('puppeteer-core');

(async () => {
  const browser = await puppeteer.launch({
    executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe',
    headless: 'new', args: ['--no-sandbox','--disable-gpu']
  });
  const page = await browser.newPage();
  page.on('console', msg => { if(msg.type()==='error') console.log('[CONSOLE ERROR]', msg.text()); });
  page.on('pageerror', err => console.log('[PAGE ERROR]', err.message));
  await page.setViewport({width:1440, height:900, deviceScaleFactor:1});
  await page.goto('http://127.0.0.1:8000', {waitUntil:'networkidle2', timeout:30000});
  await page.evaluate(() => {
    localStorage.setItem('pbc_onboarded','1');
    localStorage.setItem('pbc_current_project','demo');
  });
  await page.reload({waitUntil:'networkidle2', timeout:30000});
  await new Promise(r => setTimeout(r, 4000));

  // 辅助：检查某元素的 computed display 和是否错位
  const checkEl = async (selector, desc) => {
    const result = await page.evaluate((sel) => {
      const el = document.querySelector(sel);
      if (!el) return {found: false};
      const cs = getComputedStyle(el);
      const rect = el.getBoundingClientRect();
      const children = [...el.children].map(c => {
        const r = c.getBoundingClientRect();
        return {tag: c.tagName, text: (c.textContent||'').trim().slice(0,30), x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width)};
      });
      return {
        found: true,
        display: cs.display,
        alignItems: cs.alignItems,
        gap: cs.gap,
        width: cs.width,
        height: cs.height,
        childCount: el.children.length,
        children: children.slice(0, 6),
      };
    }, selector);
    console.log(`\n--- ${desc} (${selector}) ---`);
    if (!result.found) { console.log('  NOT FOUND'); return; }
    console.log(`  display=${result.display} alignItems=${result.alignItems} gap=${result.gap}`);
    console.log(`  children=${result.childCount}`);
    result.children.forEach((c,i) => console.log(`    [${i}] ${c.tag} "${c.text}" x=${c.x} y=${c.y} w=${c.w}`));
    
    // 判断是否错位：display 不是 flex/grid 但有 align-items/gap → 可能退化
    const degraded = result.display !== 'flex' && result.display !== 'grid' && result.display !== 'inline-flex';
    if (degraded) console.log(`  ⚠️ 可能退化! display=${result.display} (应为 flex)`);
    else console.log(`  ✓ display 正常`);
    return result;
  };

  // 1. 消息中心面板 (line 506)
  console.log('\n===== 1. 消息中心面板 =====');
  await page.evaluate(() => {
    const el = document.querySelector('[x-data="pbcApp()"]');
    if (el && el._x_dataStack) el._x_dataStack[0].messageCenter.show = true;
  });
  await new Promise(r => setTimeout(r, 500));
  await checkEl('[x-show="messageCenter.show"]', '消息中心面板');
  await page.screenshot({path:'D:/AgentProjects/IpoPBC/screenshots/diag_msg_center.png'});
  await page.evaluate(() => {
    const el = document.querySelector('[x-data="pbcApp()"]');
    if (el && el._x_dataStack) el._x_dataStack[0].messageCenter.show = false;
  });
  await new Promise(r => setTimeout(r, 300));

  // 2. 文件变更面板 (line 594) - 内层面板
  console.log('\n===== 2. 文件变更面板 =====');
  await page.evaluate(() => {
    const el = document.querySelector('[x-data="pbcApp()"]');
    if (el && el._x_dataStack) el._x_dataStack[0].changePanel.show = true;
  });
  await new Promise(r => setTimeout(r, 500));
  // 查内层面板（594行那个，有 display:flex;flex-direction:column）
  const changePanelInner = await page.evaluate(() => {
    const divs = document.querySelectorAll('div[x-show="changePanel.show"]');
    // 第二个是内层面板
    if (divs.length >= 2) {
      const el = divs[1];
      const cs = getComputedStyle(el);
      return {display: cs.display, flexDirection: cs.flexDirection, found: true};
    }
    return {found: false};
  });
  console.log('  内层面板:', JSON.stringify(changePanelInner));
  if (changePanelInner.found && changePanelInner.display !== 'flex') {
    console.log(`  ⚠️ 内层面板 display=${changePanelInner.display} (应为 flex)`);
  } else {
    console.log('  ✓ 内层面板 display 正常');
  }
  await page.screenshot({path:'D:/AgentProjects/IpoPBC/screenshots/diag_change_panel.png'});
  await page.evaluate(() => {
    const el = document.querySelector('[x-data="pbcApp()"]');
    if (el && el._x_dataStack) el._x_dataStack[0].changePanel.show = false;
  });
  await new Promise(r => setTimeout(r, 300));

  // 3. 三个文件区信息条 (line 1347/1354/1358)
  console.log('\n===== 3. 文件区信息条 =====');
  // 切到 files tab
  await page.evaluate(() => {
    const el = document.querySelector('[x-data="pbcApp()"]');
    if (el && el._x_dataStack) el._x_dataStack[0].switchTab('files');
  });
  await new Promise(r => setTimeout(r, 500));
  const infoBars = await page.evaluate(() => {
    const divs = [...document.querySelectorAll('div[x-show]')];
    // 找文件区那三个信息条
    const bars = divs.filter(d => {
      const xs = d.getAttribute('x-show') || '';
      return xs.includes('fileZone.paths') && d.style.display.includes('flex');
    });
    return bars.map(b => {
      const cs = getComputedStyle(b);
      return {
        xshow: b.getAttribute('x-show').slice(0,50),
        display: cs.display,
        visible: cs.display !== 'none',
      };
    });
  });
  infoBars.forEach((b,i) => {
    console.log(`  [${i}] x-show="${b.xshow}..." display=${b.display} visible=${b.visible}`);
    if (b.visible && b.display !== 'flex') console.log(`    ⚠️ 退化! display=${b.display}`);
    else if (b.visible) console.log(`    ✓ 正常`);
  });
  await page.screenshot({path:'D:/AgentProjects/IpoPBC/screenshots/diag_file_info.png'});

  // 4. 消息中心折叠/展开项 (line 537/571)
  console.log('\n===== 4. 消息中心列表项 =====');
  await page.evaluate(() => {
    const el = document.querySelector('[x-data="pbcApp()"]');
    if (el && el._x_dataStack) el._x_dataStack[0].messageCenter.show = true;
  });
  await new Promise(r => setTimeout(r, 500));
  const msgItems = await page.evaluate(() => {
    const divs = [...document.querySelectorAll('div[x-show]')];
    const items = divs.filter(d => {
      const xs = d.getAttribute('x-show') || '';
      return (xs === 'm.collapsed' || xs === '!m.collapsed && !m.items');
    });
    return items.map(b => {
      const cs = getComputedStyle(b);
      return {
        xshow: b.getAttribute('x-show'),
        display: cs.display,
        visible: cs.display !== 'none',
      };
    });
  });
  if (msgItems.length === 0) console.log('  没有消息项（可能没有数据）');
  msgItems.forEach((b,i) => {
    console.log(`  [${i}] x-show="${b.xshow}" display=${b.display} visible=${b.visible}`);
    if (b.visible && b.display !== 'flex') console.log(`    ⚠️ 退化!`);
    else if (b.visible) console.log(`    ✓ 正常`);
  });
  await page.evaluate(() => {
    const el = document.querySelector('[x-data="pbcApp()"]');
    if (el && el._x_dataStack) el._x_dataStack[0].messageCenter.show = false;
  });

  // 5. 未读徽章 (line 1236)
  console.log('\n===== 5. 未读徽章 =====');
  const badge = await page.evaluate(() => {
    const el = document.querySelector('span[x-show="changePanel.unread>0"]');
    if (!el) return {found: false};
    const cs = getComputedStyle(el);
    return {found: true, display: cs.display, visible: cs.display !== 'none'};
  });
  console.log(`  found=${badge.found} display=${badge.display} visible=${badge.visible}`);
  if (badge.found && badge.visible && badge.display !== 'flex') {
    console.log(`  ⚠️ 退化! display=${badge.display}`);
  } else if (badge.found && badge.visible) {
    console.log('  ✓ 正常');
  }

  // 6. 逐个打开所有 overlay modal
  console.log('\n===== 6. 所有 overlay modal =====');
  const modals = [
    {name: 'folderConfig', expr: 'folderConfig.show'},
    {name: 'aiConfig', expr: 'aiConfig.show'},
    {name: 'relocateModal', expr: 'relocateModal.show'},
    {name: 'reclassifyModal', expr: 'reclassifyModal.show'},
    {name: 'testDataModal', expr: 'testDataModal.show'},
    {name: 'showCreateProject', expr: 'showCreateProject'},
    {name: 'resolveModal', expr: 'resolveModal.show'},
    {name: 'escalationModal', expr: 'escalationModal.show'},
    {name: 'fileDetail', expr: 'fileDetail.show'},
    {name: 'renameProjectModal', expr: 'renameProjectModal.show'},
    {name: 'deleteProjectModal', expr: 'deleteProjectModal.show'},
    {name: 'showProjectDrawer', expr: 'showProjectDrawer'},
    {name: 'showOnboarding', expr: 'showOnboarding'},
  ];
  for (const m of modals) {
    await page.evaluate((name, expr) => {
      const el = document.querySelector('[x-data="pbcApp()"]');
      if (!el || !el._x_dataStack) return;
      const d = el._x_dataStack[0];
      // 用 expr 找属性
      if (expr.includes('.')) {
        const parts = expr.split('.');
        let obj = d;
        for (let i = 0; i < parts.length - 1; i++) obj = obj[parts[i]];
        if (obj) obj[parts[parts.length-1]] = true;
      } else {
        d[expr] = true;
      }
    }, m.name, m.expr);
    await new Promise(r => setTimeout(r, 500));
    const result = await page.evaluate((expr) => {
      const el = document.querySelector(`[x-show="${expr}"]`);
      if (!el) return {found: false};
      const cs = getComputedStyle(el);
      return {found: true, display: cs.display, classList: el.className};
    }, m.expr);
    const ok = result.found && (result.display === 'flex' || result.display === 'none');
    console.log(`  ${m.name}: display=${result.display} classes="${result.classList}" ${ok ? '✓' : '⚠️'}`);
    
    await page.evaluate((expr) => {
      const el = document.querySelector('[x-data="pbcApp()"]');
      if (!el || !el._x_dataStack) return;
      const d = el._x_dataStack[0];
      if (expr.includes('.')) {
        const parts = expr.split('.');
        let obj = d;
        for (let i = 0; i < parts.length - 1; i++) obj = obj[parts[i]];
        if (obj) obj[parts[parts.length-1]] = false;
      } else {
        d[expr] = false;
      }
    }, m.expr);
    await new Promise(r => setTimeout(r, 300));
  }

  console.log('\n===== 诊断完成 =====');
  await browser.close();
})();
