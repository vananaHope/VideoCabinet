// 번들 글꼴 @font-face를 src/fonts.css로 생성한다. --check는 드리프트를 실패로 처리한다.
// 굵기는 web_tokens.json의 bundled-font, 계열 이름은 font-sans의 첫 이름에서 온다.
// unicode-range는 손으로 쓰지 않고 woff2의 cmap에서 계산한다:
//   첫 렌더용(부분 집합, block) = 부분 집합 파일이 가진 글자
//   나머지(전체 파일, swap)   = 전체 파일에만 있는 글자
// 두 범위는 겹치지 않고, 합치면 전체 파일이 가진 모든 글자다.
import { readFileSync, writeFileSync } from "node:fs"
import { brotliDecompressSync } from "node:zlib"

const root = new URL("../", import.meta.url)
const tokens = JSON.parse(readFileSync(new URL("../src/my_video_manager/web_tokens.json", root), "utf8"))
const family = tokens.typography["font-sans"].split(",")[0].trim().replace(/^"|"$/g, "")
const weights = tokens["bundled-font"].weights
const packageDir = "node_modules/pretendard"
const version = JSON.parse(readFileSync(new URL(`${packageDir}/package.json`, root), "utf8")).version
const files = stem => ({
  first: `${packageDir}/dist/web/static/woff2-subset/${family}-${stem}.subset.woff2`,
  rest: `${packageDir}/dist/web/static/woff2/${family}-${stem}.woff2`,
})
const output = new URL("src/fonts.css", root)

// WOFF2 표 목록에서 cmap 표를 꺼낸다(https://www.w3.org/TR/WOFF2/). cmap은 변환하지 않는 표라 압축만 푼다.
function cmapTable(path) {
  const data = readFileSync(new URL(path, root))
  if (data.toString("latin1", 0, 4) !== "wOF2") throw new Error(`WOFF2가 아닙니다: ${path}`)
  let offset = 48
  const base128 = () => {
    let value = 0
    for (let i = 0; i < 5; i++) {
      const byte = data[offset++]
      value = value * 128 + (byte & 0x7f)
      if (!(byte & 0x80)) return value
    }
    throw new Error(`UIntBase128 오류: ${path}`)
  }
  const tables = []
  for (let i = data.readUInt16BE(12); i > 0; i--) {
    const flags = data[offset++]
    const index = flags & 0x3f
    const tag = index === 63 ? data.toString("latin1", offset, (offset += 4)) : { 0: "cmap", 10: "glyf", 11: "loca" }[index] ?? String(index)
    const transform = flags >> 6
    const length = base128()
    const transformed = tag === "glyf" || tag === "loca" ? transform === 0 : transform !== 0
    tables.push({ tag, length: transformed ? base128() : length })
  }
  const stream = brotliDecompressSync(data.subarray(offset, offset + data.readUInt32BE(20)))
  let start = 0
  for (const table of tables) {
    if (table.tag === "cmap") return stream.subarray(start, start + table.length)
    start += table.length
  }
  throw new Error(`cmap 표가 없습니다: ${path}`)
}

// 유니코드 cmap 부표(3,10 형식 12 또는 3,1 형식 4)에서 글리프가 있는 글자 번호를 모은다.
function codePoints(path) {
  const cmap = cmapTable(path)
  const records = Array.from({ length: cmap.readUInt16BE(2) }, (_, i) => ({
    platform: cmap.readUInt16BE(4 + i * 8), encoding: cmap.readUInt16BE(6 + i * 8), offset: cmap.readUInt32BE(8 + i * 8) }))
  const pick = (platform, encoding, format) => records.find(r => r.platform === platform && r.encoding === encoding && cmap.readUInt16BE(r.offset) === format)
  const points = new Set()
  const full = pick(3, 10, 12)
  if (full) {
    for (let i = 0, groups = cmap.readUInt32BE(full.offset + 12); i < groups; i++) {
      const at = full.offset + 16 + i * 12
      const first = cmap.readUInt32BE(at), last = cmap.readUInt32BE(at + 4), glyph = cmap.readUInt32BE(at + 8)
      for (let c = first; c <= last; c++) if (glyph + c - first) points.add(c)
    }
    return points
  }
  const bmp = pick(3, 1, 4)
  if (!bmp) throw new Error(`유니코드 cmap 부표가 없습니다: ${path}`)
  const segments = cmap.readUInt16BE(bmp.offset + 6) / 2
  const ends = bmp.offset + 14, starts = ends + segments * 2 + 2, deltas = starts + segments * 2, rangeOffsets = deltas + segments * 2
  for (let s = 0; s < segments; s++) {
    const last = cmap.readUInt16BE(ends + s * 2), first = cmap.readUInt16BE(starts + s * 2)
    const delta = cmap.readInt16BE(deltas + s * 2), rangeOffset = cmap.readUInt16BE(rangeOffsets + s * 2)
    for (let c = first; c <= last && c !== 0xffff; c++) {
      let glyph = rangeOffset ? cmap.readUInt16BE(rangeOffsets + s * 2 + rangeOffset + (c - first) * 2) : c
      if (rangeOffset && !glyph) continue
      glyph = (glyph + delta) & 0xffff
      if (glyph) points.add(c)
    }
  }
  return points
}

// 연속한 글자 번호를 CSS unicode-range 구간으로 줄인다.
function unicodeRange(points) {
  const sorted = [...points].sort((a, b) => a - b)
  const parts = []
  for (let i = 0; i < sorted.length; i++) {
    let j = i
    while (j + 1 < sorted.length && sorted[j + 1] === sorted[j] + 1) j++
    const hex = c => c.toString(16).toUpperCase()
    parts.push(i === j ? `U+${hex(sorted[i])}` : `U+${hex(sorted[i])}-${hex(sorted[j])}`)
    i = j
  }
  return parts.join(", ")
}

const face = (weight, display, points, path) => `@font-face { font-family: "${family}"; font-weight: ${weight}; font-display: ${display}; `
  + `unicode-range: ${unicodeRange(points)}; src: url("../${path}") format("woff2"); }\n`

function render() {
  let css = `/* frontend/scripts/generate-fonts.mjs로 생성(npm run fonts). 굵기는 web_tokens.json의 bundled-font를 수정하세요.\n`
    + `   unicode-range는 pretendard ${version} woff2의 cmap에서 계산한다. 실행 중 네트워크에서 받지 않는다.\n`
    + `   block: 첫 렌더용 부분 집합이 가진 글자. main.tsx가 첫 렌더 전에 읽어 대체 글꼴이 먼저 보였다가 바뀌지 않는다.\n`
    + `   swap: 전체 파일에만 있는 글자(드문 한글 음절·확장 라틴·기호·한자 등). 화면에 나올 때만 읽는다. 줄 높이와 카드 칸이 고정이라 바뀌어도 배치가 밀리지 않는다. */\n`
  for (const [weight, stem] of Object.entries(weights)) {
    const { first, rest } = files(stem)
    const subset = codePoints(first)
    const all = codePoints(rest)
    const extra = [...subset].filter(c => !all.has(c))
    if (extra.length) throw new Error(`부분 집합에만 있는 글자가 있습니다(${first}): ${unicodeRange(extra)}`)
    css += face(weight, "block", subset, first) + face(weight, "swap", [...all].filter(c => !subset.has(c)), rest)
  }
  return css
}

const css = render()
if (process.argv.includes("--check")) {
  let current = ""
  // checkout 때 줄 끝이 CRLF로 바뀔 수 있어 줄 끝은 비교하지 않는다.
  try { current = readFileSync(output, "utf8").replace(/\r\n/g, "\n") } catch { /* 없으면 드리프트 */ }
  if (current !== css) {
    console.error("src/fonts.css가 생성 결과와 다릅니다. frontend에서 npm run fonts를 실행하세요.")
    process.exit(1)
  }
} else {
  writeFileSync(output, css)
}
