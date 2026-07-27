const puppeteer = require('puppeteer-core');
(async () => {
  const browser = await puppeteer.launch({
    executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe',
    headless: 'new', args: ['--no-sandbox','--disable-gpu']
  });
  const page = await browser.newPage();
  let consoleErrors = 0;
  page.on('console', msg => { if(msg.type()==='error') { console.log('[CONSOLE ERROR]', msg.text()); consoleErrors++; } });
  page.on('pageerror', err => { console.log('[PAGE ERROR]', err.message); consoleErrors++; });
  await page.setViewport({width:1440, height:900, deviceScaleFactor:1});
  await page.goto('http://127.0.0.1:8000', {waitUntil:'networkidle2', timeout:30000});
  await page.evaluate(() => {
    localStorage.setItem('pbc_onboarded','1');
    localStorage.setItem('pbc_current_project','demo');
  });
  await page.reload({waitUntil:'networkidle2', timeout:30000});
  await new Promise(r => setTimeout(r, 4000));

  const setAlpine = async (code) => {
    return await page.evaluate(code);
  };

  // 1. 消息中心面板开关 3 次
  console.log('\n=== 1. 消息中心面板开关 3 次 ===');
  for (let i = 1; i <= 3; i++) {
    await setAlpine(() => { const el=document.querySelector('[x-data]'); if(el&&el._x_dataStack) el._x_dataStack[0].messageCenter.show=true; });
    await new Promise(r => setTimeout(r, 500));
    const open = await page.evaluate(() => { const el=document.querySelector('[x-show="messageCenter.show"]'); return el?getComputedStyle(el).display:'not found'; });
    await setAlpine(() => { const el=document.querySelector('[x-data]'); if(el&&el._x_dataStack) el._x_dataStack[0].messageCenter.show=false; });
    await new Promise(r => setTimeout(r, 300));
    const closed = await page.evaluate(() => { const el=document.querySelector('[x-show="messageCenter.show"]'); return el?getComputedStyle(el).display:'not found'; });
    console.log(`  第${i}次: 开=${open} 关=${closed} ${open==='flex'&&closed==='none'?'✓':'✗'}`);
  }

  // 2. 文件变更面板开关 3 次
  console.log('\n=== 2. 文件变更面板开关 3 次 ===');
  for (let i = 1; i <= 3; i++) {
    await setAlpine(() => { const el=document.querySelector('[x-data]'); if(el&&el._x_dataStack) el._x_dataStack[0].changePanel.show=true; });
    await new Promise(r => setTimeout(r, 500));
    // 内层面板
    const open = await page.evaluate(() => { const divs=[...document.querySelectorAll('[x-show="changePanel.show"]')]; return divs.length>=2?getComputedStyle(divs[1]).display:'not found'; });
    await setAlpine(() => { const el=document.querySelector('[x-data]'); if(el&&el._x_dataStack) el._x_dataStack[0].changePanel.show=false; });
    await new Promise(r => setTimeout(r, 300));
    const closed = await page.evaluate(() => { const divs=[...document.querySelectorAll('[x-show="changePanel.show"]')]; return divs.length>=2?getComputedStyle(divs[1]).display:'not found'; });
    console.log(`  第${i}次: 开=${open} 关=${closed} ${open==='flex'&&closed==='none'?'✓':'✗'}`);
  }

  // 3. 文件区信息条（切到 files tab）
  console.log('\n=== 3. 文件区信息条 ===');
  await setAlpine(() => { const el=document.querySelector('[x-data]'); if(el&&el._x_dataStack){el._x_dataStack[0].switchTab('files'); } });
  await new Promise(r => setTimeout(r, 500));
  const infoBar = await page.evaluate(() => {
    const el = document.querySelector('[x-show*="fileZone.paths"] [x-show*="client_folder.exists"], [x-show*="client_folder.exists"]');
    // 找带 d-flex 的那个
    const bars = [...document.querySelectorAll('.d-flex[x-show*="fileZone"]')];
    if (bars.length === 0) return {found: false, count: 0};
    const visible = bars.filter(b => getComputedStyle(b).display !== 'none');
    return {
      found: true,
      total: bars.length,
      visible: visible.length,
      display: visible.length > 0 ? getComputedStyle(visible[0]).display : 'none visible',
    };
  });
  console.log(`  found=${infoBar.found} total=${infoBar.total} visible=${infoBar.visible} display=${infoBar.display} ${infoBar.visible>0&&infoBar.display==='flex'?'✓':'(无可见项)'}`);

  // 4. 所有 overlay modal 开关各 1 次
  console.log('\n=== 4. 所有 overlay modal 开关 ===');
  const modals = ['folderConfig.show','aiConfig.show','relocateModal.show','reclassifyModal.show','testDataModal.show','showCreateProject','resolveModal.show','escalationModal.show','fileDetail.show','renameProjectModal.show','deleteProjectModal.show','showProjectDrawer','showOnboarding'];
  for (const expr of modals) {
    await setAlpine((e) => { const el=document.querySelector('[x-data]'); if(!el||!el._x_dataStack) return; const d=el._x_dataStack[0]; if(e.includes('.')){const p=e.split('.');let o=d;for(let i=0;i<p.length-1;i++)o=o[p[i]];if(o)o[p[p.length-1]]=true;}else{d[e]=true;} }, expr);
    await new Promise(r => setTimeout(r, 400));
    const open = await page.evaluate((e) => { const el=document.querySelector(`[x-show="${e}"]`); return el?getComputedStyle(el).display:'nf'; }, expr);
    await setAlpine((e) => { const el=document.querySelector('[x-data]'); if(!el||!el._x_dataStack) return; const d=el._x_dataStack[0]; if(e.includes('.')){const p=e.split('.');let o=d;for(let i=0;i<p.length-1;i++)o=o[p[i]];if(o)o[p[p.length-1]]=false;}else{d[e]=false;} }, expr);
    await new Promise(r => setTimeout(r, 300));
    console.log(`  ${expr}: 开=${open} ${open==='flex'?'✓':'?'}`);
  }

  console.log(`\n=== Console 报错数: ${consoleErrors} ===`);
  console.log(consoleErrors === 0 ? '✓ 零报错' : '⚠️ 有报错');
  await browser.close();
})();
