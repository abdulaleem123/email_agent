import React from 'react'

export default function Graph({ data = [], seriesA, seriesB }) {
  if (!data.length) {
    return <div className="empty" style={{ height: 180, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>No email activity yet</div>
  }

  const maxVal = Math.max(1, ...data.map(d => Math.max(d[seriesA.key] || 0, d[seriesB.key] || 0)))

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div className="chartbars" style={{ display: 'flex', alignItems: 'flex-end', gap: 4, height: 180 }}>
        {data.map((d, i) => (
          <div
            key={d.date || i}
            className="col"
            title={`${d.date}: ${d[seriesA.key] || 0} ${seriesA.name} / ${d[seriesB.key] || 0} ${seriesB.name}`}
            style={{ flex: 1, display: 'flex', alignItems: 'flex-end', gap: 2, height: '100%' }}
          >
            <div
              style={{
                flex: 1,
                height: `${((d[seriesA.key] || 0) / maxVal) * 100}%`,
                background: seriesA.color,
                borderRadius: '3px 3px 0 0',
                minHeight: d[seriesA.key] ? 2 : 0,
                transition: 'height 0.4s ease',
              }}
            />
            <div
              style={{
                flex: 1,
                height: `${((d[seriesB.key] || 0) / maxVal) * 100}%`,
                background: seriesB.color,
                borderRadius: '3px 3px 0 0',
                minHeight: d[seriesB.key] ? 2 : 0,
                transition: 'height 0.4s ease',
              }}
            />
          </div>
        ))}
      </div>
      <div className="legend" style={{ display: 'flex', gap: 16, fontSize: 12 }}>
        <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
          <i style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 2, background: seriesA.color }} />
          {seriesA.name}
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
          <i style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 2, background: seriesB.color }} />
          {seriesB.name}
        </span>
      </div>
    </div>
  )
}