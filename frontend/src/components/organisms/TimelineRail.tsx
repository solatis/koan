/**
 * TimelineRail — the full left sidebar showing the phase timeline.
 *
 * Composes the timeline molecules + MilestoneNumber atom into a navy rail:
 * top-level phases with handoff badges between them, an optional milestones
 * section (or a three-dot placeholder when milestones are not yet defined),
 * and any post-milestone phases (e.g. Curation).
 *
 * Milestone insertion point: the milestones section is placed after the last
 * phase that produced a handoff artifact (the planning artifact the milestones
 * build from). Phases after that point — typically the terminal Curation phase
 * — render below the milestones section. isFirst/isLast track the true first
 * and last top-level phase nodes across the whole rail.
 *
 * Meta strings are derived here: elapsed for done phases, "step N/M · Step"
 * for active phases, "skipped" for skipped phases.
 *
 * Used in: workspace layout, left column.
 */

import { Fragment } from 'react'
import type { ReactNode } from 'react'
import { MilestoneNumber } from '../atoms/MilestoneNumber'
import { TimelinePhaseNode } from '../molecules/TimelinePhaseNode'
import { TimelineHandoff } from '../molecules/TimelineHandoff'
import { TimelineSubPhaseNode } from '../molecules/TimelineSubPhaseNode'
import { TimelineSubArtifact } from '../molecules/TimelineSubArtifact'
import { TimelinePlaceholder } from '../molecules/TimelinePlaceholder'
import './TimelineRail.css'

export interface PhaseNodeData {
  id: string
  name: string
  status: 'done' | 'active' | 'future' | 'skipped'
  elapsed?: string
  currentStep?: number
  totalSteps?: number
  stepName?: string
  producedArtifacts?: string[]
}

export interface MilestoneGroupData {
  number: number
  title: string
  status: 'done' | 'active' | 'future'
  subPhases: {
    name: string
    status: 'done' | 'active' | 'future'
    producedArtifact?: string
  }[]
}

interface TimelineRailProps {
  phases: PhaseNodeData[]
  milestones?: MilestoneGroupData[] | null
  showMilestonePlaceholder?: boolean
  activePhaseId: string
  viewingPhaseId?: string | null
  onPhaseClick?: (phaseId: string) => void
}

/** Meta line for a phase node, or undefined when the node shows none. */
function deriveMeta(phase: PhaseNodeData): string | undefined {
  if (phase.status === 'done') return phase.elapsed
  if (phase.status === 'skipped') return 'skipped'
  if (phase.status === 'active' && phase.currentStep != null && phase.totalSteps != null) {
    const step = `step ${phase.currentStep}/${phase.totalSteps}`
    return phase.stepName ? `${step} · ${phase.stepName}` : step
  }
  return undefined
}

/** Index of the last phase that produced a handoff artifact, or -1. */
function lastArtifactIndex(phases: PhaseNodeData[]): number {
  for (let i = phases.length - 1; i >= 0; i--) {
    if ((phases[i].producedArtifacts?.length ?? 0) > 0) return i
  }
  return -1
}

export function TimelineRail({
  phases,
  milestones,
  showMilestonePlaceholder,
  viewingPhaseId,
  onPhaseClick,
}: TimelineRailProps) {
  const showMilestones = !!(milestones && milestones.length > 0)
  const showPlaceholder = !showMilestones && !!showMilestonePlaceholder
  const hasSection = showMilestones || showPlaceholder

  const insertIndex = hasSection
    ? lastArtifactIndex(phases) + 1 || phases.length
    : phases.length
  const prePhases = phases.slice(0, insertIndex)
  const postPhases = phases.slice(insertIndex)

  const firstId = phases.length > 0 ? phases[0].id : null
  const lastId = phases.length > 0 ? phases[phases.length - 1].id : null

  const renderPhase = (phase: PhaseNodeData): ReactNode[] => {
    const out: ReactNode[] = [
      <TimelinePhaseNode
        key={phase.id}
        name={phase.name}
        status={phase.status}
        meta={deriveMeta(phase)}
        viewing={viewingPhaseId === phase.id}
        isFirst={phase.id === firstId}
        isLast={phase.id === lastId}
        onClick={onPhaseClick ? () => onPhaseClick(phase.id) : undefined}
      />,
    ]
    // A phase's handoffs render unless it is the terminal node of the rail.
    if (phase.producedArtifacts && phase.id !== lastId) {
      phase.producedArtifacts.forEach((name, k) =>
        out.push(<TimelineHandoff key={`${phase.id}-handoff-${k}`} name={name} />),
      )
    }
    return out
  }

  const renderMilestone = (ms: MilestoneGroupData): ReactNode => (
    <div className="tlr__ms-group" key={`ms-${ms.number}`}>
      <div className="tlr__ms-header">
        <MilestoneNumber number={ms.number} status={ms.status} />
        <span className={`tlr__ms-title tlr__ms-title--${ms.status}`}>{ms.title}</span>
      </div>
      {ms.status !== 'future' && ms.subPhases.length > 0 && (
        <div className="tlr__sub-phases">
          {ms.subPhases.map((sp, i) => (
            <Fragment key={`ms-${ms.number}-sub-${i}`}>
              <TimelineSubPhaseNode name={sp.name} status={sp.status} />
              {sp.producedArtifact && <TimelineSubArtifact name={sp.producedArtifact} />}
            </Fragment>
          ))}
        </div>
      )}
    </div>
  )

  return (
    <div className={`tlr${showMilestones ? ' tlr--milestones' : ''}`}>
      {prePhases.flatMap(renderPhase)}

      {showMilestones && (
        <>
          <div className="tlr__separator" />
          <div className="tlr__section-label">milestones</div>
          {milestones!.map(renderMilestone)}
        </>
      )}
      {showPlaceholder && <TimelinePlaceholder label="milestones" />}

      {postPhases.flatMap(renderPhase)}
    </div>
  )
}

export default TimelineRail
