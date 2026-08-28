// import React, { useState } from 'react'
// import { api, setToken } from '../api.js'
// import { Brand } from '../App.jsx'
// import ThreeBackdrop from './ThreeBackdrop.jsx'

// const AGENTS = [
//   ['Osaja', 'Senior Sales Strategist'],
//   ['Saif', 'Co-Founder, Chatversio AI'],
//   ['Aleem', 'AI Engineer'],
//   ['Dawood', 'Frontend & Full-Stack Developer'],
// ]

// export default function Login({ onAuthed }) {
//   const [step, setStep] = useState('creds')       // creds | otp
//   const [email, setEmail] = useState('')
//   const [password, setPassword] = useState('')
//   const [code, setCode] = useState('')
//   const [err, setErr] = useState('')
//   const [busy, setBusy] = useState(false)

//   const submit = async (e) => {
//     e.preventDefault()
//     setErr(''); setBusy(true)
//     try {
//       if (step === 'creds') {
//         const r = await api.login(email.trim(), password)
//         if (r.otp_required) setStep('otp')
//         else { setToken(r.token); onAuthed() }
//       } else {
//         const r = await api.verifyOtp(email.trim(), code.trim())
//         setToken(r.token); onAuthed()
//       }
//     } catch (ex) { setErr(ex.message) } finally { setBusy(false) }
//   }

//   return (
//     <div className="login-wrap">
//       <div className="login-left">
//         <Brand />
//         <h1>{step === 'creds' ? 'Welcome back' : 'Check your email'}</h1>
//         <p className="login-sub">
//           {step === 'creds'
//             ? 'Sign in to manage your AI email agents'
//             : `We sent a 6-digit verification code to ${email}`}
//         </p>
//         {err && <div className="err">{err}</div>}
//         <form onSubmit={submit} style={{ maxWidth: 420 }}>
//           {step === 'creds' ? (
//             <>
//               <div className="field">
//                 <label>Email</label>
//                 <input type="email" value={email} onChange={e => setEmail(e.target.value)}
//                        placeholder="you@example.com" required autoFocus />
//               </div>
//               <div className="field">
//                 <label>Password</label>
//                 <input type="password" value={password} onChange={e => setPassword(e.target.value)}
//                        placeholder="••••••••" required />
//               </div>
//             </>
//           ) : (
//             <div className="field">
//               <label>Verification code</label>
//               <input value={code} onChange={e => setCode(e.target.value)} placeholder="123456"
//                      inputMode="numeric" maxLength={6} required autoFocus
//                      style={{ letterSpacing: '.4em', fontSize: 18, textAlign: 'center' }} />
//             </div>
//           )}
//           <button className="btn full" disabled={busy}>
//             {busy ? 'Please wait…' : step === 'creds' ? 'Sign in →' : 'Verify & continue'}
//           </button>
//         </form>
//         {step === 'otp' && (
//           <button className="hint" style={{ color: 'var(--blue)', textAlign: 'left' }}
//                   onClick={() => { setStep('creds'); setCode(''); setErr('') }}>← Back to sign in</button>
//         )}
//         <p className="hint">Access is invite-only. Contact your administrator for an account.</p>
//       </div>
//       <div className="login-right">
//         <ThreeBackdrop />
//         <div className="eyebrow">POWERED BY CHATVERSIO AI</div>
//         <h2>Your AI agents.<br />Always on.<br />Always ready.</h2>
//         <p>Four specialist agents research every lead, write emails that sound human,
//            reply from their own knowledge base, and book meetings — while you watch it live.</p>
//         <div className="agent-strip">
//           {AGENTS.map(([name, role]) => (
//             <div key={name} className="agent-chip">
//               <div><b>{name}</b><small>{role}</small></div>
//               <span className="dot-online">online</span>
//             </div>
//           ))}
//         </div>
//       </div>
//     </div>
//   )
// }


import React, { useState } from 'react'
import { api, setToken } from '../api.js'
import { Brand } from '../App.jsx'
import ThreeBackdrop from './ThreeBackdrop.jsx'

const AGENTS = [
  ['Osaja', 'Senior Sales Strategist', '/osaja.png'],
  ['Saif', 'Co-Founder, Chatversio AI', '/saif.png'],
  ['Aleem', 'AI Engineer', '/aleem.png'],
  ['Dawood', 'Frontend & Full-Stack Developer', '/dawood.png'],
]

export default function Login({ onAuthed }) {
  const [step, setStep] = useState('creds')       // creds | otp
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    setErr(''); setBusy(true)
    try {
      if (step === 'creds') {
        const r = await api.login(email.trim(), password)
        if (r.otp_required) setStep('otp')
        else { setToken(r.token); onAuthed() }
      } else {
        const r = await api.verifyOtp(email.trim(), code.trim())
        setToken(r.token); onAuthed()
      }
    } catch (ex) { setErr(ex.message) } finally { setBusy(false) }
  }

  return (
    <div className="login-wrap">
      <div className="login-left">
        <Brand />
        <h1>{step === 'creds' ? 'Welcome back' : 'Check your email'}</h1>
        <p className="login-sub">
          {step === 'creds'
            ? 'Sign in to manage your AI email agents'
            : `We sent a 6-digit verification code to ${email}`}
        </p>
        {err && <div className="err">{err}</div>}
        <form onSubmit={submit} style={{ maxWidth: 420 }}>
          {step === 'creds' ? (
            <>
              <div className="field">
                <label>Email</label>
                <input type="email" value={email} onChange={e => setEmail(e.target.value)}
                       placeholder="you@example.com" required autoFocus />
              </div>
              <div className="field">
                <label>Password</label>
                <input type="password" value={password} onChange={e => setPassword(e.target.value)}
                       placeholder="••••••••" required />
              </div>
            </>
          ) : (
            <div className="field">
              <label>Verification code</label>
              <input value={code} onChange={e => setCode(e.target.value)} placeholder="123456"
                     inputMode="numeric" maxLength={6} required autoFocus
                     style={{ letterSpacing: '.4em', fontSize: 18, textAlign: 'center' }} />
            </div>
          )}
          <button className="btn full" disabled={busy}>
            {busy ? 'Please wait…' : step === 'creds' ? 'Sign in →' : 'Verify & continue'}
          </button>
        </form>
        {step === 'otp' && (
          <button className="hint" style={{ color: 'var(--blue)', textAlign: 'left' }}
                  onClick={() => { setStep('creds'); setCode(''); setErr('') }}>← Back to sign in</button>
        )}
        <p className="hint">Access is invite-only. Contact your administrator for an account.</p>
      </div>
      <div className="login-right">
        <ThreeBackdrop />
        <div className="eyebrow">POWERED BY CHATVERSIO AI</div>
        <h2>Your AI agents.<br />Always on.<br />Always ready.</h2>
        <p>Four specialist agents research every lead, write emails that sound human,
           reply from their own knowledge base, and book meetings — while you watch it live.</p>
        <div className="agent-strip">
          {AGENTS.map(([name, role, photo], i) => (
            <div key={name} className="agent-chip" style={{ animationDelay: `${0.15 + i * 0.09}s` }}>
              <img src={photo} alt={name} className="agent-photo" />
              <div className="agent-info">
                <b>{name}</b>
                <small>{role}</small>
              </div>
              <span className="dot-online" title="online">●</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
