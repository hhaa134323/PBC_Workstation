const puppeteer = require('puppeteer-core');
(async () => {
  const browser = await puppeteer.launch({
    executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe',
    headless: 'new', args: ['--no-sandbox','--disable-gpu']
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

  // 打开文件变更面板
  console.log('\n===== 文件变更面板深度诊断 =====');
  await page.evaluate(() => {
    const el = document.querySelector('[x-data="pbcApp()"]');
    if (el && el._x_dataStack) el._x_dataStack[0].changePanel.show = true;
  });
  await new Promise(r => setTimeout(r, 800));

  // 查所有 x-show="changePanel.show" 的元素
  const result = await page.evaluate(() => {
    const divs = [...document.querySelectorAll('[x-show="changePanel.show"]')];
    return divs.map((d,i) => {
      const cs = getComputedStyle(d);
      const rect = d.getBoundingClientRect();
      return {
        idx: i,
        tag: d.tagName,
        classes: d.className,
        display: cs.display,
        flexDirection: cs.flexDirection,
        style: d.getAttribute('style'),
        x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height),
        childCount: d.children.length,
      };
    });
  });
  result.forEach(r => console.log(JSON.stringify(r, null, 2)));

  // 也检查消息中心折叠/展开项（造一些假消息数据）
  console.log('\n===== 消息中心列表项（造数据）=====');
  await page.evaluate(() => {
    const el = document.querySelector('[x-data="pbcApp()"]');
    if (el && el._x_dataStack) {
      const d = el._x_dataStack[0];
      d.messageCenter.show = true;
      // 造几条假消息
      d.messageCenter.items = [
        {id:1, type:'needs_confirm', collapsed:false, title:'测试消息1', body:'这是一个测试', time:'刚刚', item_id:'历-1', action:'去确认'},
        {id:2, type:'file_classified', collapsed:true, title:'测试消息2', body:'另一个测试', time:'5分钟前'},
      ];
    }
  });
  await new Promise(r => setTimeout(r, 500));
  
  const msgResult = await page.evaluate(() => {
    const divs = [...document.querySelectorAll('div[x-show]')];
    const items = divs.filter(d => {
      const xs = d.getAttribute('x-show') || '';
      return xs === 'm.collapsed' || xs === '!m.collapsed && !m.items';
    });
    return items.map(b => {
      const cs = getComputedStyle(b);
      return {
        xshow: b.getAttribute('x-show'),
        display: cs.display,
        visible: cs.display !== 'none',
        style: b.getAttribute('style')?.slice(0,80),
      };
    });
  });
  msgResult.forEach(r => console.log(JSON.stringify(r)));
  
  // 检查文件区三个信息条
  console.log('\n===== 文件区信息条 =====');
  await page.evaluate(() => {
    const el = document.querySelector('[x-data="pbcApp()"]');
    if (el && el._x_dataStack) {
      const d = el._x_dataStack[0];
      d.switchTab('files');
      // 确保 fileZone.paths 有数据
      if (!d.fileZone.paths) d.fileZone.paths = {client_folder: {path:'/test', exists:true}};
    }
  });
  await new Promise(r => setTimeout(r, 500));
  const fileInfo = await page.evaluate(() => {
    const divs = [...document.querySelectorAll('div[x-show]')];
    const bars = divs.filter(d => {
      const xs = d.getAttribute('x-show') || '';
      return xs.includes('fileZone.paths');
    });
    return bars.map(b => {
      const cs = getComputedStyle(b);
      return {
        xshow: b.getAttribute('x-show').slice(0,60),
        display: cs.display,
        visible: cs.display !== 'none',
      };
    });
  });
  fileInfo.forEach(r => console.log(JSON.stringify(r)));

  await page.screenshot({path:'D:/AgentProjects/IpoPBC/screenshots/diag_change_panel_open.png'});
  console.log('\ndone');
  await browser.close();
})();
