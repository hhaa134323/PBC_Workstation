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

  // 1. 横条存在且可见
  const bar = await page.evaluate(() => {
    const el = document.querySelector('.brief-bar');
    if (!el) return {found: false};
    const cs = getComputedStyle(el);
    return {found: true, display: cs.display, text: el.textContent.trim().slice(0,80)};
  });
  console.log('1. 横条:', JSON.stringify(bar));

  // 2. 展开态大卡片不存在
  const card = await page.evaluate(() => {
    const el = document.querySelector('.bc-body');
    return el ? 'EXISTS' : 'GONE';
  });
  console.log('2. 展开态:', card, card === 'GONE' ? '✓' : '✗');

  // 3. 点击横条 → openChangePanel
  await page.click('.brief-bar');
  await new Promise(r => setTimeout(r, 800));
  const changePanel = await page.evaluate(() => {
    const el = document.querySelector('[x-data]');
    if (!el || !el._x_dataStack) return 'no alpine';
    return el._x_dataStack[0].changePanel.show;
  });
  console.log('3. 点击后 changePanel.show =', changePanel, changePanel === true ? '✓' : '✗');

  // 4. 截图给视觉模型
  await page.screenshot({path:'D:/AgentProjects/IpoPBC/screenshots/brief_bar_only.png'});
  console.log('4. 截图完成');

  console.log('\nConsole errors:', consoleErrors);
  await browser.close();
})();
