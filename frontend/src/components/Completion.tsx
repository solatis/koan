import { useStore } from '../store/index'

export function Completion() {
  const completion = useStore(s => s.run?.completion)
  const artifacts = useStore(s => s.run?.artifacts ?? {})

  if (!completion) return null

  const artifactList = Object.keys(artifacts)

  return (
    <div className="phase-content">
      <div className="phase-inner">
        {completion.success ? (
          <>
            <h2 className="phase-heading">Run Complete</h2>
            <p className="phase-status">
              {completion.summary || 'All phases completed successfully.'}
            </p>
            {artifactList.length > 0 && (
              <div className="summary-list">
                {artifactList.map(path => (
                  <div key={path} className="summary-item">
                    <span className="icon-done">[OK]</span>
                    <span>{path}</span>
                  </div>
                ))}
              </div>
            )}
          </>
        ) : (
          <>
            <h2 className="phase-heading" style={{ color: 'var(--status-failed)' }}>
              Run Failed
            </h2>
            <p className="phase-status">{completion.error || 'An error occurred.'}</p>
          </>
        )}
      </div>
    </div>
  )
}
