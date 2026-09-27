import React, { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api.js'
import Counter from './Counter.jsx'
import { IconRefresh } from './Icons.jsx'

/**
 * Live progress for a QUEUED background job (Excel/CSV import, mailbox
 * verify). The POST returns instantly with a job id; this polls the job and
 * renders the real phase + counters the server writes, so the user sees
 * "Importing leads 34 000 / 80 000…" instead of a spinner that may as well be
 * a 500.
 *
 * Works without a jobId too: `pick="running"` asks the API for whatever import
 * is in flight, which is what makes a page refresh mid-import pick up exactly
 * where it left off instead of pretending nothing happened.
 */
const POLL_MS = 800

export function useImportJob() {
  const [job, setJob] = useState(null)
  const [active, setActive] = useState(false)
  const pollRef = useRef(null)

  const stop = useCallback(() => {
    if (pollRef.current) { clearTimeout(pollRef.current); pollRef.current = null }
    setActive(false)
  }, [])

  const watch = useCallback((jobId) => {
    if (pollRef.current) clearTimeout(pollRef.current)
    setActive(true)
    let cancelled = false
    const tick = async () => {
      if (cancelled) return
      try {
        const j = await api.uploadJob(jobId)
        if (cancelled) return
        setJob(j)
        if (j.status === 'queued' || j.status === 'running') {
          pollRef.current = setTimeout(tick, POLL_MS)
        } else {
          pollRef.current = null
          setActive(false)
        }
      } catch {
        pollRef.current = setTimeout(tick, 2500)   // transient blip: keep trying
      }
    }
    tick()
    return () => { cancelled = true }
  }, [])

  const reset = useCallback(() => { setJob(null); stop() }, [stop])

  // Adopt an import that is already running (page refresh / other tab).
  const adoptRunning = useCallback(async () => {
    try {
      const r = await api.importJobs()
      const live = (r.items || []).find(j => j.status === 'queued' || j.status === 'running')
      if (live) { watch(live.id); return true }
    } catch { /* silent */ }
    return false
  }, [watch])

  useEffect(() => () => { if (pollRef.current) clearTimeout(pollRef.current) }, [])

  return { job, active, watch, stop, reset, adoptRunning }
}

export default function ImportProgress({ job, onDone, onDismiss, compact }) {
  // Hook first: an early `return null` before useState would break the hook
  // order between renders.
  const [cancelling, setCancelling] = useState(false)
  if (!job) return null
  const running = job.status === 'queued' || job.status === 'running'
  const failed = job.status === 'error'
  const pct = Math.max(0, Math.min(100, job.pct || 0))

  return (
    <div className="card mb" style={{ borderLeft: `3px solid ${failed ? '#b91c1c' : running ? '#0054FC' : '#16a34a'}` }}>
      <div className="row between" style={{ gap: 12, alignItems: 'flex-start' }}>
        <div style={{ minWidth: 0, flex: 1 }}>
          <b className="sm">
            {job.kind === 'verify' ? 'Mailbox verification' : `Importing ${job.filename || 'file'}`}
          </b>
          <div className="sm mut" style={{ marginTop: 2 }}>{job.phase}</div>
        </div>
        <div className="row" style={{ gap: 8, flex: 'none' }}>
          {running && <span className="spinner" />}
          <b className="sm" style={{ color: failed ? '#b91c1c' : 'var(--navy)' }}>
            {running ? `${pct}%` : failed ? 'Failed' : job.status === 'cancelled' ? 'Stopped' : 'Done'}
          </b>
        </div>
      </div>

      <div className="bar" style={{ marginTop: 10 }}>
        <i style={{
          width: `${running ? Math.max(pct, 2) : 100}%`,
          background: failed ? '#b91c1c' : running ? 'var(--blue)' : 'var(--ok)',
          transition: 'width .4s ease',
        }} />
      </div>

      {/* Live counters — the numbers the server actually wrote. */}
      <div className="row wrap sm mut" style={{ gap: 14, marginTop: 10 }}>
        {job.total > 0 && <span><b><Counter value={job.total} /></b> rows in file</span>}
        {running && job.processed > 0 && (
          <span><b><Counter value={job.processed} /></b> processed</span>
        )}
        {job.created > 0 && (
          <span style={{ color: 'var(--ok)' }}><b><Counter value={job.created} /></b> imported</span>
        )}
        {job.skipped_duplicates > 0 && (
          <span><b><Counter value={job.skipped_duplicates} /></b> duplicates skipped</span>
        )}
        {job.cross_duplicates > 0 && (
          <span><b><Counter value={job.cross_duplicates} /></b> also in the other queue</span>
        )}
        {job.blocked_addresses > 0 && (
          <span style={{ color: 'var(--warm)' }}>
            <b><Counter value={job.blocked_addresses} /></b> blocked (noreply@/info@/disposable)
          </span>
        )}
        {job.unverified > 0 && (
          <span style={{ color: 'var(--hot)' }}><b><Counter value={job.unverified} /></b> unverified</span>
        )}
      </div>

      {job.status === 'done' && job.result?.batch_count > 0 && (
        <div className="sm mut mt">
          {job.result.auto_enrolled > 0
            ? <>Split into <b>{job.result.batch_count}</b> batch bundle(s) of ~<b>{job.result.batch_size}</b> and{' '}
              <b>{job.result.auto_enrolled}</b> lead(s) queued for sending. Per-batch progress lives in Mail Records.</>
            : <>Split into <b>{job.result.batch_count}</b> batch bundle(s) of ~<b>{job.result.batch_size}</b>.
              Launch them from the Leads page whenever you're ready.</>}
        </div>
      )}

      {failed && job.error && (
        <div className="err mt" style={{ marginBottom: 0 }}>{job.error}</div>
      )}

      {job.status === 'cancelled' && (
        <div className="sm mut mt">
          Stopped. Everything imported before the stop is kept and duplicates are skipped
          if you re-upload the same file.
        </div>
      )}

      {!running && (
        <div className="row mt" style={{ gap: 8 }}>
          <button className="btn ghost small" onClick={() => { onDone?.(job); onDismiss?.() }}>
            <IconRefresh /> Refresh the list
          </button>
          <button className="btn small" onClick={() => onDismiss?.()}>Close</button>
        </div>
      )}

      {running && (
        <div className="row mt" style={{ gap: 8 }}>
          <button className="btn ghost small" disabled={cancelling}
                  onClick={async () => {
                    setCancelling(true)
                    try { await api.cancelImport(job.id) } catch { /* keep polling */ }
                    setCancelling(false)
                  }}>
            {cancelling ? 'Stopping…' : 'Stop after this chunk'}
          </button>
          <span className="sm mut">
            Everything already imported is kept — you can safely re-upload the file.
          </span>
        </div>
      )}
    </div>
  )
}
