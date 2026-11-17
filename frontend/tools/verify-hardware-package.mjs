import { chromium } from '@playwright/test';
import path from 'node:path';
import fs from 'node:fs/promises';
const conservative=process.argv.includes('conservative');
const root=path.resolve('../../kruvim-paid-local-followup-20261117');
for(const channel of ['msedge','chrome']){
 const browser=await chromium.launch({channel});
 try{
  const context=await browser.newContext();if(conservative)await context.addInitScript(()=>Object.defineProperty(navigator,'deviceMemory',{configurable:true,value:4}));const page=await context.newPage();const sent=[];const errors=[];
  context.on('request',r=>{if(!['GET','HEAD','OPTIONS'].includes(r.method()))sent.push(r.url());});
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto('http://127.0.0.1:5188/hardware-check/index.html');
  await page.locator('#files').setInputFiles((conservative?['brief.pdf','brief.docx','slide-red.png','small-lossy.webp','large-audio.wav','large-video.mp4']:['large-brief.pdf','large-image.png','large-audio.wav','large-video.mp4']).map(f=>path.resolve('../../kruvim-local-processing-evidence/fixtures',f)));
  await page.locator('#run').click();
  await page.getByRole('status').filter({hasText:'Local checks passed on this device.'}).waitFor({timeout:240000});
  const download=page.waitForEvent('download');await page.locator('#save').click();await(await download).saveAs(path.join(root,`${channel}-portable-${conservative?"conservative-":""}hardware-report.json`));
  const report=JSON.parse(await fs.readFile(path.join(root,`${channel}-portable-${conservative?"conservative-":""}hardware-report.json`),'utf8'));
  if(!report.success||!report.hardware.physicalMemoryBytes||sent.length||errors.length)throw new Error('Portable diagnostic verification failed');
  await fs.writeFile(path.join(root,`${channel}-portable-${conservative?"conservative-":""}network.json`),JSON.stringify({sent,errors,physicalMemoryBytes:report.hardware.physicalMemoryBytes,scope:'Tested diagnostic launcher on current 40 GiB host; not qualification of low-RAM hardware'},null,2));
  console.log(`${channel}: portable diagnostic passed; physical bytes=${report.hardware.physicalMemoryBytes}`);
 }finally{await browser.close();}
}
