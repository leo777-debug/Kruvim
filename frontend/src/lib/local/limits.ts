export function localLimits(memory = (navigator as Navigator & { deviceMemory?: number }).deviceMemory) {
  const standard = !!memory && memory >= 8;
  return {
    mode: memory && memory < 2 ? "paste-only" : standard ? "standard" : "conservative",
    automaticSpeech: standard,
    textBytes: (standard ? 128 : 2) * 1024 * 1024,
    pdfBytes: (standard ? 64 : 8) * 1024 * 1024,
    pdfPages: standard ? 200 : 40,
    docxBytes: (standard ? 16 : 4) * 1024 * 1024,
    xmlBytes: (standard ? 4 : 1) * 1024 * 1024,
    imageBytes: (standard ? 64 : 8) * 1024 * 1024,
    imagePixels: standard ? 40_000_000 : 12_000_000,
    videoPixels: standard ? 40_000_000 : 2_100_000,
    edge: standard ? 1024 : 768,
    frames: standard ? 8 : 4,
    explanation: memory && memory < 2
      ? "This device reports less than 2 GB RAM. Use pasted text or transcripts; automatic file preparation is disabled."
      : standard
        ? "Standard local limits: 128 MiB media/text, 64 MiB PDF/images, 16 MiB DOCX, 200 PDF pages, 1024-pixel images. Automatic speech is available within the decoded-audio memory limit."
        : "Conservative local mode (under 8 GB or RAM unknown): 2 MiB text, 8 MiB PDF/images, 4 MiB DOCX, 40 PDF pages, 12-megapixel source images and 768-pixel outputs. Video up to 128 MiB/1080p uses at most four frames and needs a pasted transcript. Automatic speech/model downloads are disabled. You can always paste text or a transcript. These limits do not certify this device's physical hardware.",
  };
}
