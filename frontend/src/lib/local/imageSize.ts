/** Read bounded image headers before asking a native decoder to allocate pixels. */
export async function imageSize(file: File): Promise<[number, number]> {
  const bytes = new Uint8Array(await file.slice(0, 512 * 1024).arrayBuffer());
  const view = new DataView(bytes.buffer);
  if (bytes.length >= 24 && view.getUint32(0) === 0x89504e47 && view.getUint32(4) === 0x0d0a1a0a) return [view.getUint32(16), view.getUint32(20)];
  if (bytes[0] === 0xff && bytes[1] === 0xd8) {
    let offset = 2;
    while (offset + 9 <= bytes.length) {
      if (bytes[offset] !== 0xff) break;
      if (bytes[offset + 1] === 0xff) { offset++; continue; }
      const marker = bytes[offset + 1];
      if ([0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7, 0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf].includes(marker)) return [view.getUint16(offset + 7), view.getUint16(offset + 5)];
      if (marker === 0xda || marker === 0xd9) break;
      const length = view.getUint16(offset + 2);
      if (length < 2) break;
      offset += length + 2;
    }
  }
  if (bytes.length >= 30 && String.fromCharCode(...bytes.slice(0, 4)) === "RIFF" && String.fromCharCode(...bytes.slice(8, 12)) === "WEBP") {
    const kind = String.fromCharCode(...bytes.slice(12, 16));
    if (kind === "VP8X") return [1 + bytes[24] + (bytes[25] << 8) + (bytes[26] << 16), 1 + bytes[27] + (bytes[28] << 8) + (bytes[29] << 16)];
    if (kind === "VP8L" && bytes[20] === 0x2f) return [1 + bytes[21] + ((bytes[22] & 0x3f) << 8), 1 + (bytes[22] >> 6) + (bytes[23] << 2) + ((bytes[24] & 0xf) << 10)];
    if (kind === "VP8 " && bytes[23] === 0x9d && bytes[24] === 1 && bytes[25] === 0x2a) return [view.getUint16(26, true) & 0x3fff, view.getUint16(28, true) & 0x3fff];
  }
  throw new Error("Image dimensions are unavailable or its metadata exceeds 512 KiB. Re-encode to PNG/JPEG locally before selecting it.");
}
