const puppeteer = require('puppeteer-core');
(async () => {
  const browser = await puppeteer.launch({
    executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe',
    headless: 'new', args: ['--no-sandbox','--disable-gpu']
  });
  const page = await browser.newPage();
  let consoleErrors = 0;
  page.on('console', msg => { if(msg.type()==='error') consoleErrors++; });
  page.on('pageerror', () => consoleErrors++);
  await page.setViewport({width:1440, height:900, deviceScaleFactor:1});
  await page.goto('http://127.0.0.1:8000', {waitUntil:'networkidle2', timeout:30000});
  await page.evaluate(() => {
    localStorage.setItem('pbc_onboarded','1');
    localStorage.setItem('pbc_current_project','demo');
  });
  await page.reload({waitUntil:'networkidle2', timeout:30000});
  await new Promise(r => setTimeout(r, 4000));

  const setProp = async (expr, val) => {
    await page.evaluate((e, v) => {
      const el = document.querySelector('[x-data]');
      if (!el || !el._x_dataStack) return;
      const d = el._x_dataStack[0];
      if (e.includes('.')) {
        const p = e.split('.');
        let o = d;
        for (let i = 0; i < p.length-1; i++) o = o[p[i]];
        if (o) o[p[p.length-1]] = v;
      } else {
        d[e] = v;
      }
    }, expr, val);
  };

  // 文件变更面板 - 查所有 x-show="changePanel.show" 的元素
  console.log('=== 文件变更面板 ===');
  for (let i = 1; i <= 3; i++) {
    await setProp('changePanel.show', true);
    await new Promise(r => setTimeout(r, 500));
    const states = await page.evaluate(() => {
      const divs = [...document.querySelectorAll('[x-show="changePanel.show"]')];
      return divs.map(d => ({cls: d.className, display: getComputedStyle(d).display}));
    });
    await setProp('changePanel.show', false);
    await new Promise(r => setTimeout(r, 300));
    console.log(`  第${i}次: ${states.map(s=>s.cls+':'+s.display).join(' | ')}`);
  }

  // 所有 overlay modal
  console.log('\n=== overlay modal ===');
  const modals = ['folderConfig.show','aiConfig.show','relocateModal.show','reclassifyModal.show','testDataModal.show','showCreateProject','resolveModal.show','escalationModal.show','fileDetail.show','renameProjectModal.show','deleteProjectModal.show','showProjectDrawer','showOnboarding'];
  for (const expr of modals) {
    await setProp(expr, true);
    await new Promise(r => setTimeout(r, 400));
    const display = await page.evaluate((e) => {
      const el = document.querySelector(`[x-show="${e}"]`);
      return el ? getComputedStyle(el).display : 'nf';
    }, expr);
    await setProp(expr, false);
    await new Promise(r => setTimeout(r, 300));
    console.log(`  ${expr}: ${display} ${display==='flex'?'✓':'?'}`);
  }

  console.log(`\nConsole errors (已有 null 引用): ${consoleErrors}`);
  await browser.close();
})();
