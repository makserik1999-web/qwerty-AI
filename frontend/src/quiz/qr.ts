/**
 * QR codes for the join link, drawn here rather than by a library.
 *
 * The projector shows a code a class points its phone cameras at - the
 * fastest way thirty people reach one URL - and the project adds no
 * dependency for a hundred and fifty lines of well-specified arithmetic.
 *
 * ISO/IEC 18004 Model 2, byte mode, error correction level M (15% of the
 * symbol recoverable: a projector with a smudge on it still scans), versions
 * 1-15, which holds up to 412 bytes - far beyond any join link. The steps are
 * the standard's: data bits, Reed-Solomon blocks, interleave, place in the
 * zigzag around the function patterns, try all eight masks, keep the one with
 * the lowest penalty. Checked against a real decoder (OpenCV) while written.
 */

export interface QrMatrix {
  size: number
  /** modules[y][x] - true is dark. */
  modules: boolean[][]
}

const MAX_VERSION = 15
// Level M, per version (index 0 unused).
const EC_PER_BLOCK = [-1, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26, 30, 22, 22, 24, 24]
const BLOCKS = [-1, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5, 5, 8, 9, 9, 10]
// Format bits name level M as 00.
const LEVEL_M_BITS = 0

function rawDataModules(version: number): number {
  let result = (16 * version + 128) * version + 64
  if (version >= 2) {
    const align = Math.floor(version / 7) + 2
    result -= (25 * align - 10) * align - 55
    if (version >= 7) result -= 36
  }
  return result
}

function dataCodewords(version: number): number {
  return Math.floor(rawDataModules(version) / 8) - EC_PER_BLOCK[version] * BLOCKS[version]
}

/* ------------------------------------------------------ Reed-Solomon -- */

function gfMultiply(x: number, y: number): number {
  let z = 0
  for (let i = 7; i >= 0; i--) {
    z = (z << 1) ^ ((z >>> 7) * 0x11d)
    z ^= ((y >>> i) & 1) * x
  }
  return z & 0xff
}

function rsDivisor(degree: number): number[] {
  const result = new Array<number>(degree).fill(0)
  result[degree - 1] = 1
  let root = 1
  for (let i = 0; i < degree; i++) {
    for (let j = 0; j < result.length; j++) {
      result[j] = gfMultiply(result[j], root)
      if (j + 1 < result.length) result[j] ^= result[j + 1]
    }
    root = gfMultiply(root, 0x02)
  }
  return result
}

function rsRemainder(data: number[], divisor: number[]): number[] {
  const result = divisor.map(() => 0)
  for (const byte of data) {
    const factor = byte ^ (result.shift() as number)
    result.push(0)
    divisor.forEach((coefficient, i) => {
      result[i] ^= gfMultiply(coefficient, factor)
    })
  }
  return result
}

/* ------------------------------------------------------------ the data -- */

function encodeData(bytes: Uint8Array, version: number): number[] {
  const bits: number[] = []
  const push = (value: number, length: number) => {
    for (let i = length - 1; i >= 0; i--) bits.push((value >>> i) & 1)
  }
  push(0b0100, 4)
  push(bytes.length, version <= 9 ? 8 : 16)
  bytes.forEach((byte) => push(byte, 8))

  const capacity = dataCodewords(version) * 8
  push(0, Math.min(4, capacity - bits.length))
  push(0, (8 - (bits.length % 8)) % 8)
  for (let pad = 0xec; bits.length < capacity; pad ^= 0xec ^ 0x11) push(pad, 8)

  const words: number[] = []
  for (let i = 0; i < bits.length; i += 8) {
    words.push(bits.slice(i, i + 8).reduce((acc, bit) => (acc << 1) | bit, 0))
  }
  return words
}

function withErrorCorrection(data: number[], version: number): number[] {
  const blocks = BLOCKS[version]
  const ecLength = EC_PER_BLOCK[version]
  const raw = Math.floor(rawDataModules(version) / 8)
  const shortBlocks = blocks - (raw % blocks)
  const shortLength = Math.floor(raw / blocks)
  const divisor = rsDivisor(ecLength)

  const all: number[][] = []
  for (let i = 0, k = 0; i < blocks; i++) {
    const block = data.slice(k, k + shortLength - ecLength + (i < shortBlocks ? 0 : 1))
    k += block.length
    const ec = rsRemainder(block, divisor)
    if (i < shortBlocks) block.push(0)
    all.push(block.concat(ec))
  }

  const result: number[] = []
  for (let i = 0; i < all[0].length; i++) {
    all.forEach((block, j) => {
      // The padding byte added to short blocks is not a codeword.
      if (i !== shortLength - ecLength || j >= shortBlocks) result.push(block[i])
    })
  }
  return result
}

/* ------------------------------------------------------------- drawing -- */

class QrSymbol {
  readonly size: number
  readonly modules: boolean[][]
  readonly isFunction: boolean[][]

  constructor(readonly version: number) {
    this.size = version * 4 + 17
    this.modules = Array.from({ length: this.size }, () => new Array<boolean>(this.size).fill(false))
    this.isFunction = Array.from({ length: this.size }, () =>
      new Array<boolean>(this.size).fill(false),
    )
  }

  set(x: number, y: number, dark: boolean) {
    this.modules[y][x] = dark
    this.isFunction[y][x] = true
  }

  drawFunctionPatterns() {
    for (let i = 0; i < this.size; i++) {
      this.set(6, i, i % 2 === 0)
      this.set(i, 6, i % 2 === 0)
    }
    this.finder(3, 3)
    this.finder(this.size - 4, 3)
    this.finder(3, this.size - 4)

    const positions = this.alignmentPositions()
    const last = positions.length - 1
    positions.forEach((x, i) =>
      positions.forEach((y, j) => {
        const corner = (i === 0 && j === 0) || (i === 0 && j === last) || (i === last && j === 0)
        if (!corner) this.alignment(x, y)
      }),
    )
    this.formatBits(0)
    this.versionBits()
  }

  finder(cx: number, cy: number) {
    for (let dy = -4; dy <= 4; dy++) {
      for (let dx = -4; dx <= 4; dx++) {
        const x = cx + dx
        const y = cy + dy
        if (x < 0 || y < 0 || x >= this.size || y >= this.size) continue
        const distance = Math.max(Math.abs(dx), Math.abs(dy))
        this.set(x, y, distance !== 2 && distance !== 4)
      }
    }
  }

  alignment(cx: number, cy: number) {
    for (let dy = -2; dy <= 2; dy++) {
      for (let dx = -2; dx <= 2; dx++) {
        this.set(cx + dx, cy + dy, Math.max(Math.abs(dx), Math.abs(dy)) !== 1)
      }
    }
  }

  alignmentPositions(): number[] {
    if (this.version === 1) return []
    const count = Math.floor(this.version / 7) + 2
    const step = Math.ceil((this.version * 4 + 4) / (count * 2 - 2)) * 2
    const result = [6]
    for (let pos = this.size - 7; result.length < count; pos -= step) result.splice(1, 0, pos)
    return result
  }

  formatBits(mask: number) {
    const data = (LEVEL_M_BITS << 3) | mask
    let rem = data
    for (let i = 0; i < 10; i++) rem = (rem << 1) ^ ((rem >>> 9) * 0x537)
    const bits = ((data << 10) | rem) ^ 0x5412
    const bit = (i: number) => ((bits >>> i) & 1) !== 0

    for (let i = 0; i <= 5; i++) this.set(8, i, bit(i))
    this.set(8, 7, bit(6))
    this.set(8, 8, bit(7))
    this.set(7, 8, bit(8))
    for (let i = 9; i < 15; i++) this.set(14 - i, 8, bit(i))

    for (let i = 0; i < 8; i++) this.set(this.size - 1 - i, 8, bit(i))
    for (let i = 8; i < 15; i++) this.set(8, this.size - 15 + i, bit(i))
    this.set(8, this.size - 8, true)
  }

  versionBits() {
    if (this.version < 7) return
    let rem = this.version
    for (let i = 0; i < 12; i++) rem = (rem << 1) ^ ((rem >>> 11) * 0x1f25)
    const bits = (this.version << 12) | rem
    for (let i = 0; i < 18; i++) {
      const dark = ((bits >>> i) & 1) !== 0
      const a = this.size - 11 + (i % 3)
      const b = Math.floor(i / 3)
      this.set(a, b, dark)
      this.set(b, a, dark)
    }
  }

  drawCodewords(codewords: number[]) {
    let i = 0
    for (let right = this.size - 1; right >= 1; right -= 2) {
      if (right === 6) right = 5
      for (let vert = 0; vert < this.size; vert++) {
        for (let j = 0; j < 2; j++) {
          const x = right - j
          const upward = ((right + 1) & 2) === 0
          const y = upward ? this.size - 1 - vert : vert
          if (!this.isFunction[y][x] && i < codewords.length * 8) {
            this.modules[y][x] = ((codewords[i >>> 3] >>> (7 - (i & 7))) & 1) !== 0
            i++
          }
        }
      }
    }
  }

  applyMask(mask: number) {
    for (let y = 0; y < this.size; y++) {
      for (let x = 0; x < this.size; x++) {
        if (this.isFunction[y][x]) continue
        let invert: boolean
        switch (mask) {
          case 0: invert = (x + y) % 2 === 0; break
          case 1: invert = y % 2 === 0; break
          case 2: invert = x % 3 === 0; break
          case 3: invert = (x + y) % 3 === 0; break
          case 4: invert = (Math.floor(x / 3) + Math.floor(y / 2)) % 2 === 0; break
          case 5: invert = ((x * y) % 2) + ((x * y) % 3) === 0; break
          case 6: invert = (((x * y) % 2) + ((x * y) % 3)) % 2 === 0; break
          default: invert = (((x + y) % 2) + ((x * y) % 3)) % 2 === 0
        }
        if (invert) this.modules[y][x] = !this.modules[y][x]
      }
    }
  }

  penalty(): number {
    const size = this.size
    let result = 0

    const line = (get: (a: number, b: number) => boolean) => {
      for (let a = 0; a < size; a++) {
        let runColor = false
        let run = 0
        const history = [0, 0, 0, 0, 0, 0, 0]
        const addHistory = (length: number) => {
          if (history[0] === 0) length += size
          history.pop()
          history.unshift(length)
        }
        const finderLike = () => {
          const n = history[1]
          const core =
            n > 0 && history[2] === n && history[3] === n * 3 && history[4] === n && history[5] === n
          return (
            (core && history[0] >= n * 4 && history[6] >= n ? 1 : 0) +
            (core && history[6] >= n * 4 && history[0] >= n ? 1 : 0)
          )
        }
        for (let b = 0; b < size; b++) {
          if (get(a, b) === runColor) {
            run++
            if (run === 5) result += 3
            else if (run > 5) result++
          } else {
            addHistory(run)
            if (!runColor) result += finderLike() * 40
            runColor = get(a, b)
            run = 1
          }
        }
        if (runColor) {
          addHistory(run)
          run = 0
        }
        addHistory(run + size)
        result += finderLike() * 40
      }
    }
    line((y, x) => this.modules[y][x])
    line((x, y) => this.modules[y][x])

    for (let y = 0; y < size - 1; y++) {
      for (let x = 0; x < size - 1; x++) {
        const c = this.modules[y][x]
        if (c === this.modules[y][x + 1] && c === this.modules[y + 1][x] && c === this.modules[y + 1][x + 1]) {
          result += 3
        }
      }
    }

    const dark = this.modules.reduce((sum, row) => sum + row.filter(Boolean).length, 0)
    const total = size * size
    result += (Math.ceil(Math.abs(dark * 20 - total * 10) / total) - 1) * 10
    return result
  }
}

export function encodeQr(text: string): QrMatrix {
  const bytes = new TextEncoder().encode(text)
  let version = 1
  for (; version <= MAX_VERSION; version++) {
    const needed = 4 + (version <= 9 ? 8 : 16) + bytes.length * 8
    if (needed <= dataCodewords(version) * 8) break
  }
  if (version > MAX_VERSION) throw new Error('text too long for a join code')

  const codewords = withErrorCorrection(encodeData(bytes, version), version)
  const symbol = new QrSymbol(version)
  symbol.drawFunctionPatterns()
  symbol.drawCodewords(codewords)

  let best = 0
  let lowest = Infinity
  for (let mask = 0; mask < 8; mask++) {
    symbol.applyMask(mask)
    symbol.formatBits(mask)
    const score = symbol.penalty()
    if (score < lowest) {
      lowest = score
      best = mask
    }
    symbol.applyMask(mask) // masks are their own inverse
  }
  symbol.applyMask(best)
  symbol.formatBits(best)
  return { size: symbol.size, modules: symbol.modules }
}

/** One SVG path for every dark module, merged into horizontal runs. */
export function qrPath(matrix: QrMatrix, margin = 4): string {
  const parts: string[] = []
  matrix.modules.forEach((row, y) => {
    let x = 0
    while (x < matrix.size) {
      if (!row[x]) {
        x++
        continue
      }
      const start = x
      while (x < matrix.size && row[x]) x++
      parts.push(`M${start + margin} ${y + margin}h${x - start}v1h${start - x}z`)
    }
  })
  return parts.join('')
}
