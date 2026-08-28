import React, { useEffect, useRef, useState } from 'react'

/** Animates from the previous value to the new one whenever `value` changes —
 * used on stat cards so numbers visibly count up instead of jumping. */
export default function Counter({ value, format, duration = 650 }) {
  const [display, setDisplay] = useState(value ?? 0)
  const prev = useRef(value ?? 0)
  const raf = useRef(null)

  useEffect(() => {
    const from = prev.current
    const to = typeof value === 'number' ? value : 0
    if (from === to) { setDisplay(to); return }
    const start = performance.now()
    cancelAnimationFrame(raf.current)
    const tick = (now) => {
      const p = Math.min(1, (now - start) / duration)
      const eased = 1 - Math.pow(1 - p, 3)   // ease-out cubic
      setDisplay(from + (to - from) * eased)
      if (p < 1) raf.current = requestAnimationFrame(tick)
      else prev.current = to
    }
    raf.current = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf.current)
  }, [value, duration])

  const shown = typeof value === 'number' ? Math.round(display) : (value ?? '—')
  return <>{format ? format(shown) : shown.toLocaleString()}</>
}
