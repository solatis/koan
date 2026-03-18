import { render } from 'preact'
import { App } from './components/App.jsx'
import { connectSSE } from './sse.js'

const data = window.__DATA__
const token = data?.token || new URLSearchParams(location.search).get('session') || ''

render(<App token={token} topic={data?.topic} />, document.getElementById('app'))
connectSSE(token)

setInterval(() => {
  fetch('/api/heartbeat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token }),
  }).catch(() => {})
}, 5000)
