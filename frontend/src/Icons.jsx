import React from 'react'

/* Clean 20x20 stroke icons — consistent weight, no fills, no emoji.
   Kept as plain inline SVG (zero deps) so the sidebar looks like a real
   product's icon set instead of mismatched emoji glyphs. */
const base = { width: 19, height: 19, viewBox: '0 0 24 24', fill: 'none',
               stroke: 'currentColor', strokeWidth: 1.8,
               strokeLinecap: 'round', strokeLinejoin: 'round' }

export const IconChevronDown = (p) => (
  <svg {...base} {...p}><path d="M6 9l6 6 6-6" /></svg>
)
export const IconPlus = (p) => (
  <svg {...base} {...p}><path d="M12 5v14M5 12h14" /></svg>
)
export const IconPause = (p) => (
  <svg {...base} {...p}><rect x="6" y="4" width="4" height="16" rx="1" /><rect x="14" y="4" width="4" height="16" rx="1" /></svg>
)
export const IconFilter = (p) => (
  <svg {...base} {...p}><path d="M4 6h16M7 12h10M10 18h4" /></svg>
)


               export const IconArchive = (p) => (
  <svg {...base} {...p}><rect x="2" y="3" width="20" height="5" rx="1.5" /><path d="M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8" /><path d="M9 13h6" /></svg>
)

export const IconSend = (p) => (
  <svg {...base} {...p}><path d="M22 2L11 13" /><path d="M22 2L15 22l-4-9-9-4 20-7z" /></svg>
)
export const IconInbox = (p) => (
  <svg {...base} {...p}><path d="M4 4h16a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z" /><path d="M2 13h5l2 3h6l2-3h5" /></svg>
)
export const IconTrendUp = (p) => (
  <svg {...base} {...p}><path d="M3 17l5-5 4 4 9-9" /><path d="M14 7h7v7" /></svg>
)
export const IconRefresh = (p) => (
  <svg {...base} {...p}><path d="M4 12a8 8 0 0 1 14.9-4H16" /><path d="M20 12a8 8 0 0 1-14.9 4H8" /><path d="M19 5l1 3-3 1M5 19l-1-3 3-1" /></svg>
)

export const IconGrid = (p) => (
  <svg {...base} {...p}><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" /><rect x="3" y="14" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" /></svg>
)
export const IconMail = (p) => (
  <svg {...base} {...p}><rect x="3" y="5" width="18" height="14" rx="2" /><path d="M3 7l9 6 9-6" /></svg>
)
export const IconBot = (p) => (
  <svg {...base} {...p}><rect x="4" y="8" width="16" height="11" rx="3" /><path d="M12 8V4M9 4h6" /><circle cx="9" cy="13.5" r="1.3" fill="currentColor" stroke="none" /><circle cx="15" cy="13.5" r="1.3" fill="currentColor" stroke="none" /><path d="M8 19v1.5M16 19v1.5" /></svg>
)
export const IconRocket = (p) => (
  <svg {...base} {...p}><path d="M13.5 3c3 0 6 2 7.5 6-3.8.3-6 1.6-8 3.6-2 2-3.3 4.5-3.6 8-4-1.5-6-4.5-6-7.5 4-1.5 7-4.5 10.1-10.1z" /><circle cx="15" cy="9" r="1.6" /><path d="M6 15c-1.5 1-2 3-1.7 5.7C7 21 9 20.5 10 19" /></svg>
)
export const IconMic = (p) => (
  <svg {...base} {...p}><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3M9 21h6" /></svg>
)
export const IconUsers = (p) => (
  <svg {...base} {...p}><circle cx="9" cy="8" r="3.2" /><path d="M2.5 20c.6-3.6 3.2-6 6.5-6s5.9 2.4 6.5 6" /><circle cx="17.5" cy="8.5" r="2.6" /><path d="M15.5 14.2c2.4.3 4.3 2.3 4.8 5.3" /></svg>
)
export const IconBook = (p) => (
  <svg {...base} {...p}><path d="M4 5.5C4 4.7 4.7 4 5.5 4H12v16H5.5A1.5 1.5 0 0 1 4 18.5v-13z" /><path d="M20 5.5c0-.8-.7-1.5-1.5-1.5H12v16h6.5c.8 0 1.5-.7 1.5-1.5v-13z" /></svg>
)
export const IconTrash = (p) => (
  <svg {...base} {...p}><path d="M4 7h16" /><path d="M9 7V4.5A1.5 1.5 0 0 1 10.5 3h3A1.5 1.5 0 0 1 15 4.5V7" /><path d="M6 7l1 13.5A1.5 1.5 0 0 0 8.5 22h7a1.5 1.5 0 0 0 1.5-1.5L18 7" /><path d="M10 11v6M14 11v6" /></svg>
)
export const IconGear = (p) => (
  <svg {...base} {...p}><circle cx="12" cy="12" r="3.2" /><path d="M19.4 13.5a7.5 7.5 0 0 0 0-3l1.9-1.3-2-3.4-2.2.8a7.6 7.6 0 0 0-2.6-1.5L14 2.5h-4l-.5 2.6a7.6 7.6 0 0 0-2.6 1.5l-2.2-.8-2 3.4L4.6 10.5a7.5 7.5 0 0 0 0 3l-1.9 1.3 2 3.4 2.2-.8c.75.66 1.63 1.17 2.6 1.5l.5 2.6h4l.5-2.6a7.6 7.6 0 0 0 2.6-1.5l2.2.8 2-3.4z" /></svg>
)
export const IconStar = (p) => (
  <svg {...base} {...p}><path d="M12 3.5l2.6 5.6 6 .7-4.4 4.2 1.1 6-5.3-3-5.3 3 1.1-6-4.4-4.2 6-.7z" /></svg>
)
export const IconChevronsLeft = (p) => (
  <svg {...base} {...p}><path d="M18 6l-5 6 5 6M11 6l-5 6 5 6" /></svg>
)
export const IconChevronsRight = (p) => (
  <svg {...base} {...p}><path d="M6 6l5 6-5 6M13 6l5 6-5 6" /></svg>
)
export const IconBell = (p) => (
  <svg {...base} {...p}><path d="M6 10a6 6 0 1 1 12 0c0 4 1.5 5.5 1.5 5.5H4.5S6 14 6 10z" /><path d="M9.5 19a2.5 2.5 0 0 0 5 0" /></svg>
)
export const IconSearch = (p) => (
  <svg {...base} {...p}><circle cx="11" cy="11" r="7" /><path d="M21 21l-4.3-4.3" /></svg>
)
export const IconLogout = (p) => (
  <svg {...base} {...p}><path d="M9 4H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h3" /><path d="M15 16l4-4-4-4" /><path d="M19 12H9" /></svg>
)
export const IconShield = (p) => (
  <svg {...base} {...p}><path d="M12 3l7 3v6c0 4.5-3 7.5-7 9-4-1.5-7-4.5-7-9V6l7-3z" /><path d="M9 12l2 2 4-4" /></svg>
)
