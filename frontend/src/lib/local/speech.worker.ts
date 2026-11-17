import { env, pipeline } from "@huggingface/transformers";
env.allowLocalModels = false;
env.useBrowserCache = true;
// This is ONNX inference in this worker. Never use Web Speech's remote recognition.
if (env.backends.onnx.wasm) {
  env.backends.onnx.wasm.numThreads = 1;
  // Ship runtime assets with the website instead of depending on a third-party
  // runtime CDN. Model weights are separately cached by Transformers.js.
  env.backends.onnx.wasm.wasmPaths = {
    mjs: new URL("../../../node_modules/@huggingface/transformers/dist/ort-wasm-simd-threaded.jsep.mjs", import.meta.url).href,
    wasm: new URL("../../../node_modules/@huggingface/transformers/dist/ort-wasm-simd-threaded.jsep.wasm", import.meta.url).href,
  };
}
let recognizer: any;
self.onmessage = async ({ data }: MessageEvent<{ samples: Float32Array; offset: number }>) => {
  try {
    recognizer ||= await pipeline("automatic-speech-recognition", "Xenova/whisper-tiny", {
      device: "wasm", dtype: "q8", progress_callback: (p: any) => self.postMessage({ progress: p.status === "progress" ? `Downloading speech model: ${p.file} ${Math.round(p.progress || 0)}%` : `Speech model: ${p.status}` }),
    });
    const output = await recognizer(data.samples, { return_timestamps: true, chunk_length_s: 30, stride_length_s: 0, task: "transcribe" });
    self.postMessage({ chunks: (output.chunks || []).map((c: any) => ({ text: c.text, start: data.offset + (c.timestamp[0] || 0), end: data.offset + (c.timestamp[1] ?? data.samples.length / 16000) })) });
  } catch (e) { self.postMessage({ error: `Local speech recognition failed: ${e instanceof Error ? e.message : "unknown error"}. Paste an SRT/VTT transcript instead. No audio was uploaded.` }); }
};
