import React, { useEffect, useState } from 'react'
import { api } from '../api.js'
import { Toast, useToast } from '../App.jsx'

export default function Garbage() {
  const [data, setData] = useState({ items: [], total: 0, page: 1, pages: 1 })
  const [page, setPage] = useState(1)
  const [sel, setSel] = useState(new Set())
  const [toast, show] = useToast()
  const PER = 25

  const load = () => api.garbage(page, PER).then(d => { setData(d); setSel(new Set()) }).catch(e => show(e.message, true))
  useEffect(() => { load() }, [page])

  const toggleAll = () => setSel(s => s.size === data.items.length ? new Set() : new Set(data.items.map(m => m.id)))
  const toggleOne = (id) => setSel(s => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n })

  const bulkDelete = async () => {
    const r = await api.bulkDeleteGarbage([...sel])
    show(`Deleted ${r.deleted} items`); load()
  }
  const clearAll = async () => {
    if (!confirm(`Permanently delete all ${data.total} garbage items?`)) return
    const r = await api.clearGarbage()
    show(`Cleared ${r.deleted} items`); setPage(1); load()
  }

  const pagesArr = Array.from({ length: data.pages }, (_, i) => i + 1)
    .filter(p => p === 1 || p === data.pages || Math.abs(p - page) <= 2)

  return (
    <>
      <div className="row between mb">
        <span className="sm mut">{data.total} filtered items · auto-purged after retention period (see Settings)</span>
        <div className="row">
          <button className="btn danger small" disabled={!sel.size} onClick={bulkDelete}>Delete selected ({sel.size})</button>
          <button className="btn danger small" disabled={!data.total} onClick={clearAll}>Clear all</button>
        </div>
      </div>
      <div className="card" style={{ padding: 0, overflow: 'auto' }}>
        <table>
          <thead>
            <tr>
              <th><input type="checkbox" style={{ width: 16 }} checked={sel.size === data.items.length && data.items.length > 0} onChange={toggleAll} /></th>
              <th>From</th><th>Subject</th><th>Reason</th><th>When</th><th></th>
            </tr>
          </thead>
          <tbody>
            {data.items.map(m => (
              <tr key={m.id}>
                <td><input type="checkbox" style={{ width: 16 }} checked={sel.has(m.id)} onChange={() => toggleOne(m.id)} /></td>
                <td className="sm">{m.from_addr || '—'}</td>
                <td className="sm" style={{ maxWidth: 280, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{m.subject}</td>
                <td><span className="pill gray">{m.spam_reason || 'spam'}</span></td>
                <td className="sm mut">{new Date(m.created_at + 'Z').toLocaleString()}</td>
                <td><button className="btn danger small" onClick={async () => { await api.deleteGarbage(m.id); load() }}>✕</button></td>
              </tr>
            ))}
            {data.items.length === 0 && <tr><td colSpan={6}><div className="empty">Garbage is empty — spam and unverified emails land here</div></td></tr>}
          </tbody>
        </table>
      </div>
      {data.pages > 1 && (
        <div className="pagination">
          <button disabled={page === 1} onClick={() => setPage(p => p - 1)}>‹</button>
          {pagesArr.map((p, i) => (
            <React.Fragment key={p}>
              {i > 0 && pagesArr[i - 1] !== p - 1 && <span className="mut">…</span>}
              <button className={p === page ? 'on' : ''} onClick={() => setPage(p)}>{p}</button>
            </React.Fragment>
          ))}
          <button disabled={page === data.pages} onClick={() => setPage(p => p + 1)}>›</button>
        </div>
      )}
      <Toast toast={toast} />
    </>
  )
}