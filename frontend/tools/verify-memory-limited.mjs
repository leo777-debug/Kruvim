import { chromium } from '@playwright/test';
import fs from 'node:fs/promises';
import path from 'node:path';
const [channel,gate,reportFile,profile]=process.argv.slice(2);
while(true){try{await fs.access(gate);break;}catch{await new Promise(r=>setTimeout(r,100));}}
const result={channel,checks:[],sent:[],errors:[],scope:'OS job-limited browser process tree on a 40 GiB host; not physical low-RAM hardware'};
let browser;
try{
  browser=await chromium.launch({channel});
  const context=await browser.newContext();
  if(profile==='conservative')await context.addInitScript(()=>Object.defineProperty(navigator,'deviceMemory',{configurable:true,value:4}));
  result.policyOverride=profile==='conservative'?'4 GB browser capability signal; not physical RAM':null;
  const page=await context.newPage();
  context.on('request',r=>{if(!['GET','HEAD','OPTIONS'].includes(r.method()))result.sent.push({method:r.method(),url:r.url(),bytes:r.postDataBuffer()?.length||0});});
  page.on('pageerror',e=>result.errors.push(e.message));page.on('crash',()=>result.errors.push('browser renderer crashed'));
  await page.goto('http://127.0.0.1:5186/login');
  result.browser=await page.evaluate(()=>navigator.userAgent);
  result.reportedDeviceMemory=await page.evaluate(()=>navigator.deviceMemory);
  await page.evaluate(()=>{const i=document.createElement('input');i.id='memory-fixture';i.type='file';document.body.append(i);});
  const fixtures=path.resolve('../../kruvim-local-processing-evidence/fixtures');
  for(const name of (profile==='conservative'?['brief.pdf','low-max.pdf','brief.docx','low-max-photo.jpg','slide-red.png','slide-blue.jpg','small-lossy.webp','small-lossless.webp','large-audio.wav','large-video.mp4']:['large-brief.pdf','large-image.png','large-audio.wav','large-video.mp4'])){
    await page.locator('#memory-fixture').setInputFiles(path.join(fixtures,name));
    const one=await page.evaluate(async ({name,profile})=>{
      const {prepareFile}=await import('/src/lib/local/prepare.ts');const started=performance.now();let lastProgress='';
      try{const v=await prepareFile(document.querySelector('#memory-fixture').files[0],new AbortController().signal,s=>lastProgress=s,profile==='conservative'&&(name.endsWith('wav')||name.endsWith('mp4'))?'00:00:00,000 --> 00:00:20,000\nSupplied transcript for low-memory frame processing.':'');
        return{name,ms:performance.now()-started,textChars:v.text.length,transcriptChars:v.transcript.length,images:v.local_media.images.length,duration:v.local_media.duration};
      }catch(e){return{name,ms:performance.now()-started,error:e.message,lastProgress};}
    },{name,profile});
    result.checks.push(one);await fs.writeFile(reportFile,JSON.stringify(result,null,2));
    if(one.error)throw new Error('Local processing failed: '+one.name+': '+one.error);
    console.log(`${channel}: ${name} passed`);
  }
  result.success=result.sent.length===0&&result.errors.length===0;
}catch(e){result.success=false;result.failure=e.message;process.exitCode=1;}
finally{await browser?.close().catch(()=>{});await fs.writeFile(reportFile,JSON.stringify(result,null,2));}
