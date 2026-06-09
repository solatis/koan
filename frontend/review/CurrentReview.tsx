export default function CurrentReview() {
  return (
    <div style={{ padding: 24, fontFamily: 'var(--font-body)', color: 'var(--text-primary)' }}>
      <h2 style={{ fontSize: 'var(--type-section-title)', marginBottom: 12 }}>
        Design Review
      </h2>
      <p style={{ fontSize: 'var(--type-body)', color: 'var(--text-muted)' }}>
        No active review. Update this file during a design session.
      </p>
    </div>
  )
}
