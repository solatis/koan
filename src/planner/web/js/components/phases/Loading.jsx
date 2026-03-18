export function Loading({ topic }) {
  return (
    <div class="phase-inner" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', paddingTop: '80px' }}>
      <div class="spinner" />
      <p class="phase-status" style={{ marginTop: '16px' }}>Initializing...</p>
      {topic && (
        <div class="topic-card">
          <div class="topic-label">YOUR REQUEST</div>
          <div class="topic-text">{topic}</div>
        </div>
      )}
    </div>
  )
}
