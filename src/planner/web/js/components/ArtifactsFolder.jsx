// Artifact tree sidebar. Shows all generated artifacts grouped by epic root
// and stories. Clicking a file opens an overlay with rendered markdown content.
// Always mounted -- receives updates via SSE through the store and fetches
// initial listing on mount.

import { useState, useEffect, useRef } from 'preact/hooks'
import { marked } from 'marked'
import { useStore } from '../store.js'
import { fetchArtifacts, fetchArtifactContent } from '../lib/api.js'

// -- Helpers --

function relativeTime(iso) {
  const ms = Date.now() - new Date(iso).getTime()
  const s = Math.floor(ms / 1000)
  if (s < 60) return `${s}s ago`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  return `${Math.floor(h / 24)}d ago`
}

// -- FileEntry --

function FileEntry({ file, isNew, onOpen }) {
  const [hovered, setHovered] = useState(false)
  const cls = 'tree-file' + (hovered ? ' tree-hover' : '')

  return (
    <div
      class={cls}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onClick={() => onOpen(file.path)}
    >
      <span class="tree-file-name">
        {file.path.split('/').pop()}
        {isNew && <span class="tree-new-badge">new</span>}
      </span>
      <span class="tree-file-meta">
        {relativeTime(file.modifiedAt)} &middot; {file.formattedSize}
      </span>
    </div>
  )
}

// -- ArtifactsFolder --

export function ArtifactsFolder({ token }) {
  const artifactFiles = useStore(s => s.artifactFiles)
  const [collapsedFolders, setCollapsedFolders] = useState(new Set())
  const [openFile, setOpenFile] = useState(null)
  const [overlayContent, setOverlayContent] = useState(null)
  const [overlayLoading, setOverlayLoading] = useState(false)
  const [overlayError, setOverlayError] = useState(null)
  const [overlayDisplayPath, setOverlayDisplayPath] = useState(null)
  const [newPaths, setNewPaths] = useState(new Set())
  const prevFilesRef = useRef([])
  const badgeTimersRef = useRef(new Map())

  // Pre-populate on mount -- only if SSE has not already delivered fresher data
  useEffect(() => {
    fetchArtifacts(token)
      .then(d => {
        const current = useStore.getState().artifactFiles
        if (current.length === 0) useStore.setState({ artifactFiles: d.files })
      })
      .catch(err => console.error('fetchArtifacts:', err))
  }, [])

  // Clear all badge timers on unmount
  useEffect(() => {
    return () => {
      for (const id of badgeTimersRef.current.values()) clearTimeout(id)
      badgeTimersRef.current.clear()
    }
  }, [])

  // New-badge logic
  useEffect(() => {
    const prev = new Set(prevFilesRef.current.map(f => f.path))
    const added = artifactFiles.filter(f => !prev.has(f.path))
    if (added.length) {
      setNewPaths(s => {
        const next = new Set(s)
        added.forEach(f => next.add(f.path))
        return next
      })
      added.forEach(f => {
        const existing = badgeTimersRef.current.get(f.path)
        if (existing) clearTimeout(existing)
        const id = setTimeout(() => {
          badgeTimersRef.current.delete(f.path)
          setNewPaths(s => {
            const next = new Set(s)
            next.delete(f.path)
            return next
          })
        }, 4000)
        badgeTimersRef.current.set(f.path, id)
      })
    }
    prevFilesRef.current = artifactFiles
  }, [artifactFiles])

  // Overlay content fetch -- cancel stale requests when openFile changes
  useEffect(() => {
    if (!openFile) return
    let cancelled = false
    setOverlayLoading(true)
    setOverlayContent(null)
    setOverlayError(null)
    setOverlayDisplayPath(null)
    fetchArtifactContent(token, openFile)
      .then(d => {
        if (cancelled) return
        setOverlayContent(d.content)
        setOverlayDisplayPath(d.displayPath ?? null)
      })
      .catch(err => {
        if (cancelled) return
        if (err.status === 404) setOverlayError({ notFound: true })
        else setOverlayError({ message: err.message })
      })
      .finally(() => { if (!cancelled) setOverlayLoading(false) })
    return () => { cancelled = true }
  }, [openFile])

  // Escape key
  useEffect(() => {
    if (!openFile) return
    const handler = e => { if (e.key === 'Escape') setOpenFile(null) }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [openFile])

  // Tree structure
  const epicRootFiles = artifactFiles.filter(f => !f.path.includes('/'))
  const storiesMap = new Map()
  artifactFiles.forEach(f => {
    if (!f.path.startsWith('stories/')) return
    const id = f.path.split('/')[1]
    if (!storiesMap.has(id)) storiesMap.set(id, [])
    storiesMap.get(id).push(f)
  })

  function toggleFolder(p) {
    setCollapsedFolders(s => {
      const next = new Set(s)
      next.has(p) ? next.delete(p) : next.add(p)
      return next
    })
  }

  const filename = openFile ? openFile.split('/').pop() : ''

  return (
    <div class="artifacts-sidebar">
      <div class="sidebar-heading">Artifacts</div>

      {/* Epic root */}
      <div class="tree-folder">
        <div class="tree-folder-label" onClick={() => toggleFolder('epic-root')}>
          {collapsedFolders.has('epic-root') ? '\u25B8' : '\u25BE'} epic root
        </div>
        {!collapsedFolders.has('epic-root') && (
          <div class="tree-children">
            {epicRootFiles.map(f => (
              <FileEntry key={f.path} file={f} isNew={newPaths.has(f.path)} onOpen={setOpenFile} />
            ))}
          </div>
        )}
      </div>

      {/* Stories */}
      <div class="tree-folder">
        <div class="tree-folder-label" onClick={() => toggleFolder('stories')}>
          {collapsedFolders.has('stories') ? '\u25B8' : '\u25BE'} stories/
        </div>
        {!collapsedFolders.has('stories') && (
          <div class="tree-children">
            {[...storiesMap.entries()].map(([id, files]) => (
              <div class="tree-folder" key={id}>
                <div class="tree-folder-label" onClick={() => toggleFolder(`stories/${id}`)}>
                  {collapsedFolders.has(`stories/${id}`) ? '\u25B8' : '\u25BE'} {id}/
                </div>
                {!collapsedFolders.has(`stories/${id}`) && (
                  <div class="tree-children">
                    {files.map(f => (
                      <FileEntry key={f.path} file={f} isNew={newPaths.has(f.path)} onOpen={setOpenFile} />
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Overlay */}
      {openFile && (
        <div class="artifact-overlay" onClick={() => setOpenFile(null)}>
          <div class="artifact-overlay-panel" onClick={e => e.stopPropagation()}>
            <div class="artifact-overlay-header">
              <div>
                <div class="artifact-overlay-title">
                  {filename}
                  <span class="artifact-overlay-readonly-badge">read-only</span>
                </div>
                <div class="artifact-overlay-path">
                  {(() => {
                    const entry = artifactFiles.find(f => f.path === openFile)
                    const label = overlayDisplayPath ?? openFile
                    if (!entry) return label
                    return `${label} \u00b7 ${entry.formattedSize} \u00b7 ${relativeTime(entry.modifiedAt)}`
                  })()}
                </div>
              </div>
              <button onClick={() => setOpenFile(null)}>&times;</button>
            </div>
            <div class="artifact-overlay-body">
              {overlayLoading && <span>Loading...</span>}
              {overlayError?.notFound && <span>File not found.</span>}
              {overlayError && !overlayError.notFound && <span>Error: {overlayError.message}</span>}
              {overlayContent && (
                <div dangerouslySetInnerHTML={{ __html: marked.parse(overlayContent) }} />
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
