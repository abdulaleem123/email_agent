import React, { useMemo } from 'react'
import {
  Chart as ChartJS, LineElement, PointElement, LinearScale, CategoryScale,
  Filler, Tooltip, Legend,
} from 'chart.js'
import { Line } from 'react-chartjs-2'

ChartJS.register(LineElement, PointElement, LinearScale, CategoryScale, Filler, Tooltip, Legend)

function toRgba(color, alpha) {
  // Chart.js draws on canvas — CSS custom properties (var(--blue)) don't
  // resolve there, so callers pass real hex/rgb colors. This adds fill alpha.
  if (color.startsWith('#')) {
    const c = color.replace('#', '')
    const bigint = parseInt(c.length === 3 ? c.split('').map(x => x + x).join('') : c, 16)
    const r = (bigint >> 16) & 255, g = (bigint >> 8) & 255, b = bigint & 255
    return `rgba(${r},${g},${b},${alpha})`
  }
  return color
}

/**
 * Animated Chart.js line/area chart — real-time-friendly (re-animates on
 * data change), flat translucent fills (no gradients), white theme, Fluent
 * tooltips. Pass real hex colors (e.g. '#0054FC'), not CSS vars — canvas
 * can't resolve custom properties.
 *
 * data: [{ label, ...values }]
 * seriesA / seriesB: { key, name, color }
 */
export default function AnimatedChart({ data = [], seriesA, seriesB, height = 220 }) {
  const chartData = useMemo(() => ({
    labels: data.map(d => d.label),
    datasets: [
      {
        label: seriesA.name,
        data: data.map(d => d[seriesA.key] ?? 0),
        borderColor: seriesA.color,
        backgroundColor: toRgba(seriesA.color, 0.12),
        pointBackgroundColor: seriesA.color,
        fill: true,
        tension: 0.35,
        pointRadius: 2.5,
        pointHoverRadius: 5,
        borderWidth: 2.4,
      },
      ...(seriesB ? [{
        label: seriesB.name,
        data: data.map(d => d[seriesB.key] ?? 0),
        borderColor: seriesB.color,
        backgroundColor: toRgba(seriesB.color, 0.10),
        pointBackgroundColor: seriesB.color,
        fill: true,
        tension: 0.35,
        pointRadius: 2.5,
        pointHoverRadius: 5,
        borderWidth: 2,
      }] : []),
    ],
  }), [data, seriesA, seriesB])

  const options = useMemo(() => ({
    responsive: true,
    maintainAspectRatio: false,
    animation: { duration: 700, easing: 'easeOutCubic' },
    interaction: { mode: 'index', intersect: false },
    plugins: {
      legend: {
        display: true, position: 'top', align: 'end',
        labels: { boxWidth: 8, boxHeight: 8, usePointStyle: true, pointStyle: 'circle',
                  font: { family: 'Inter', size: 11 }, color: '#6b7690' },
      },
      tooltip: {
        backgroundColor: '#ffffff', titleColor: '#001B58', bodyColor: '#0f1b33',
        borderColor: '#e7ebf3', borderWidth: 1, padding: 10, cornerRadius: 8,
        titleFont: { family: "'Segoe UI', system-ui, sans-serif", weight: '600', size: 12 },
        bodyFont: { family: "'Segoe UI', system-ui, sans-serif", size: 12 },
        boxPadding: 4,
      },
    },
    scales: {
      x: { grid: { display: false }, ticks: { color: '#6b7690', font: { size: 11 } } },
      y: { grid: { color: '#eef1f7' }, ticks: { color: '#6b7690', font: { size: 11 } }, beginAtZero: true },
    },
  }), [])

  // Show chart even when all values are zero — axes and labels still render,
  // giving meaningful context ("no emails sent yet") rather than a blank state.
  if (!data || data.length === 0) {
    return <div className="empty" style={{ height }}>No data yet for this period</div>
  }

  return (
    <div style={{ height }}>
      <Line data={chartData} options={options}
            // remount on data-length change so the animation genuinely replays
            key={data.length + '-' + (data[data.length - 1]?.label || '')} />
    </div>
  )
}