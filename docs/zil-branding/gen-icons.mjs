import sharp from "sharp";
import { writeFile } from "node:fs/promises";

const BG = "#000000";
const FG = "#ffffff";
// ZIL wordmark (viewBox 0 0 57 32) — matches Zil's real favicon
const WORD =
  "M12.8857 19.0928H21.4629V32H0L10.1328 19.0928H1.67871V6.18555H23.0186L12.8857 19.0928ZM39.0742 32H26.166V6.18555H39.0742V32ZM57.001 32H44.0938V0H57.001V32Z";

// square icon: black bg + white ZIL wordmark centered
function iconSVG(size, rounded) {
  const rx = rounded ? Math.round(size * 0.22) : 0;
  const targetW = size * 0.62; // wordmark width
  const scale = targetW / 57;
  const drawW = 57 * scale;
  const drawH = 32 * scale;
  const tx = (size - drawW) / 2;
  const ty = (size - drawH) / 2;
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
  <rect width="${size}" height="${size}" rx="${rx}" ry="${rx}" fill="${BG}"/>
  <g transform="translate(${tx} ${ty}) scale(${scale})"><path d="${WORD}" fill="${FG}"/></g>
</svg>`;
}

async function pngFromSVG(svg, out, size) {
  await sharp(Buffer.from(svg)).resize(size, size).png().toFile(out);
  console.log("wrote", out);
}

const W = "/Users/brianjosesucari/Developer/plane/apps/web";

// [size, path, rounded]
const targets = [
  [16, `${W}/app/assets/favicon/favicon-16x16.png`, false],
  [32, `${W}/app/assets/favicon/favicon-32x32.png`, false],
  [180, `${W}/app/assets/favicon/apple-touch-icon.png`, true],
  [180, `${W}/app/assets/icons/icon-180x180.png`, true],
  [512, `${W}/app/assets/icons/icon-512x512.png`, true],
  [192, `${W}/public/icons/icon-192x192.png`, true],
  [348, `${W}/public/icons/icon-348x348.png`, true],
  [512, `${W}/public/icons/icon-512x512.png`, true],
  [192, `${W}/public/favicon/android-chrome-192x192.png`, true],
  [512, `${W}/public/favicon/android-chrome-512x512.png`, true],
];

for (const [size, out, rounded] of targets) {
  await pngFromSVG(iconSVG(size, rounded), out, size);
}

// favicon.ico (16/32/48, flat)
async function makeIco(sizes, out) {
  const pngs = [];
  for (const s of sizes) {
    const buf = await sharp(Buffer.from(iconSVG(s, false))).resize(s, s).png().toBuffer();
    pngs.push({ size: s, buf });
  }
  const count = pngs.length;
  const header = Buffer.alloc(6);
  header.writeUInt16LE(0, 0);
  header.writeUInt16LE(1, 2);
  header.writeUInt16LE(count, 4);
  const dir = Buffer.alloc(16 * count);
  let offset = 6 + 16 * count;
  pngs.forEach((p, i) => {
    const b = i * 16;
    dir.writeUInt8(p.size >= 256 ? 0 : p.size, b + 0);
    dir.writeUInt8(p.size >= 256 ? 0 : p.size, b + 1);
    dir.writeUInt8(0, b + 2);
    dir.writeUInt8(0, b + 3);
    dir.writeUInt16LE(1, b + 4);
    dir.writeUInt16LE(32, b + 6);
    dir.writeUInt32LE(p.buf.length, b + 8);
    dir.writeUInt32LE(offset, b + 12);
    offset += p.buf.length;
  });
  await writeFile(out, Buffer.concat([header, dir, ...pngs.map((p) => p.buf)]));
  console.log("wrote", out);
}
await makeIco([16, 32, 48], `${W}/app/assets/favicon/favicon.ico`);

// og-image 1200x630: black bg, centered white ZIL wordmark
const og = `<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630">
  <rect width="1200" height="630" fill="${BG}"/>
  <g transform="translate(420 219) scale(6)"><path d="${WORD}" fill="${FG}"/></g>
</svg>`;
await sharp(Buffer.from(og)).png().toFile(`${W}/app/assets/og-image.png`);
console.log("wrote og-image");
