const puppeteer = require('puppeteer-core');
(async () => {
  const browser = await puppeteer.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:'new',args:['--no-sandbox','--disable-gpu']});
  const page = await browser.newPage();
  await page.setViewport({width:1440,height:900});
  await page.goto('http://127.0.0.1:8000',{waitUntil:'networkidle2',timeout:30000});
  await page.evaluate(() => { localStorage.setItem('pbc_onboarded','1'); localStorage.setItem('pbc_current_project','demo'); });
  await page.reload({waitUntil:'networkidle2',timeout:30000});
  await new Promise(r => setTimeout(r, 4000));
  await page.evaluate(() => { const el=document.querySelector('[x-data]'); if(el&&el._x_dataStack) el._x_dataStack[0].switchTab('review'); });
  await new Promise(r => setTimeout(r, 1000));
  await page.screenshot({path:'D:/AgentProjects/IpoPBC/screenshots/pending_archive_tab.png'});
  console.log('done');
  await browser.close();
})();
