import pdfWorkerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import type { PreparedFile, Progress, SelectedImage } from "./types";

function check(signal: AbortSignal) { signal.throwIfAborted(); }
function abortable<T>(work: Promise<T>, signal: AbortSignal): Promise<T> {
  return new Promise((resolve, reject) => {
    const abort = () => reject(new DOMException("Local processing cancelled. Nothing was uploaded.", "AbortError"));
    if (signal.aborted) { void work.catch(() => {}); return abort(); }
    signal.addEventListener("abort", abort, { once: true });
    work.then(resolve, reject).finally(() => signal.removeEventListener("abort", abort));
  });
}
function workerCall(worker: Worker, data: unknown, signal: AbortSignal, progress: Progress, transfer: Transferable[] = []): Promise<any> {
  return new Promise((resolve, reject) => {
    const clear = () => { worker.onmessage = null; worker.onerror = null; signal.removeEventListener("abort", abort); };
    const abort = () => { clear(); worker.terminate(); reject(new DOMException("Local processing cancelled. Nothing was uploaded.", "AbortError")); };
    if (signal.aborted) return abort();
    signal.addEventListener("abort", abort, { once: true });
    worker.onerror = () => { clear(); reject(new Error("Local worker failed or ran out of memory. Close tabs, split the file, or paste a transcript. Nothing was uploaded.")); };
    worker.onmessage = ({ data }) => {
      if (data.progress) { progress(data.progress); return; }
      if (!("text" in data) && !("xml" in data) && !("chunks" in data) && !data.error) return;
      clear(); data.error ? reject(new Error(data.error)) : resolve(data);
    };
    worker.postMessage(data, transfer);
  });
}

export async function documentText(file: File, signal: AbortSignal, progress: Progress): Promise<string> {
  if (file.name.toLowerCase().endsWith(".pdf")) {
    const pdfjs = await import("pdfjs-dist"); check(signal);
    pdfjs.GlobalWorkerOptions.workerSrc = pdfWorkerUrl;
    const task = pdfjs.getDocument({ data: new Uint8Array(await file.arrayBuffer()), isEvalSupported: false, useSystemFonts: false });
    const abort = () => { void task.destroy(); }; signal.addEventListener("abort", abort, { once: true });
    try {
      check(signal); const pdf = await task.promise; let text = "";
      if (pdf.numPages > 200) throw new Error("PDF exceeds 200 pages. Split it locally first.");
      for (let i = 1; i <= pdf.numPages; i++) {
        check(signal); progress(`Reading PDF page ${i} of ${pdf.numPages}`);
        const page = await pdf.getPage(i); const content = await page.getTextContent();
        text += `\n[Page ${i}]\n` + content.items.map(x => "str" in x ? x.str + (x.hasEOL ? "\n" : " ") : "").join("");
        page.cleanup();
        if (text.length > 60000) throw new Error("Document exceeds 60,000 characters. Split it or paste an excerpt.");
      }
      if (!text.replace(/\[Page \d+\]/g, "").trim()) throw new Error("PDF has no readable text. Run OCR locally and paste its output.");
      return text.trim();
    } finally { signal.removeEventListener("abort", abort); await task.destroy(); }
  }
  const worker = new Worker(new URL("./document.worker.ts", import.meta.url), { type: "module" });
  try {
    const result = await workerCall(worker, { file }, signal, progress);
    if (!result.xml) return result.text;
    const doc = new DOMParser().parseFromString(result.xml, "application/xml");
    if (doc.querySelector("parsererror")) throw new Error("The Word document contains invalid XML.");
    const text = Array.from(doc.getElementsByTagNameNS("*", "p"), p => Array.from(p.getElementsByTagNameNS("*", "t"), t => t.textContent || "").join("")).join("\n");
    if (!text.trim() || text.length > 60_000) throw new Error("Word document is empty or exceeds 60,000 characters. Split it or paste an excerpt.");
    return text;
  } finally { worker.terminate(); }
}

function mediaEvent(el: HTMLMediaElement, event: string, signal: AbortSignal, action: () => void): Promise<void> {
  return new Promise((resolve, reject) => {
    const clear = () => { clearTimeout(timer); el.removeEventListener(event, done); el.removeEventListener("error", fail); signal.removeEventListener("abort", abort); };
    const done = () => { clear(); resolve(); };
    const fail = () => { clear(); reject(new Error("This browser cannot decode the media, or the file is damaged. Convert it locally or paste a transcript.")); };
    const abort = () => { clear(); reject(new DOMException("Local processing cancelled", "AbortError")); };
    const timer = setTimeout(fail, 30_000);
    el.addEventListener(event, done, { once: true }); el.addEventListener("error", fail, { once: true }); signal.addEventListener("abort", abort, { once: true });
    if (signal.aborted) return abort();
    action();
  });
}

function resized(source: CanvasImageSource, width: number, height: number): string {
  if (!width || !height || width * height > 40_000_000) throw new Error("Image exceeds 40 megapixels or has invalid dimensions. Resize it locally first.");
  const scale = Math.min(1, 1024 / Math.max(width, height));
  const canvas = document.createElement("canvas"); canvas.width = Math.max(1, Math.round(width * scale)); canvas.height = Math.max(1, Math.round(height * scale));
  try {
    const ctx = canvas.getContext("2d"); if (!ctx) throw new Error("Browser image processing is unavailable.");
    ctx.drawImage(source, 0, 0, canvas.width, canvas.height);
    const data = canvas.toDataURL("image/jpeg", 0.75);
    if (data.length > 350_000) throw new Error("Resized image is too complex. Resize it further locally.");
    return data;
  } finally { canvas.width = canvas.height = 0; }
}
const stamp = (seconds: number) => { const ms = Math.round(seconds * 1000); return `${String(Math.floor(ms / 3600000)).padStart(2, "0")}:${String(Math.floor(ms / 60000) % 60).padStart(2, "0")}:${String(Math.floor(ms / 1000) % 60).padStart(2, "0")},${String(ms % 1000).padStart(3, "0")}`; };

export async function prepareFile(file: File, signal: AbortSignal, progress: Progress, transcript = ""): Promise<PreparedFile> {
  check(signal);
  if (!globalThis.Worker || !globalThis.WebAssembly) throw new Error("This browser lacks local processing support. Paste text or a transcript; no file was uploaded.");
  if (!file.size || file.size > 128 * 1024 * 1024) throw new Error("Choose a nonempty file up to the 128 MiB local safety ceiling, or split it locally.");
  const ext = file.name.split(".").pop()?.toLowerCase();
  if ((ext === "pdf" || file.type.startsWith("image/")) && file.size > 64 * 1024 * 1024) throw new Error("PDFs and images are limited to 64 MiB locally. Split or resize the file on your device.");
  if (ext === "docx" && file.size > 16 * 1024 * 1024) throw new Error("DOCX files are limited to 16 MiB locally. Split the document or paste text.");
  const memory = (navigator as Navigator & { deviceMemory?: number }).deviceMemory;
  if (memory && memory < 4) throw new Error("This browser reports less than 4 GB memory. Paste text or a transcript instead.");
  const result: PreparedFile = { text: "", transcript: "", local_media: { images: [] }, notes: [] };
  progress(`Reading ${file.name} on this device`);
  if (file.type.startsWith("image/")) {
    if (!["image/png", "image/jpeg", "image/webp"].includes(file.type)) throw new Error("Use a PNG, JPEG or WebP image.");
    const bitmap = await createImageBitmap(file);
    try { check(signal); result.local_media.images.push({ data: resized(bitmap, bitmap.width, bitmap.height), order: 0 }); } finally { bitmap.close(); }
    return result;
  }
  if (!file.type.startsWith("audio/") && !file.type.startsWith("video/")) {
    result.text = await documentText(file, signal, progress); return result;
  }
  const video = file.type.startsWith("video/");
  const el = document.createElement(video ? "video" : "audio"); el.preload = "auto";
  const url = URL.createObjectURL(file);
  try {
    await mediaEvent(el, "loadedmetadata", signal, () => { el.src = url; el.load(); });
    const duration = el.duration;
    if (!Number.isFinite(duration) || duration <= 0 || duration > 86400) throw new Error("Media duration is unavailable. Convert it locally or paste timed subtitles.");
    if (video && (!(el as HTMLVideoElement).videoWidth || !(el as HTMLVideoElement).videoHeight)) throw new Error("The video codec is unsupported in this browser. Convert it locally to H.264 MP4, or remove the file and paste a transcript.");
    result.local_media.duration = duration;
    if (!transcript.trim()) {
      // Native decodeAudioData requires the full compressed buffer. Guard both compressed
      // and decoded memory; inference itself is sequential, 30 seconds at a time.
      if (duration > 600 || duration * 48000 * 2 * 4 > 128 * 1024 * 1024 || file.size > 128 * 1024 * 1024) throw new Error("Automatic speech needs <=10 minutes, <=128 MiB compressed and <=128 MiB estimated decoded stereo audio. Paste a transcript to process larger media locally.");
      progress("Decoding audio locally (cancellation discards the result)");
      const context = new AudioContext({ sampleRate: 16000 });
      let worker: Worker | undefined;
      // decodeAudioData has no abort API. Close the context on cancellation and
      // reject immediately; the browser may finish its native decode in the background.
      const close = () => { void context.close().catch(() => {}); };
      signal.addEventListener("abort", close, { once: true });
      try {
        const bytes = await abortable(file.arrayBuffer(), signal); check(signal);
        const audio = await abortable(context.decodeAudioData(bytes), signal); check(signal);
        if (audio.numberOfChannels * audio.length * 4 > 128 * 1024 * 1024 || audio.sampleRate !== 16000) throw new Error("Decoded audio exceeds the memory ceiling or the browser cannot resample to 16 kHz. Paste a transcript.");
        worker = new Worker(new URL("./speech.worker.ts", import.meta.url), { type: "module" });
        const cues: { start: number; end: number; text: string }[] = [];
        for (let start = 0; start < audio.length; start += 30 * 16000) {
          check(signal); progress(`Transcribing locally: ${Math.round(start / audio.length * 100)}%`);
          const samples = new Float32Array(Math.min(30 * 16000, audio.length - start));
          for (let channel = 0; channel < audio.numberOfChannels; channel++) {
            const source = audio.getChannelData(channel);
            for (let i = 0; i < samples.length; i++) samples[i] += source[start + i] / audio.numberOfChannels;
          }
          const r = await workerCall(worker, { samples, offset: start / 16000 }, signal, progress, [samples.buffer]);
          cues.push(...r.chunks);
        }
        result.transcript = cues.filter(c => c.text.trim() && c.end > c.start).map((c, i) => `${i + 1}\n${stamp(c.start)} --> ${stamp(Math.min(duration, c.end))}\n${c.text.trim()}\n`).join("\n");
        if (!result.transcript) throw new Error("No speech was detected. Paste a transcript or describe the silent video.");
        if (result.transcript.length > 120_000) throw new Error("Transcript exceeds 120,000 characters. Split the media.");
        result.notes.push("Whisper tiny transcript: review recognition and timing errors before sending. Music and silence can cause hallucinated words.");
      } finally { worker?.terminate(); signal.removeEventListener("abort", close); if (context.state !== "closed") await context.close(); }
    }
    if (video) {
      const count = Math.min(8, Math.max(1, Math.ceil(duration / 10)));
      for (let i = 0; i < count; i++) {
        check(signal); progress(`Extracting local frame ${i + 1} of ${count}`);
        const time = Math.min(duration - 0.001, (i + 0.5) * duration / count);
        await mediaEvent(el, "seeked", signal, () => { el.currentTime = time; });
        const v = el as HTMLVideoElement;
        result.local_media.images.push({ data: resized(v, v.videoWidth, v.videoHeight), time, order: i });
      }
      result.notes.push("Sparse selected frames are not a full video analysis. Remove unnecessary frames before sending.");
    }
    return result;
  } finally { el.pause(); el.removeAttribute("src"); el.load(); URL.revokeObjectURL(url); }
}

export function orderedImages(images: SelectedImage[]): SelectedImage[] { return images.map((image, order) => ({ ...image, order })); }
