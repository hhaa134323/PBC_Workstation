const puppeteer = require('puppeteer-core');
(async () => {
  const browser = await puppeteer.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:'new',args:['--no-sandbox','--disable-gpu']});
  const page = await browser.newPage();
  let consoleErrors = 0;
  page.on('console', msg => { if(msg.type()==='error') consoleErrors++; });
  page.on('pageerror', () => consoleErrors++);
  await page.setViewport({width:1440,height:900});
  await page.goto('http://127.0.0.1:8000',{waitUntil:'networkidle2',timeout:30000});
  await page.evaluate(() => { localStorage.setItem('pbc_onboarded','1'); localStorage.setItem('pbc_current_project','demo'); });
  await page.reload({waitUntil:'networkidle2',timeout:30000});
  await new Promise(r => setTimeout(r, 4000));

  // 展开大卡片
  await page.evaluate(() => { const el=document.querySelector('[x-data]'); if(el&&el._x_dataStack) el._x_dataStack[0].briefFolded = false; });
  await new Promise(r => setTimeout(r, 800));

  // 1. 四条验收命令
  console.log('=== 验收命令 ===');
  const checks = await page.evaluate(() => {
    const body = document.querySelector('.bc-body');
    const rows = document.querySelectorAll('.bc-row');
    const alerts = document.querySelectorAll('.bc-alert');
    const gc = document.querySelector('.bc-gc');
    return {
      display: body ? getComputedStyle(body).display : 'not found',
      rowCount: rows.length,
      alertCount: alerts.length,
      gcText: gc ? gc.textContent : 'not found',
    };
  });
  console.log('1. getComputedStyle(.bc-body).display =', checks.display, checks.display === 'flex' ? '✓' : '✗');
  console.log('2. .bc-row length =', checks.rowCount, checks.rowCount === 7 ? '✓' : '✗ (期望7)');
  console.log('3. .bc-alert length =', checks.alertCount, checks.alertCount === 1 ? '✓' : '✗ (期望1)');
  console.log('4. .bc-gc textContent =', checks.gcText, checks.gcText === '7' ? '✓' : '✗ (期望"7")');

  // 2. 展开收起来回
  console.log('\n=== 展开/收起回归 ===');
  let allOk = true;
  for (let i = 1; i <= 3; i++) {
    // 收起
    await page.evaluate(() => { const el=document.querySelector('[x-data]'); if(el&&el._x_dataStack) el._x_dataStack[0].briefFolded = true; });
    await new Promise(r => setTimeout(r, 400));
    const foldedDisplay = await page.evaluate(() => { const el=document.querySelector('.brief-bar'); return el ? getComputedStyle(el).display : 'nf'; });
    // 展开
    await page.evaluate(() => { const el=document.querySelector('[x-data]'); if(el&&el._x_dataStack) el._x_dataStack[0].briefFolded = false; });
    await new Promise(r => setTimeout(r, 400));
    const unfoldDisplay = await page.evaluate(() => { const el=document.querySelector('.bc-body'); return el ? getComputedStyle(el).display : 'nf'; });
    const ok = foldedDisplay === 'flex' && unfoldDisplay === 'flex';
    console.log(`  第${i}次: 收起=${foldedDisplay} 展开=${unfoldDisplay} ${ok?'✓':'✗'}`);
    if (!ok) allOk = false;
  }

  // 3. 点"去风险分析"
  console.log('\n=== 去风险分析 ===');
  await page.evaluate(() => { const el=document.querySelector('.bc-go'); if(el) el.click(); });
  await new Promise(r => setTimeout(r, 500));
  const tab = await page.evaluate(() => { const el=document.querySelector('[x-data]'); if(el&&el._x_dataStack) return el._x_dataStack[0].currentTab; return 'nf'; });
  console.log('  currentTab =', tab, tab === 'overdue' ? '✓' : '✗');

  // 4. 截图给视觉模型
  await page.evaluate(() => { const el=document.querySelector('[x-data]'); if(el&&el._x_dataStack){ el._x_dataStack[0].briefFolded = false; el._x_dataStack[0].currentTab = 'triage'; } });
  await new Promise(r => setTimeout(r, 500));
  await page.evaluate(() => { const el=document.querySelector('[x-data]'); if(el&&el._x_dataStack) el._x_dataStack[0].briefFolded = false; });
  await new Promise(r => setTimeout(r, 500));
  await page.screenshot({path:'D:/AgentProjects/IpoPBC/screenshots/brief_card_after.png'});

  console.log(`\nConsole errors: ${consoleErrors}`);
  await browser.close();
})();
