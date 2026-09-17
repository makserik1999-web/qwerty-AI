import type { SceneId } from '../../lib/types'
import { appear, eased, lerp, phase, polygon, round, VIEW_H, VIEW_W } from './helpers'

export interface SceneProps {
  /** Playback position, 0 → 1. */
  p: number
}

/* -------------------------------------------------------------------------- */
/* Shared scene furniture                                                      */
/* -------------------------------------------------------------------------- */

function Grid() {
  const lines = []
  for (let x = 40; x < VIEW_W; x += 40) {
    lines.push(<line key={`v${x}`} x1={x} y1={0} x2={x} y2={VIEW_H} />)
  }
  for (let y = 40; y < VIEW_H; y += 40) {
    lines.push(<line key={`h${y}`} x1={0} y1={y} x2={VIEW_W} y2={y} />)
  }
  return <g className="scene__grid">{lines}</g>
}

function Caption({ text, opacity = 1 }: { text: string; opacity?: number }) {
  return (
    <text className="scene__caption" x={32} y={VIEW_H - 28} opacity={opacity}>
      {text}
    </text>
  )
}

/* -------------------------------------------------------------------------- */
/* 1. Pythagoras — squares on the three sides                                  */
/* -------------------------------------------------------------------------- */

function PythagorasScene({ p }: SceneProps) {
  const C: [number, number] = [230, 250] // right angle
  const A: [number, number] = [350, 250] // end of leg a
  const B: [number, number] = [230, 160] // end of leg b

  const draw = eased(p, 0, 0.18)
  const kA = eased(p, 0.2, 0.4)
  const kB = eased(p, 0.32, 0.52)
  const kC = eased(p, 0.56, 0.8)
  const showSum = appear(p, 0.82, 0.1)

  const squareA = polygon([C, A, [A[0], A[1] + 120 * kA], [C[0], C[1] + 120 * kA]])
  const squareB = polygon([C, B, [B[0] - 90 * kB, B[1]], [C[0] - 90 * kB, C[1]]])
  // Outward normal of the hypotenuse, so the third square grows away from the triangle.
  const n: [number, number] = [90, -120]
  const squareC = polygon([
    A,
    B,
    [B[0] + n[0] * kC, B[1] + n[1] * kC],
    [A[0] + n[0] * kC, A[1] + n[1] * kC],
  ])

  return (
    <g>
      <Grid />
      <polygon className="scene__fill-a" points={squareA} opacity={kA} />
      <polygon className="scene__fill-b" points={squareB} opacity={kB} />
      <polygon className="scene__fill-c" points={squareC} opacity={kC} />

      <polygon
        className="scene__shape"
        points={polygon([C, A, B])}
        strokeDasharray={440}
        strokeDashoffset={440 * (1 - draw)}
      />
      {/* right-angle marker */}
      <polyline
        className="scene__hint"
        points={polygon([
          [C[0] + 16, C[1]],
          [C[0] + 16, C[1] - 16],
          [C[0], C[1] - 16],
        ])}
        opacity={draw}
      />

      <text className="scene__label" x={290} y={272} opacity={draw}>
        a
      </text>
      <text className="scene__label" x={212} y={210} opacity={draw}>
        b
      </text>
      <text className="scene__label" x={300} y={195} opacity={draw}>
        c
      </text>

      <text className="scene__value" x={268} y={330} opacity={kA} textAnchor="middle">
        a²
      </text>
      <text className="scene__value" x={186} y={212} opacity={kB} textAnchor="middle">
        b²
      </text>
      <text className="scene__value" x={340} y={150} opacity={kC} textAnchor="middle">
        c²
      </text>

      <text className="scene__formula" x={430} y={330} opacity={showSum}>
        a² + b² = c²
      </text>
      <Caption text="Pythagoras" opacity={0.001} />
    </g>
  )
}

/* -------------------------------------------------------------------------- */
/* 2. Quadratic — the parabola keeps its shape while a, b, c move it           */
/* -------------------------------------------------------------------------- */

const AXIS_X0 = 90
const AXIS_Y0 = 300
const UNIT = 34

function toX(x: number): number {
  return AXIS_X0 + 230 + x * UNIT
}
function toY(y: number): number {
  return AXIS_Y0 - y * UNIT
}

function QuadraticScene({ p }: SceneProps) {
  const drawAxes = eased(p, 0, 0.12)
  const drawCurve = eased(p, 0.12, 0.42)
  const morph = eased(p, 0.48, 0.72)
  const showVertex = appear(p, 0.76, 0.1)

  const a = lerp(1, 0.55, morph)
  const h = lerp(0, -1.6, morph)
  const k = lerp(0, -1.4, morph)

  const points: Array<[number, number]> = []
  const span = 3.4
  const steps = 80
  const visible = Math.round(steps * drawCurve)
  for (let i = 0; i <= visible; i += 1) {
    const t = -span + (i / steps) * span * 2
    const y = a * (t - h) * (t - h) + k
    if (y > 4.4) continue
    points.push([toX(t), toY(y)])
  }

  return (
    <g>
      <Grid />
      <g opacity={drawAxes} className="scene__axis">
        <line x1={60} y1={AXIS_Y0} x2={VIEW_W - 40} y2={AXIS_Y0} />
        <line x1={toX(0)} y1={40} x2={toX(0)} y2={VIEW_H - 50} />
        <text className="scene__label" x={VIEW_W - 46} y={AXIS_Y0 + 24}>
          x
        </text>
        <text className="scene__label" x={toX(0) + 12} y={52}>
          y
        </text>
      </g>

      <polyline className="scene__curve" points={polygon(points)} />

      <g opacity={showVertex}>
        <circle className="scene__point" cx={toX(h)} cy={toY(k)} r={6} />
        <text className="scene__label" x={toX(h) + 14} y={toY(k) - 12}>
          ({round(h)}; {round(k)})
        </text>
      </g>

      <text className="scene__formula" x={40} y={376}>
        y = {round(a)}(x {h < 0 ? '+' : '−'} {Math.abs(round(h))})² {k < 0 ? '−' : '+'}{' '}
        {Math.abs(round(k))}
      </text>
      <Caption text="Quadratic" opacity={0.001} />
    </g>
  )
}

/* -------------------------------------------------------------------------- */
/* 3. Circle area — sectors unroll into a rectangle                            */
/* -------------------------------------------------------------------------- */

const SECTORS = 12
const R = 92
const CX = 200
const CY = 190

function sectorPath(radius: number, sweepDeg: number): string {
  const rad = (sweepDeg * Math.PI) / 180
  const x = radius * Math.cos(rad)
  const y = radius * Math.sin(rad)
  return `M0,0 L${round(radius)},0 A${radius},${radius} 0 0 1 ${round(x)},${round(y)} Z`
}

function CircleAreaScene({ p }: SceneProps) {
  const grow = eased(p, 0, 0.16)
  const split = eased(p, 0.18, 0.34)
  const sweep = 360 / SECTORS
  const arc = (R * sweep * Math.PI) / 180
  const baseX = 250
  const baseY = 300

  return (
    <g>
      <Grid />
      <g opacity={grow}>
        {Array.from({ length: SECTORS }, (_, i) => {
          const move = eased(p, 0.4 + i * 0.018, 0.72 + i * 0.018)
          const startAngle = i * sweep
          const column = Math.floor(i / 2)
          const up = i % 2 === 0
          const finalX = baseX + column * arc + (up ? 0 : arc)
          const finalY = up ? baseY : baseY - R
          const finalRot = up ? -90 : 90
          const x = lerp(CX, finalX, move)
          const y = lerp(CY, finalY, move)
          const rot = lerp(startAngle, finalRot, move)
          return (
            <path
              key={i}
              className={
                i % 2 === 0 ? 'scene__sector' : 'scene__sector scene__sector--alt'
              }
              d={sectorPath(R * grow, sweep)}
              transform={`translate(${round(x)} ${round(y)}) rotate(${round(rot)})`}
              strokeOpacity={split}
            />
          )
        })}
      </g>

      <g opacity={1 - eased(p, 0.34, 0.5)}>
        <line className="scene__hint" x1={CX} y1={CY} x2={CX + R} y2={CY} />
        <text className="scene__label" x={CX + R / 2 - 6} y={CY - 10}>
          r
        </text>
      </g>

      <g opacity={eased(p, 0.74, 0.86)}>
        <line
          className="scene__hint"
          x1={baseX - 14}
          y1={baseY}
          x2={baseX - 14}
          y2={baseY - R}
        />
        <text className="scene__label" x={baseX - 40} y={baseY - R / 2}>
          r
        </text>
        <line
          className="scene__hint"
          x1={baseX}
          y1={baseY + 18}
          x2={baseX + arc * (SECTORS / 2)}
          y2={baseY + 18}
        />
        <text className="scene__label" x={baseX + arc * 2.4} y={baseY + 40}>
          πr
        </text>
      </g>

      <text className="scene__formula" x={40} y={70} opacity={appear(p, 0.86, 0.1)}>
        S = r · πr = πr²
      </text>
      <Caption text="Circle area" opacity={0.001} />
    </g>
  )
}

/* -------------------------------------------------------------------------- */
/* 4. Photosynthesis — inputs enter the leaf, outputs leave                    */
/* -------------------------------------------------------------------------- */

function Molecule({
  x,
  y,
  label,
  tone,
  opacity = 1,
}: {
  x: number
  y: number
  label: string
  tone: 'in' | 'out' | 'sun'
  opacity?: number
}) {
  return (
    <g transform={`translate(${round(x)} ${round(y)})`} opacity={opacity}>
      <circle className={`scene__molecule scene__molecule--${tone}`} r={26} />
      <text className="scene__molecule-text" y={5} textAnchor="middle">
        {label}
      </text>
    </g>
  )
}

function PhotosynthesisScene({ p }: SceneProps) {
  const leaf = eased(p, 0, 0.14)
  const rays = eased(p, 0.16, 0.34)
  const inFlow = eased(p, 0.3, 0.56)
  const outFlow = eased(p, 0.6, 0.86)
  const formula = appear(p, 0.88, 0.1)

  const leafPath = `M320,120 C400,120 440,180 430,250 C360,262 300,232 296,168 C294,142 302,126 320,120 Z`

  return (
    <g>
      <Grid />
      {/* sun + rays */}
      <g opacity={rays}>
        <circle className="scene__sun" cx={110} cy={90} r={26} />
        {Array.from({ length: 5 }, (_, i) => {
          const y = 130 + i * 12
          const progress = Math.min(1, Math.max(0, rays * 1.4 - i * 0.1))
          return (
            <line
              key={i}
              className="scene__ray"
              x1={130}
              y1={y}
              x2={lerp(130, 300, progress)}
              y2={lerp(y, 170 + i * 8, progress)}
            />
          )
        })}
      </g>

      <path className="scene__leaf" d={leafPath} opacity={leaf} />
      <path
        className="scene__leaf-vein"
        d="M300,170 C340,200 390,225 428,246"
        opacity={leaf}
      />

      <Molecule
        x={lerp(80, 300, inFlow)}
        y={lerp(300, 220, inFlow)}
        label="CO₂"
        tone="in"
        opacity={inFlow}
      />
      <Molecule
        x={lerp(150, 320, inFlow)}
        y={lerp(350, 250, inFlow)}
        label="H₂O"
        tone="in"
        opacity={inFlow}
      />
      <Molecule
        x={lerp(420, 560, outFlow)}
        y={lerp(160, 110, outFlow)}
        label="O₂"
        tone="out"
        opacity={outFlow}
      />
      <Molecule
        x={lerp(420, 560, outFlow)}
        y={lerp(240, 290, outFlow)}
        label="C₆H₁₂O₆"
        tone="out"
        opacity={outFlow}
      />

      <text className="scene__formula" x={40} y={372} opacity={formula}>
        6CO₂ + 6H₂O → C₆H₁₂O₆ + 6O₂
      </text>
      <Caption text="Photosynthesis" opacity={0.001} />
    </g>
  )
}

/* -------------------------------------------------------------------------- */
/* 5. Newton's second law — same force, different mass                         */
/* -------------------------------------------------------------------------- */

function NewtonScene({ p }: SceneProps) {
  const setup = eased(p, 0, 0.14)
  const run = phase(p, 0.24, 0.82)
  const formula = appear(p, 0.84, 0.1)

  // Both carts get the same push; the heavier one accelerates half as fast.
  const lightX = 150 + 300 * run * run
  const heavyX = 150 + 150 * run * run
  const arrow = eased(p, 0.16, 0.26)

  return (
    <g>
      <Grid />
      {[
        { y: 140, x: lightX, size: 46, label: 'm', tone: 'a' },
        { y: 270, x: heavyX, size: 62, label: '2m', tone: 'b' },
      ].map((cart) => (
        <g key={cart.label}>
          <line
            className="scene__axis"
            x1={90}
            y1={cart.y + 34}
            x2={VIEW_W - 40}
            y2={cart.y + 34}
          />
          <g opacity={setup}>
            <rect
              className={`scene__box scene__box--${cart.tone}`}
              x={cart.x}
              y={cart.y + 34 - cart.size}
              width={cart.size}
              height={cart.size}
              rx={6}
            />
            <text
              className="scene__value"
              x={cart.x + cart.size / 2}
              y={cart.y + 32 - cart.size / 2}
              textAnchor="middle"
            >
              {cart.label}
            </text>
          </g>
          <g opacity={arrow}>
            <line
              className="scene__arrow"
              x1={cart.x - 70}
              y1={cart.y + 34 - cart.size / 2}
              x2={cart.x - 10}
              y2={cart.y + 34 - cart.size / 2}
              markerEnd="url(#anyq-arrow)"
            />
            <text
              className="scene__label"
              x={cart.x - 78}
              y={cart.y + 40 - cart.size / 2}
              textAnchor="end"
            >
              F
            </text>
          </g>
        </g>
      ))}

      <text className="scene__formula" x={40} y={70} opacity={formula}>
        F = m · a → a = F / m
      </text>
      <Caption text="Newton" opacity={0.001} />
    </g>
  )
}

/* -------------------------------------------------------------------------- */
/* 6. Derivative — the secant turns into a tangent                             */
/* -------------------------------------------------------------------------- */

function curveY(x: number): number {
  return 0.35 * x * x
}

function DerivativeScene({ p }: SceneProps) {
  const axes = eased(p, 0, 0.1)
  const curve = eased(p, 0.08, 0.32)
  const close = eased(p, 0.36, 0.8)
  const formula = appear(p, 0.84, 0.1)

  const x0 = -1.2
  const h = lerp(2.6, 0.02, close)
  const x1 = x0 + h
  const y0 = curveY(x0)
  const y1 = curveY(x1)
  const slope = h === 0 ? 0 : (y1 - y0) / h

  const points: Array<[number, number]> = []
  const steps = 70
  const visible = Math.round(steps * curve)
  for (let i = 0; i <= visible; i += 1) {
    const t = -3 + (i / steps) * 6
    const y = curveY(t)
    if (y > 4.6) continue
    points.push([toX(t), toY(y)])
  }

  const lineFrom: [number, number] = [toX(x0 - 2), toY(y0 + slope * -2)]
  const lineTo: [number, number] = [toX(x0 + 2.6), toY(y0 + slope * 2.6)]

  return (
    <g>
      <Grid />
      <g opacity={axes} className="scene__axis">
        <line x1={60} y1={AXIS_Y0} x2={VIEW_W - 40} y2={AXIS_Y0} />
        <line x1={toX(0)} y1={40} x2={toX(0)} y2={VIEW_H - 50} />
      </g>

      <polyline className="scene__curve" points={polygon(points)} />

      <g opacity={curve}>
        <line
          className={close > 0.94 ? 'scene__tangent' : 'scene__secant'}
          x1={lineFrom[0]}
          y1={lineFrom[1]}
          x2={lineTo[0]}
          y2={lineTo[1]}
        />
        <circle className="scene__point" cx={toX(x0)} cy={toY(y0)} r={6} />
        <circle
          className="scene__point scene__point--alt"
          cx={toX(x1)}
          cy={toY(y1)}
          r={6}
          opacity={1 - close * 0.9}
        />
        <text className="scene__label" x={toX(x0) - 26} y={toY(y0) + 6}>
          x
        </text>
        <text
          className="scene__label"
          x={toX(x1) + 12}
          y={toY(y1) + 4}
          opacity={1 - close}
        >
          x + h
        </text>
      </g>

      <text className="scene__formula" x={40} y={340}>
        h = {round(Math.max(0, h))}
      </text>
      <text className="scene__formula" x={40} y={374} opacity={formula}>
        f′(x) = {round(slope)}
      </text>
      <Caption text="Derivative" opacity={0.001} />
    </g>
  )
}

/* -------------------------------------------------------------------------- */
/* 7. Balancing a chemical equation                                            */
/* -------------------------------------------------------------------------- */

function AtomPair({
  x,
  y,
  labels,
  tone,
}: {
  x: number
  y: number
  labels: string[]
  tone: 'in' | 'out'
}) {
  return (
    <g transform={`translate(${x} ${y})`}>
      {labels.map((label, index) => (
        <g key={index} transform={`translate(${index * 34} 0)`}>
          <circle className={`scene__atom scene__atom--${tone}`} r={17} />
          <text className="scene__atom-text" y={5} textAnchor="middle">
            {label}
          </text>
        </g>
      ))}
    </g>
  )
}

function ReactionScene({ p }: SceneProps) {
  const start = eased(p, 0, 0.12)
  const mismatch = appear(p, 0.2, 0.1) * (1 - appear(p, 0.5, 0.08))
  const balance = eased(p, 0.52, 0.76)
  const done = appear(p, 0.8, 0.1)

  return (
    <g>
      <Grid />
      <g opacity={start}>
        <text className="scene__coeff" x={72} y={150} opacity={balance}>
          2
        </text>
        <AtomPair x={100} y={140} labels={['H', 'H']} tone="in" />
        <text className="scene__formula" x={168} y={148}>
          +
        </text>
        <AtomPair x={200} y={140} labels={['O', 'O']} tone="in" />
        <line
          className="scene__arrow"
          x1={280}
          y1={140}
          x2={340}
          y2={140}
          markerEnd="url(#anyq-arrow)"
        />
        <text className="scene__coeff" x={352} y={150} opacity={balance}>
          2
        </text>
        <AtomPair x={382} y={140} labels={['H', 'H', 'O']} tone="out" />
      </g>

      {/* second copy of each molecule appears once the coefficients are placed */}
      <g opacity={balance}>
        <AtomPair x={100} y={218} labels={['H', 'H']} tone="in" />
        <AtomPair x={382} y={218} labels={['H', 'H', 'O']} tone="out" />
      </g>

      <g className="scene__tally">
        <text
          x={100}
          y={310}
          className={mismatch > 0.5 ? 'scene__tally--bad' : undefined}
        >
          H: {balance > 0.5 ? 4 : 2} · O: 2
        </text>
        <text
          x={382}
          y={310}
          className={mismatch > 0.5 ? 'scene__tally--bad' : undefined}
        >
          H: {balance > 0.5 ? 4 : 2} · O: {balance > 0.5 ? 2 : 1}
        </text>
      </g>

      <text className="scene__formula" x={40} y={366} opacity={done}>
        2H₂ + O₂ → 2H₂O
      </text>
      <Caption text="Reaction" opacity={0.001} />
    </g>
  )
}

/* -------------------------------------------------------------------------- */

export const SCENES: Record<SceneId, (props: SceneProps) => JSX.Element> = {
  pythagoras: PythagorasScene,
  quadratic: QuadraticScene,
  circleArea: CircleAreaScene,
  photosynthesis: PhotosynthesisScene,
  newton: NewtonScene,
  derivative: DerivativeScene,
  reaction: ReactionScene,
}

/** Language-neutral scene titles, shown as the animation's own caption. */
export const SCENE_TITLES: Record<SceneId, string> = {
  pythagoras: 'a² + b² = c²',
  quadratic: 'y = ax² + bx + c',
  circleArea: 'S = πr²',
  photosynthesis: '6CO₂ + 6H₂O → C₆H₁₂O₆ + 6O₂',
  newton: 'F = m · a',
  derivative: 'f′(x) = lim (h→0)',
  reaction: '2H₂ + O₂ → 2H₂O',
}
