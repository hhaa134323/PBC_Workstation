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
  const el = await page.$('div[x-show*="briefFolded"]');
  if (el) {
    const box = await el.boundingBox();
    if (box) {
      await page.screenshot({path:'D:/AgentProjects/IpoPBC/screenshots/brief_bar_zoom.png', clip:{x:0,y:Math.max(0,box.y-10),width:1440,height:box.height+20}});
      console.log('clipped:', box.y, box.height);
    }
  }
  await page.screenshot({path:'D:/AgentProjects/IpoPBC/screenshots/brief_full2.png', fullPage:false});
  console.log('done');
  await browser.close();
})();
