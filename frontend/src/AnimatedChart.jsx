import React, { useEffect, useId, useMemo, useRef, useState } from 'react'

const FONT = "'Segoe UI', system-ui, -apple-system, sans-serif"
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

function rgbOf(hex) {
  const c = String(hex || '#0054FC').replace('#', '')
  const s = c.length === 3 ? c.split('').map(x => x + x).join('') : c
  const n = parseInt(s, 16)
  if (Number.isNaN(n)) return '0,84,252'
  return `${(n >> 16) & 255},${(n >> 8) & 255},${n & 255}`
}

/**
 * Axis scale with whole-number steps for small ranges (an email chart must
 * never show 0.5 / 1.5 on the Y axis) and magnitude steps for big ones.
 */
function niceScale(rawMax) {
  const max = Math.max(0, rawMax || 0)
  let step
  if (max <= 20) step = max <= 4 ? 1 : max <= 10 ? 2 : 5
  else {
    const target = max / 4
    const mag = Math.pow(10, Math.floor(Math.log10(target)))
    const n = target / mag
    step = (n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10) * mag
  }
  const niceMax = Math.max(step, Math.ceil(max / step) * step)
  const ticks = []
  for (let v = 0; v <= niceMax + step * 1e-6; v += step) ticks.push(+v.toFixed(6))
  return { max: niceMax, ticks }
}

function fmtNum(v, compact) {
  if (compact) {
    if (Math.abs(v) >= 1e6) return `${+(v / 1e6).toFixed(1)}M`
    if (Math.abs(v) >= 1000) return `${+(v / 1000).toFixed(v % 1000 === 0 ? 0 : 1)}k`
  }
  return Number.isInteger(v) ? String(v) : `${+v.toFixed(1)}`
}

function shortLabel(s) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(s || ''))
  if (m) return `${MONTHS[+m[2] - 1]} ${+m[3]}`
  const t = String(s || '')
  return t.length > 9 ? t.slice(0, 9) : t
}

/**
 * Monotone cubic path (Fritsch-Carlson). Unlike a plain Catmull-Rom it can
 * never overshoot the data, so a flat run followed by a single spike — which
 * is exactly what a 15-day email chart looks like — does not dip below zero.
 */
function monotonePath(pts) {
  const n = pts.length
  if (n === 0) return ''
  if (n === 1) return `M${pts[0].x},${pts[0].y}`
  const dx = [], m = []
  for (let i = 0; i < n - 1; i++) {
    dx[i] = pts[i + 1].x - pts[i].x
    m[i] = (pts[i + 1].y - pts[i].y) / (dx[i] || 1e-6)
  }
  const t = [m[0]]
  for (let i = 1; i < n - 1; i++) {
    if (m[i - 1] * m[i] <= 0) t[i] = 0
    else {
      const w1 = 2 * dx[i] + dx[i - 1]
      const w2 = dx[i] + 2 * dx[i - 1]
      t[i] = (w1 + w2) / (w1 / m[i - 1] + w2 / m[i])
    }
  }
  t[n - 1] = m[n - 2]
  let d = `M${pts[0].x},${pts[0].y}`
  for (let i = 0; i < n - 1; i++) {
    const h = dx[i]
    d += ` C${pts[i].x + h / 3},${pts[i].y + t[i] * h / 3}` +
         ` ${pts[i + 1].x - h / 3},${pts[i + 1].y - t[i + 1] * h / 3}` +
         ` ${pts[i + 1].x},${pts[i + 1].y}`
  }
  return d
}

/**
 * Animated SVG activity chart.
 *
 * Motion: the line draws itself left to right, the area rises into place,
 * grid and labels fade in behind it, and the live tail keeps a slow halo.
 * Everything is driven by CSS animations keyed on the data identity, so a
 * refresh replays the entrance instead of snapping.
 *
 * data: [{ label, ...values }]
 * seriesA / seriesB: { key, name, color } — pass real hex, not CSS vars.
 */
export default function AnimatedChart({ data = [], seriesA, seriesB, height = 220 }) {
  const wrapRef = useRef(null)
  const uid = useId().replace(/[^a-zA-Z0-9]/g, '') || 'ac'
  const [w, setW] = useState(560)
  const [hover, setHover] = useState(-1)

  const rows = useMemo(() => (Array.isArray(data) ? data : []), [data])

  useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const measure = () => setW(Math.max(260, el.clientWidth || 560))
    measure()
    if (typeof ResizeObserver === 'undefined') return undefined
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  useEffect(() => { setHover(-1) }, [rows])

  const series = useMemo(() => (
    [seriesA, seriesB].filter(Boolean).map(s => ({
      ...s,
      values: rows.map(d => Number(d && d[s.key]) || 0),
    }))
  ), [rows, seriesA, seriesB])

  const replayKey = `${rows.length}|${rows[rows.length - 1]?.label ?? ''}|${
    series.map(s => s.key).join(',')}`

  if (rows.length === 0) {
    return <div className="empty" style={{ height }}>No data yet for this period</div>
  }

  let rawMax = 0
  series.forEach(s => s.values.forEach(v => { if (v > rawMax) rawMax = v }))
  const scale = niceScale(rawMax)
  const compact = scale.max >= 1000

  const yTexts = scale.ticks.map(t => fmtNum(t, compact))
  const left = Math.max(32, yTexts.reduce((m, t) => Math.max(m, t.length), 1) * 7 + 14)
  const right = 16
  const top = 14
  const bottom = 26
  const legendH = 28
  const frameH = Math.max(96, height - legendH)
  const plotW = Math.max(20, w - left - right)
  const plotH = Math.max(30, frameH - top - bottom)

  const n = rows.length
  const xAt = i => left + (n <= 1 ? plotW / 2 : (i * plotW) / (n - 1))
  const yAt = v => top + plotH - (scale.max > 0 ? (v / scale.max) * plotH : 0)

  const geom = series.map(s => ({
    ...s,
    pts: s.values.map((v, i) => ({ x: xAt(i), y: yAt(v) })),
  }))

  const maxLabels = Math.max(2, Math.min(8, Math.floor(plotW / 74)))
  const count = Math.max(2, Math.min(maxLabels, n))
  const labelIdx = [...new Set(
    Array.from({ length: count }, (_, k) => Math.round((k * (n - 1)) / (count - 1)))
  )]

  const handleMove = e => {
    const rect = e.currentTarget.getBoundingClientRect()
    const clientX = e.touches ? e.touches[0].clientX : e.clientX
    const rel = clientX - rect.left - left
    const idx = n > 1 ? Math.round((rel / plotW) * (n - 1)) : 0
    setHover(Math.max(0, Math.min(n - 1, idx)))
  }

  const tipX = hover >= 0 ? xAt(hover) : 0
  const flip = tipX > left + plotW - 110

  return (
    <div className="ac" ref={wrapRef} style={{ height }}>
      <div className="ac-legend">
        {series.map(s => (
          <span className="ac-legend-item" key={s.key}>
            <i className="ac-legend-dot" style={{ background: s.color }} />
            {s.name}
          </span>
        ))}
        <span className="ac-legend-note">
          {rawMax === 0 ? 'No activity in this window' : ' '}
        </span>
      </div>

      <div className="ac-frame" style={{ height: frameH }}>
        <svg key={replayKey} width={w} height={frameH}
             viewBox={`0 0 ${w} ${frameH}`} role="img"
             aria-label="Email activity chart">
          <defs>
            {geom.map(g => (
              <linearGradient key={g.key} id={`${uid}${g.key}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={`rgba(${rgbOf(g.color)},0.30)`} />
                <stop offset="60%" stopColor={`rgba(${rgbOf(g.color)},0.10)`} />
                <stop offset="100%" stopColor={`rgba(${rgbOf(g.color)},0.01)`} />
              </linearGradient>
            ))}
          </defs>

          {/* horizontal grid + Y labels */}
          <g className="ac-grid">
            {scale.ticks.map((t, i) => {
              const y = yAt(t)
              return (
                <g key={i}>
                  <line x1={left} x2={left + plotW} y1={y} y2={y}
                        stroke={i === 0 ? '#dfe5ef' : '#eef1f7'} strokeWidth={1} />
                  <text x={left - 9} y={y} textAnchor="end" dominantBaseline="middle"
                        fill="#8792a8" fontSize={11} fontFamily={FONT}>
                    {yTexts[i]}
                  </text>
                </g>
              )
            })}
          </g>

          {/* X labels */}
          <g className="ac-xlabels">
            {labelIdx.map(i => (
              <text key={i} x={xAt(i)} y={top + plotH + 17}
                    textAnchor={i === 0 ? 'start' : i === n - 1 ? 'end' : 'middle'}
                    fill="#8792a8" fontSize={11} fontFamily={FONT}>
                {shortLabel(rows[i]?.label)}
              </text>
            ))}
          </g>

          {/* areas (back series first) */}
          {[...geom].reverse().map(g => {
            if (n < 2) return null
            const line = monotonePath(g.pts)
            const area = `${line} L${g.pts[n - 1].x},${top + plotH} L${g.pts[0].x},${top + plotH} Z`
            return (
              <path key={g.key} className="ac-area" d={area}
                    fill={`url(#${uid}${g.key})`} />
            )
          })}

          {/* lines */}
          {[...geom].reverse().map(g => (
            n < 2 ? null : (
              <g key={g.key}>
                <path className="ac-line" d={monotonePath(g.pts)} pathLength={1}
                      fill="none" stroke={g.color} strokeWidth={7} strokeOpacity={0.10}
                      strokeLinecap="round" strokeLinejoin="round" />
                <path className="ac-line" d={monotonePath(g.pts)} pathLength={1}
                      fill="none" stroke={g.color} strokeWidth={2.4}
                      strokeLinecap="round" strokeLinejoin="round" />
              </g>
            )
          ))}

          {/* single-point data has no path to draw */}
          {n === 1 && geom.map(g => (
            <circle key={g.key} className="ac-dot" cx={g.pts[0].x} cy={g.pts[0].y}
                    r={4} fill={g.color} />
          ))}

          {/* live halo on the newest non-zero point */}
          {n >= 2 && geom.map(g => {
            let last = -1
            g.values.forEach((v, i) => { if (v > 0) last = i })
            if (last < 0) return null
            return (
              <g key={g.key}>
                <circle className="ac-halo" cx={g.pts[last].x} cy={g.pts[last].y}
                        r={5} fill="none" stroke={g.color} strokeWidth={2} />
                <circle className="ac-dot" cx={g.pts[last].x} cy={g.pts[last].y}
                        r={4.5} fill="#fff" stroke={g.color} strokeWidth={2.4}
                        style={{ animationDelay: '1.05s' }} />
              </g>
            )
          })}

          {/* hover crosshair + points */}
          {hover >= 0 && (
            <g>
              <line className="ac-cross" x1={0} x2={0} y1={top} y2={top + plotH}
                    stroke="#c9d2e3" strokeWidth={1} strokeDasharray="3 3"
                    transform={`translate(${xAt(hover)},0)`} />
              {geom.map(g => (
                <circle key={g.key} cx={xAt(hover)} cy={yAt(g.values[hover])} r={5}
                        fill="#fff" stroke={g.color} strokeWidth={2.6} />
              ))}
            </g>
          )}

          {/* hit area */}
          <rect x={left} y={top} width={plotW} height={plotH} fill="transparent"
                onMouseMove={handleMove} onMouseLeave={() => setHover(-1)}
                onTouchStart={handleMove} onTouchMove={handleMove}
                onTouchEnd={() => setHover(-1)} style={{ cursor: 'crosshair' }} />
        </svg>

        {hover >= 0 && (
          <div className="ac-tip"
               style={{
                 left: Math.min(Math.max(tipX, left + 4), left + plotW - 4),
                 transform: `translate(${flip ? '-100%' : '0'}, 0) translateX(${
                   flip ? -8 : 8}px)`,
                 top: top + 4,
               }}>
            <div className="ac-tip-title">{shortLabel(rows[hover]?.label)}</div>
            {series.map(s => (
              <div className="ac-tip-row" key={s.key}>
                <i style={{ background: s.color }} />
                <span>{s.name}</span>
                <b>{fmtNum(s.values[hover], compact)}</b>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
