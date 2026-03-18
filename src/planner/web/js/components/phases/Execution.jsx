import { useStore } from '../../store.js'

export function Execution({ phase }) {
  const stories = useStore(s => s.stories)

  const phaseLabel = phase === 'decomposition' ? 'Decomposing into stories...'
                   : phase === 'review'         ? 'Awaiting spec review...'
                   : phase === 'executing'      ? 'Executing stories...'
                   : `Phase: ${phase}`

  return (
    <div class="phase-inner">
      <p class="phase-status">{phaseLabel}</p>
      {stories.length > 0 && (
        <div class="summary-list">
          {stories.map(story => {
            const icon = story.status === 'done'    ? '✓'
                       : story.status === 'skipped' ? '—'
                       : (story.status === 'executing' || story.status === 'planning' || story.status === 'verifying') ? '●'
                       : '◌'
            const iconCls = story.status === 'done' ? 'icon-done' : 'icon-pending'
            return (
              <div key={story.storyId} class="summary-item">
                <span class={iconCls}>{icon}</span>
                <span>{story.storyId}</span>
                <span class="review-story-title"> [{story.status}]</span>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
