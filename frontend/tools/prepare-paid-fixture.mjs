import { chromium } from '@playwright/test';
import fs from 'node:fs/promises';
import path from 'node:path';
const destination = path.resolve('../../kruvim-paid-local-followup-20261117');
const fixtures = path.resolve('../../kruvim-local-processing-evidence/fixtures');
const browser = await chromium.launch({channel: 'msedge'});
try {
  const context = await browser.newContext(); const page = await context.newPage();
  const sent = [];
  context.on('request', r => { if (!['GET','HEAD','OPTIONS'].includes(r.method())) sent.push({method:r.method(),url:r.url(),bytes:r.postDataBuffer()?.length || 0}); });
  await page.goto('http://127.0.0.1:5186/login');
  await page.evaluate(() => {const i=document.createElement('input');i.type='file';i.id='fixture';document.body.append(i);});
  const prepared = {};
  for (const name of ['brief.pdf','slide-red.png','slide-blue.jpg','large-video.mp4']) {
    await page.locator('#fixture').setInputFiles(path.join(fixtures,name));
    prepared[name] = await page.evaluate(async name => {
      const {prepareFile}=await import('/src/lib/local/prepare.ts');
      return prepareFile(document.querySelector('#fixture').files[0],new AbortController().signal,()=>{},name.endsWith('mp4')?'00:00:00,000 --> 00:00:20,000\nA breakfast recipe with oats and banana.':'');
    },name);
  }
  if(sent.length) throw new Error('Preparation unexpectedly emitted a content request');
  await fs.writeFile(path.join(destination,'derived-fixtures.json'),JSON.stringify(prepared));
  await fs.writeFile(path.join(destination,'preparation-network.json'),JSON.stringify({sent,sourceBytes:74626491,selectedFrameCount:prepared['large-video.mp4'].local_media.images.length},null,2));
  console.log('Browser-derived text, re-encoded slides and timed video frames prepared; zero content requests.');
} finally { await browser.close(); }
