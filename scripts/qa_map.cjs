const {chromium} = require(process.env.PLAYWRIGHT_MODULE);
const assert = require('node:assert/strict');
(async () => {
 const browser = await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true,args:['--enable-unsafe-swiftshader']});
 try {
 const page = await browser.newPage({viewport:{width:1440,height:1050}});
 const errors=[]; const tileHosts=new Set(); let successfulTiles=0;
 page.on('pageerror', e=>errors.push(e.message));
 page.on('request', r=>{if(/openstreetmap\.org|openfreemap\.org/.test(r.url())) tileHosts.add(new URL(r.url()).hostname)});
 page.on('response', r=>{if(r.url().includes('tiles.openfreemap.org') && r.status()===200) successfulTiles++});
 await page.goto('http://127.0.0.1:5055/login');
 await page.locator('#username').fill('RescueEchague'); await page.locator('#password').fill('map-browser-check');
 await Promise.all([page.waitForURL('http://127.0.0.1:5055/'),page.locator('button[type=submit]').click()]);
 await page.goto('http://127.0.0.1:5055/map');
 await page.waitForFunction(()=>document.querySelector('#map-status').textContent.includes('crashes represented by barangay area'),null,{timeout:30000});
 await page.waitForFunction(()=>document.querySelector('#m-year').options.length>1);
 await page.screenshot({path:'docs/map-desktop.png',fullPage:true});
 console.log(await page.locator('#map-coverage').innerText());
 await page.locator('#m-points').check();
 const change = async action=>{await Promise.all([page.waitForResponse(r=>r.url().includes('/api/map/summary') && r.status()===200),action()]);};
 await change(()=>page.locator('#m-severity').selectOption('Fatal'));
 await change(()=>page.locator('#map-ranking button').first().click());
 await change(()=>page.locator('#m-reset').click());
 await page.setViewportSize({width:390,height:844});
 await page.waitForTimeout(600);
 await page.screenshot({path:'docs/map-mobile.png',fullPage:true});
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+2),false,'mobile overflow');
 await page.route('**/api/map/summary?**',route=>route.fulfill({status:503,contentType:'application/json',body:'{}'}));
 await page.locator('#m-reset').click();
 await page.waitForFunction(()=>document.querySelector('#map-count').textContent==='Unavailable');
 await page.unroute('**/api/map/summary?**');
 await page.locator('#m-reset').click();
 await page.waitForFunction(()=>document.querySelector('#map-status').textContent.includes('crashes represented by barangay area'));
 await page.route('**/api/map/summary?**',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({points:[],total:0,plotted:0,excluded:0,barangays:[]})}));
 await page.locator('#m-reset').click();
 await page.waitForFunction(()=>document.querySelector('#map-count').textContent==='0 crashes');
 assert.equal(await page.locator('#map-ranking').innerText(),'No records match these filters.');
 assert.deepEqual(errors,[]);
 assert(!tileHosts.has('tile.openstreetmap.org'),'direct OSM tiles still requested');
 assert(successfulTiles>0,'OpenFreeMap did not serve map resources');
 console.log('PASS: desktop/mobile map, filters, points, reset, network recovery, empty results; no JS errors.');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});






