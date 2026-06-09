import '../src/styles/variables.css'
import { createRoot } from 'react-dom/client'

const direction = new URLSearchParams(window.location.search).get('d')

async function main() {
  const mod = direction
    ? await import(`./directions/${direction}.tsx`)
    : await import('./CurrentReview.tsx')

  const Page = mod.default

  createRoot(document.getElementById('review-root')!).render(
    <div style={{ background: 'var(--bg-base)', minHeight: '100vh' }}>
      <Page />
    </div>
  )
}

main()
