const puppeteer = require('puppeteer-core');

(async () => {
  const browser = await puppeteer.launch({
    executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe',
    headless: 'new',
    args: ['--no-sandbox','--disable-gpu']
  });
  const page = await browser.newPage();
  await page.setViewport({width:1440, height:900, deviceScaleFactor:1});
  await page.goto('http://127.0.0.1:8000', {waitUntil:'networkidle2', timeout:30000});
  await page.evaluate(() => {
    localStorage.setItem('pbc_onboarded','1');
    localStorage.setItem('pbc_current_project','demo');
  });
  await page.reload({waitUntil:'networkidle2', timeout:30000});
  await new Promise(r => setTimeout(r, 4000));

  // ===== A. 4 条验收命令 =====
  console.log('\n===== A. 验收命令 =====');
  const checks = await page.evaluate(() => {
    const bar = document.querySelector('.brief-bar');
    if (!bar) return {error: '.brief-bar not found'};
    return {
      display: getComputedStyle(bar).display,
      height: getComputedStyle(bar).height,
      flexGrow: getComputedStyle(bar.querySelector('.bb-msg')).flexGrow,
      styleAttr: bar.getAttribute('style'),
    };
  });
  console.log('1. display      =', checks.display,    checks.display === 'flex' ? '✓' : '✗');
  console.log('2. height       =', checks.height,     checks.height === '50px' ? '✓' : '✗');
  console.log('3. flexGrow     =', checks.flexGrow,   checks.flexGrow === '1' ? '✓' : '✗');
  console.log('4. style attr   =', checks.styleAttr,  checks.styleAttr === null || !/display/i.test(checks.styleAttr||'') ? '✓ (null or no display)' : '✗ CONTAINS display');

  // ===== B. 反复展开/收起 5 次 =====
  console.log('\n===== B. 展开/收起回归（5 次）=====');
  let allOk = true;
  for (let i = 1; i <= 5; i++) {
    // 先点展开（收起态细条可见时点击）
    const foldedVisible = await page.evaluate(() => {
      const bar = document.querySelector('.brief-bar');
      return bar && getComputedStyle(bar).display !== 'none';
    });
    if (foldedVisible) {
      await page.click('.brief-bar');
      await new Promise(r => setTimeout(r, 500));
    }

    // 再点收起（展开态的收起按钮）
    const unfoldVisible = await page.evaluate(() => {
      const btns = [...document.querySelectorAll('button')];
      const btn = btns.find(b => b.textContent.trim() === '收起');
      return btn && getComputedStyle(btn).display !== 'none' && btn.offsetParent !== null;
    });
    if (unfoldVisible) {
      await page.evaluate(() => {
        const btns = [...document.querySelectorAll('button')];
        const btn = btns.find(b => b.textContent.trim() === '收起');
        if (btn) btn.click();
      });
      await new Promise(r => setTimeout(r, 500));
    }

    // 验证收起态布局没退化
    const result = await page.evaluate(() => {
      const bar = document.querySelector('.brief-bar');
      if (!bar) return {error: 'bar not found after toggle'};
      const cs = getComputedStyle(bar);
      return {
        display: cs.display,
        height: cs.height,
        flexGrow: getComputedStyle(bar.querySelector('.bb-msg')).flexGrow,
        styleAttr: bar.getAttribute('style'),
      };
    });

    const ok = result.display === 'flex' && result.height === '50px' && result.flexGrow === '1'
      && (result.styleAttr === null || !/display/i.test(result.styleAttr||''));
    console.log(`  第${i}次: display=${result.display} height=${result.height} flexGrow=${result.flexGrow} style=${result.styleAttr} ${ok?'✓':'✗ 退化!'}`);
    if (!ok) allOk = false;
  }
  console.log('\n回归结果:', allOk ? '✓ 5 次全部通过，布局未退化' : '✗ 有退化');

  await browser.close();
})();
