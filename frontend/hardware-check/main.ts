import { localLimits } from "../src/lib/local/limits";
import { prepareFile } from "../src/lib/local/prepare";
const status=document.querySelector<HTMLPreElement>("#status")!;
const run=document.querySelector<HTMLButtonElement>("#run")!;
const cancel=document.querySelector<HTMLButtonElement>("#cancel")!;
const files=document.querySelector<HTMLInputElement>("#files")!;
const report: Record<string,any>={diagnostic:"Kruvim browser-local physical hardware check",browser:navigator.userAgent,started:new Date().toISOString(),scope:"Local preparation only; no cloud inference",memoryPolicy:localLimits(),checks:[]};
document.querySelector("#policy")!.textContent=localLimits().explanation;
let controller:AbortController|undefined;
fetch('/hardware.json').then(r=>r.json()).then(v=>{report.hardware=v;status.textContent=`Ready. Windows reports ${(v.physicalMemoryBytes/1024**3).toFixed(2)} GiB physical RAM. This is a diagnostic, not a pass yet.`;}).catch(()=>{report.hardware={error:"Physical RAM could not be read by the local launcher"};});
run.onclick=async()=>{
  if(!files.files?.length){status.textContent="Choose the fixture files first.";return;}
  report.checks=[];report.success=false;controller=new AbortController();run.disabled=true;files.disabled=true;cancel.disabled=false;
  try{
    for(const file of Array.from(files.files)){
      const started=performance.now();
      try{
        const value=await prepareFile(file,controller.signal,message=>status.textContent=`${file.name}: ${message}`,!localLimits().automaticSpeech?(document.querySelector<HTMLTextAreaElement>("#transcript")!.value.trim()):"");
        report.checks.push({filename:file.name,sourceBytes:file.size,milliseconds:Math.round(performance.now()-started),textCharacters:value.text.length,transcriptCharacters:value.transcript.length,images:value.local_media.images.length,durationSeconds:value.local_media.duration,status:"passed"});
      }catch(e){report.checks.push({filename:file.name,sourceBytes:file.size,milliseconds:Math.round(performance.now()-started),status:"failed",error:e instanceof Error?e.message:"Unknown error"});throw e;}
    }
    report.success=true;
    status.textContent="Local checks passed on this device. Save the diagnostic report. This does not verify cloud AI or establish support for other files or devices.";
  }catch(e){status.textContent=`Local check stopped: ${e instanceof Error?e.message:"Unknown error"}. No file content was uploaded. Save the report to diagnose this device.`;}
  finally{report.finished=new Date().toISOString();cancel.disabled=true;run.disabled=false;files.disabled=false;}
};
cancel.onclick=()=>controller?.abort();
document.querySelector<HTMLButtonElement>("#save")!.onclick=()=>{
  const url=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:"application/json"}));
  const a=document.createElement('a');a.href=url;a.download='kruvim-hardware-report.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
};
window.addEventListener('pagehide',()=>controller?.abort());
