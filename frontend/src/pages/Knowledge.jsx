import React, { useEffect, useRef, useState } from 'react'
import { api } from '../api.js'
import { Toast, useToast } from '../App.jsx'

export default function Knowledge() {
  const [agents, setAgents] = useState([])
  const [agentId, setAgentId] = useState(null)      // selected agent's KB
  const [docs, setDocs] = useState([])
  const [templates, setTemplates] = useState([])
  const [doc, setDoc] = useState({ title: '', content: '' })
  const [tpl, setTpl] = useState({ name: '', length: 'medium', body: '' })
  const [toast, show] = useToast()

  useEffect(() => {
    api.agents().then(ags => { setAgents(ags); if (ags[0]) setAgentId(ags[0].id) })
  }, [])

  const load = () => {
    if (agentId == null) return
    api.knowledge(agentId).then(setDocs).catch(() => {})
    api.templates(agentId).then(setTemplates).catch(() => {})
  }
  useEffect(() => { load() }, [agentId])

  const fileRef = useRef()
  const uploadFile = async (e) => {
    const file = e.target.files[0]
    if (!file) return
    try {
      await api.uploadDoc(file, agentId, file.name)
      load(); show(`Imported ${file.name} into ${current?.name || 'KB'}`)
    } catch (ex) { show(ex.message, true) } finally { e.target.value = '' }
  }

  const addDoc = async () => {
    if (!doc.title.trim() || !doc.content.trim()) return
    await api.addDoc({ ...doc, agent_id: agentId })
    setDoc({ title: '', content: '' }); load(); show('Added to knowledge base')
  }
  const addTpl = async () => {
    if (!tpl.name.trim() || !tpl.body.trim()) return
    await api.addTemplate({ ...tpl, agent_id: agentId })
    setTpl({ name: '', length: 'medium', body: '' }); load(); show('Template saved')
  }

  const current = agents.find(a => a.id === agentId)

  return (
    <>
      <div className="agent-tabs">
        {agents.map(a => (
          <button key={a.id} className={agentId === a.id ? 'on' : ''} onClick={() => setAgentId(a.id)}>
            {a.name}
          </button>
        ))}
      </div>
      <p className="sm mut mb">
        {current ? `${current.name}'s private knowledge base — only ${current.name} uses these documents. ` : ''}
        Shared docs (marked "shared") are visible to every agent.
      </p>

      <div className="grid c2">
        <div>
          <div className="card mb">
            <h3 style={{ fontSize: 15, marginBottom: 10 }}>Add knowledge for {current?.name || '…'}</h3>
            <div className="field"><input placeholder="Title" value={doc.title} onChange={e => setDoc(d => ({ ...d, title: e.target.value }))} /></div>
            <div className="field"><textarea rows={4} placeholder="Content the agent should know and answer from…" value={doc.content} onChange={e => setDoc(d => ({ ...d, content: e.target.value }))} /></div>
            <div className="row">
              <button className="btn" onClick={addDoc}>Add document</button>
              <input ref={fileRef} type="file" accept=".txt,.md,.pdf,.docx" onChange={uploadFile} style={{ display: 'none' }} />
              <button className="btn ghost" onClick={() => fileRef.current.click()}>⬆ Upload PDF / DOCX / TXT</button>
            </div>
            <p className="sm mut" style={{ marginTop: 6 }}>Text is extracted and embedded (no OCR — scanned PDFs won't work).</p>
          </div>
          {docs.map(d => (
            <div key={d.id} className="card mb">
              <div className="row between">
                <b>{d.title} {d.agent_id == null && <span className="pill gray">shared</span>}</b>
                <button className="btn danger small" onClick={async () => { await api.deleteDoc(d.id); load() }}>Delete</button>
              </div>
              <p className="sm mut mt">{d.content.slice(0, 320)}{d.content.length > 320 ? '…' : ''}</p>
            </div>
          ))}
        </div>
        <div>
          <div className="card mb">
            <h3 style={{ fontSize: 15, marginBottom: 10 }}>Seed template for {current?.name || '…'}</h3>
            <p className="sm mut mb">Templates are structure inspiration only — the agent rewrites them fully and never repeats one for the same lead.</p>
            <div className="field"><input placeholder="Template name" value={tpl.name} onChange={e => setTpl(t => ({ ...t, name: e.target.value }))} /></div>
            <div className="field">
              <select value={tpl.length} onChange={e => setTpl(t => ({ ...t, length: e.target.value }))}>
                {['short', 'medium', 'long'].map(l => <option key={l}>{l}</option>)}
              </select>
            </div>
            <div className="field"><textarea rows={4} placeholder="Hi {first_name}, …" value={tpl.body} onChange={e => setTpl(t => ({ ...t, body: e.target.value }))} /></div>
            <button className="btn" onClick={addTpl}>Save template</button>
          </div>
          {templates.map(t => (
            <div key={t.id} className="card mb">
              <div className="row between">
                <b>{t.name} <span className="pill gray">{t.length}</span> {t.agent_id == null && <span className="pill gray">shared</span>}</b>
                <button className="btn danger small" onClick={async () => { await api.deleteTemplate(t.id); load() }}>Delete</button>
              </div>
              <p className="sm mut mt">{t.body.slice(0, 260)}{t.body.length > 260 ? '…' : ''}</p>
            </div>
          ))}
        </div>
      </div>
      <Toast toast={toast} />
    </>
  )
}