import React from 'react'

/**
 * Without this, ANY unhandled error inside a page component (a bad API
 * response shape, a missing field, etc.) unmounts the ENTIRE React tree and
 * the app goes blank — which looked like "clicking a sidebar item makes
 * everything disappear". This catches it, shows what broke, and lets you
 * recover without reloading or losing your session.
 */
export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    // eslint-disable-next-line no-console
    console.error('Chatversio CRM crash:', error, info?.componentStack)
  }

  componentDidUpdate(prevProps) {
    // auto-recover when the parent switches page (resetKey changes)
    if (this.state.error && prevProps.resetKey !== this.props.resetKey) {
      this.setState({ error: null })
    }
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <div className="card" style={{ margin: '20px 0', borderColor: '#fecaca' }}>
        <b style={{ color: '#b91c1c' }}>This section hit an error and couldn't render.</b>
        <p className="sm mut mt">
          {String(this.state.error?.message || this.state.error)}
        </p>
        <div className="row mt">
          <button className="btn" onClick={() => this.setState({ error: null })}>Try again</button>
          <button className="btn ghost" onClick={() => this.props.onGoHome?.()}>Go to Dashboard</button>
        </div>
        <p className="sm mut mt">
          Open the browser console (F12) for the full error — that tells you exactly
          which request or field caused it.
        </p>
      </div>
    )
  }
}
