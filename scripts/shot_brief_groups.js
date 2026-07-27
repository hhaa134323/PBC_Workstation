const puppeteer = require('puppeteer-core');
(async () => {
  const browser = await puppeteer.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:'new',args:['--no-sandbox','--disable-gpu']});
  const page = await browser.newPage();
  await page.setViewport({width:1440,height:900});
  await page.goto('http://127.0.0.1:8000',{waitUntil:'networkidle2',timeout:30000});
  await page.evaluate(() => { localStorage.setItem('pbc_onboarded','1'); localStorage.setItem('pbc_current_project','demo'); });
  await page.reload({waitUntil:'networkidle2',timeout:30000});
  await new Promise(r => setTimeout(r, 4000));
  const msg = await page.evaluate(() => {
    const el = document.querySelector('.bb-msg');
    return el ? el.textContent.trim() : 'not found';
  });
  console.log('横条文案:', msg);
  await page.screenshot({path:'D:/AgentProjects/IpoPBC/screenshots/brief_bar_groups.png'});
  await browser.close();
})();
