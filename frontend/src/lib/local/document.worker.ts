import { unzipSync } from "fflate";

self.onmessage = async ({ data: { file, maxXmlBytes } }: MessageEvent<{ file: File; maxXmlBytes: number }>) => {
  try {
    let text = "";
    const check = () => { if (text.length > 60_000) throw new Error("Document exceeds 60,000 characters. Split it or paste a relevant excerpt; nothing was sent."); };
    const ext = file.name.split(".").pop()?.toLowerCase();
    if (ext === "docx") {
      // Bound archive expansion before inflating untrusted ZIP entries.
      const entries = unzipSync(new Uint8Array(await file.arrayBuffer()), { filter: entry => {
        if (entry.name !== "word/document.xml") return false;
        if (entry.originalSize > maxXmlBytes) throw new Error(`Word document XML exceeds this device's ${maxXmlBytes / 1024 / 1024} MiB local expansion limit.`);
        return true;
      } });
      const xml = entries["word/document.xml"];
      if (!xml) throw new Error("Invalid Word document.");
      // XML is returned to DOMParser on the UI thread, never inserted into HTML.
      self.postMessage({ xml: new TextDecoder().decode(xml) }); return;
    } else if (["txt", "md", "csv", "json", "srt", "vtt"].includes(ext || "")) {
      const reader = file.stream().getReader(); const decoder = new TextDecoder("utf-8", { fatal: true });
      try {
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          text += decoder.decode(value, { stream: true }); check();
          self.postMessage({ progress: `Reading text: ${text.length.toLocaleString()} characters` });
        }
        text += decoder.decode(); check();
      } finally { await reader.cancel(); reader.releaseLock(); }
    } else throw new Error("Unsupported document format. Use PDF, DOCX or UTF-8 text, or paste text.");
    if (!text.trim()) throw new Error("The document is empty or contains no readable text.");
    self.postMessage({ text: text.trim() });
  } catch (e) { self.postMessage({ error: e instanceof Error ? e.message : "Document extraction failed. Paste text instead." }); }
};
