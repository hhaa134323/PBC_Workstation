const puppeteer = require('puppeteer-core');

(async () => {
  const browser = await puppeteer.launch({
    executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe',
    headless: 'new',
    args: ['--no-sandbox','--disable-gpu']
  });
  const page = await browser.newPage();
  await page.setViewport({width:1440, height:900, deviceScaleFactor:1});
  page.on('console', msg => console.log('[CONSOLE]', msg.text()));
  page.on('pageerror', err => console.log('[ERROR]', err.message));

  await page.goto('http://127.0.0.1:8000', {waitUntil:'networkidle2', timeout:30000});
  await page.evaluate(() => {
    localStorage.setItem('pbc_onboarded','1');
    localStorage.setItem('pbc_current_project','demo');
  });
  await page.reload({waitUntil:'networkidle2', timeout:30000});
  await new Promise(r => setTimeout(r, 4000));

  // 找到简报细条容器
  const diag = await page.evaluate(() => {
    const allDivs = document.querySelectorAll('div[x-show]');
    let bar = null;
    for (const d of allDivs) {
      if (d.getAttribute('x-show').includes('briefFolded') && d.getAttribute('x-show').includes('briefFolded')) {
        // 只取第一个（收起态）
        bar = d;
        break;
      }
    }
    if (!bar) return {error: 'brief bar not found'};

    const cs = window.getComputedStyle(bar);
    const rect = bar.getBoundingClientRect();
    const children = [...bar.children];

    return {
      bar: {
        tag: bar.tagName,
        classes: bar.className,
        x_show: bar.getAttribute('x-show'),
        display: cs.display,
        alignItems: cs.alignItems,
        gap: cs.gap,
        padding: cs.padding,
        width: cs.width,
        height: cs.height,
        bbox: {x: rect.x, y: rect.y, w: rect.width, h: rect.height},
      },
      children: children.map(c => {
        const ccs = window.getComputedStyle(c);
        const crect = c.getBoundingClientRect();
        return {
          text: (c.textContent || '').trim().slice(0,60),
          display: ccs.display,
          flex: ccs.flex,
          flexShrink: ccs.flexShrink,
          flexGrow: ccs.flexGrow,
          flexBasis: ccs.flexBasis,
          fontSize: ccs.fontSize,
          color: ccs.color,
          width: ccs.width,
          height: ccs.height,
          marginLeft: ccs.marginLeft,
          marginRight: ccs.marginRight,
          opacity: ccs.opacity,
          overflow: ccs.overflow,
          textOverflow: ccs.textOverflow,
          whiteSpace: ccs.whiteSpace,
          bbox: {x: crect.x, y: crect.y, w: crect.width, h: crect.height},
        };
      })
    };
  });

  console.log('\n=== 简报细条诊断 ===');
  console.log(JSON.stringify(diag, null, 2));

  // 额外查 Alpine state
  const alpineState = await page.evaluate(() => {
    const el = document.querySelector('[x-data="pbcApp()"]');
    if (!el || !el._x_dataStack) return null;
    const d = el._x_dataStack[0];
    return {
      briefFolded: d.briefFolded,
      briefHasDelta: d.briefHasDelta,
      briefSeenStr: d.briefSeenStr,
      briefingDelta: d.briefingDelta ? {
        delta_count: d.briefingDelta.delta_count,
        has_delta: d.briefingDelta.has_delta,
        groups: (d.briefingDelta.delta_groups||[]).map(g=>({label:g.label,count:g.count})),
        stock_total: d.briefingDelta.stock_total,
      } : null,
    };
  });
  console.log('\n=== Alpine State ===');
  console.log(JSON.stringify(alpineState, null, 2));

  await browser.close();
})();
