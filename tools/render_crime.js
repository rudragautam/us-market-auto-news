const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");
(async()=>{const html=process.argv[2], out=process.argv[3];fs.mkdirSync(out,{recursive:true});
const browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1600,height:900}});
await page.goto("file://"+path.resolve(html)); await page.waitForTimeout(500);
const count=await page.locator(".scene").count(); let frame=0;
for(let i=0;i<count;i++){await page.locator(".scene").nth(i).scrollIntoViewIfNeeded();await page.waitForTimeout(300);
 for(let n=0;n<270;n++){await page.screenshot({path:path.join(out,String(frame++).padStart(6,"0")+".png")});await page.waitForTimeout(33);}}
await browser.close();})();