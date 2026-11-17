import { expect, test } from '@playwright/test';
import path from 'node:path';
import fs from 'node:fs';
for(const memory of [4,undefined]) test(`conservative local preparation with RAM ${memory ?? 'unknown'}`,async({page},info)=>{
  await page.addInitScript(memory=>Object.defineProperty(navigator,'deviceMemory',{configurable:true,value:memory}),memory);
  const requests:string[]=[];page.context().on('request',r=>requests.push(r.url()));
  await page.goto('/login');await page.evaluate(()=>{const i=document.createElement('input');i.id='conservative-file';i.type='file';document.body.append(i);});
  const results:any[]=[];
  for(const name of ['brief.pdf','brief.docx','slide-red.png','slide-blue.jpg','small-lossy.webp','small-lossless.webp','large-video.mp4','speech.wav','large-brief.pdf','large-image.png','forty-one-pages.pdf','large-xml.docx']){
    await page.locator('#conservative-file').setInputFiles(path.resolve('../../kruvim-local-processing-evidence/fixtures',name));
    const r=await page.evaluate(async name=>{
      const {prepareFile}=await import('/src/lib/local/prepare.ts');const {localLimits}=await import('/src/lib/local/limits.ts');
      try{const value=await prepareFile((document.querySelector('#conservative-file') as HTMLInputElement).files![0],new AbortController().signal,()=>{},name.endsWith('mp4')?'00:00:00,000 --> 00:00:20,000\nA breakfast recipe.':'');
        return {name,mode:localLimits().mode,text:value.text,images:value.local_media.images.length,data:value.local_media.images[0]?.data,duration:value.local_media.duration};
      }catch(e){return{name,error:(e as Error).message};}
    },name);
    results.push({...r,data:r.data?`JPEG ${r.data.length} chars`:undefined});
    if(['speech.wav','large-brief.pdf','large-image.png','forty-one-pages.pdf','large-xml.docx'].includes(name)){
      expect(r.error).toBeTruthy();
      if(name==='speech.wav')expect(r.error).toContain('Automatic speech is disabled');
    }else{
      expect(r.error,JSON.stringify(r)).toBeUndefined();expect(r.mode).toBe('conservative');
      if(r.data){const dimensions=await page.evaluate(async data=>{const image=new Image();image.src=data;await image.decode();return[image.width,image.height];},r.data);expect(Math.max(...dimensions)).toBeLessThanOrEqual(768);}
      if(name.endsWith('mp4')){expect(r.duration).toBeCloseTo(20);expect(r.images).toBeLessThanOrEqual(4);}
    }
  }
  expect(requests.some(url=>url.includes('huggingface.co')||url.includes('cdn.jsdelivr.net'))).toBeFalsy();
  const predecodeGuard=await page.evaluate(async()=>{
    const {prepareFile}=await import('/src/lib/local/prepare.ts');
    const header=new Uint8Array(24);header.set([137,80,78,71,13,10,26,10]);const view=new DataView(header.buffer);view.setUint32(16,20000);view.setUint32(20,20000);
    const original=createImageBitmap;let decoded=false;globalThis.createImageBitmap=async(...args:Parameters<typeof createImageBitmap>)=>{decoded=true;return original(...args);};
    try{await prepareFile(new File([header],'oversized-pixels.png',{type:'image/png'}),new AbortController().signal,()=>{});return{decoded,error:''};}
    catch(e){return{decoded,error:(e as Error).message};}
    finally{globalThis.createImageBitmap=original;}
  });
  expect(predecodeGuard.decoded).toBeFalsy();expect(predecodeGuard.error).toContain('12-megapixel');
  fs.writeFileSync(path.resolve('../../kruvim-paid-local-followup-20261117',`${info.project.name}-conservative-${memory??'unknown'}.json`),JSON.stringify({memory:memory??'unknown',results,predecodeGuard,modelDownloads:0},null,2));
});

test('under-8-GB website flow refuses automatic speech and saves a supplied transcript',async({page},info)=>{
  await page.addInitScript(()=>Object.defineProperty(navigator,'deviceMemory',{configurable:true,value:4}));
  await page.goto('/login');await page.getByLabel('Email').fill('demo@kruvim.local');await page.getByLabel('Password',{exact:true}).fill('kruvim-demo-2026');
  await page.getByRole('button',{name:'Sign in',exact:true}).click();await expect(page).not.toHaveURL(/login/);
  const fileRequests:string[]=[];let saved:any;const models:string[]=[];
  page.context().on('request',r=>{
    if(r.url().includes('huggingface.co'))models.push(r.url());
    if(r.method()==='POST'&&/projects\/[^/]+\/(assets|simulations)/.test(r.url())){fileRequests.push(r.url());if(r.url().endsWith('/simulations'))saved=r.postDataJSON();}
  });
  await page.goto('/');await expect(page.getByText(/Conservative local mode/).first()).toBeVisible();
  await page.getByLabel('Content file',{exact:true}).setInputFiles(path.resolve('../../kruvim-local-processing-evidence/fixtures/speech.wav'));
  await page.getByRole('button',{name:'Prepare and review draft',exact:true}).click();
  await expect(page.getByRole('alert')).toContainText('Automatic speech is disabled');expect(fileRequests).toEqual([]);expect(models).toEqual([]);
  await page.getByLabel('Transcript or show notes',{exact:true}).fill('Kruvim keeps original files on this device. This is a supplied transcript.');
  await page.getByRole('button',{name:'Prepare and review draft',exact:true}).click();await expect(page.getByRole('dialog')).toBeVisible();expect(fileRequests).toEqual([]);
  await page.getByRole('button',{name:'Send reviewed content to cloud',exact:true}).click();await expect(page).toHaveURL(/simulations\/[a-f0-9]+$/);
  expect(saved.content.asset_id).toBeNull();expect(saved.content.asset_ids).toEqual([]);expect(saved.content.transcript).toContain('supplied transcript');expect(saved.content.local_media.duration).toBeGreaterThan(0);
  expect(fileRequests.some(url=>url.includes('/assets'))).toBeFalsy();expect(models).toEqual([]);
  fs.writeFileSync(path.resolve('../../kruvim-paid-local-followup-20261117',`${info.project.name}-conservative-ui.json`),JSON.stringify({reportedMemory:4,automaticSpeechRefused:true,pastedTranscriptSaved:true,modelDownloads:models.length,fileRequests},null,2));
});
