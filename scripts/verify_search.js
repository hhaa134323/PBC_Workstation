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

  // 切到 triage tab
  await page.evaluate(() => { const el=document.querySelector('[x-data]'); if(el&&el._x_dataStack) el._x_dataStack[0].switchTab('triage'); });
  await new Promise(r => setTimeout(r, 1000));

  // 找搜索框
  const input = await page.$('input[placeholder*="搜索"]');
  if (!input) { console.log('搜索框没找到'); await browser.close(); return; }

  console.log('=== 搜索框输入测试 ===');

  // 模拟连续输入
  await input.click();
  await input.type('a', {delay: 50});
  await new Promise(r => setTimeout(r, 300));
  const val1 = await page.evaluate(() => document.querySelector('input[placeholder*="搜索"]').value);
  const focus1 = await page.evaluate(() => document.activeElement === document.querySelector('input[placeholder*="搜索"]'));
  console.log('输入 "a": value=' + val1 + ' focused=' + focus1);

  await input.type('b', {delay: 50});
  await new Promise(r => setTimeout(r, 300));
  const val2 = await page.evaluate(() => document.querySelector('input[placeholder*="搜索"]').value);
  const focus2 = await page.evaluate(() => document.activeElement === document.querySelector('input[placeholder*="搜索"]'));
  console.log('输入 "ab": value=' + val2 + ' focused=' + focus2);

  await input.type('c', {delay: 50});
  await new Promise(r => setTimeout(r, 300));
  const val3 = await page.evaluate(() => document.querySelector('input[placeholder*="搜索"]').value);
  const focus3 = await page.evaluate(() => document.activeElement === document.querySelector('input[placeholder*="搜索"]'));
  console.log('输入 "abc": value=' + val3 + ' focused=' + focus3);

  // 检查表格是否过滤了
  const rowCount = await page.evaluate(() => document.querySelectorAll('.tbl tbody tr').length);
  const filterInfo = await page.evaluate(() => { const el = document.querySelector('.filter-info'); return el ? el.textContent.trim() : 'not found'; });
  console.log('表格行数: ' + rowCount + ' 筛选信息: ' + filterInfo);

  const ok = val3 === 'abc' && focus3;
  console.log(ok ? '✓ 搜索框可正常连续输入' : '✗ 搜索框有问题');
  console.log('Console errors: ' + consoleErrors);
  await browser.close();
})();
