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

  // 切到 overdue tab（一定有数据）
  await page.evaluate(() => { const el=document.querySelector('[x-data]'); if(el&&el._x_dataStack) el._x_dataStack[0].switchTab('overdue'); });
  await new Promise(r => setTimeout(r, 1000));

  // 找搜索框并输入
  const testInput = async (text) => {
    return await page.evaluate((t) => {
      const input = document.querySelector('input[placeholder*="搜索"]');
      if (!input) return {error: 'input not found'};
      input.focus();
      // 模拟逐字输入
      const oldVal = input.value || '';
      const newVal = oldVal + t;
      input.value = newVal;
      input.dispatchEvent(new Event('input', {bubbles: true}));
      return {value: input.value, focused: document.activeElement === input};
    }, text);
  };

  console.log('=== 搜索框连续输入测试 ===');
  
  const r1 = await testInput('a');
  console.log('输入 a:', JSON.stringify(r1));
  await new Promise(r => setTimeout(r, 300));
  
  const r2 = await testInput('b');
  console.log('输入 ab:', JSON.stringify(r2));
  await new Promise(r => setTimeout(r, 300));
  
  const r3 = await testInput('c');
  console.log('输入 abc:', JSON.stringify(r3));
  await new Promise(r => setTimeout(r, 500));

  // 检查表格和筛选信息
  const filterInfo = await page.evaluate(() => { const el = document.querySelector('.filter-info'); return el ? el.textContent.trim() : 'not found'; });
  const rowCount = await page.evaluate(() => { const trs = document.querySelectorAll('.tbl tbody tr'); return trs.length; });
  console.log('筛选信息:', filterInfo);
  console.log('表格行数:', rowCount);
  
  const ok = r3.value === 'abc' && r3.focused;
  console.log(ok ? '✓ 搜索框可正常连续输入，焦点保持' : '✗ 搜索框有问题');
  console.log('Console errors:', consoleErrors);
  await browser.close();
})();
