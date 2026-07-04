/**
 * ReviewReflectCard -- harness rendering all five ReflectCard states with
 * realistic mock data. Access at ?harness=reflect-card.
 */

import { KoanToolCard } from './KoanToolCard'
import { ThinkingBlock } from './ThinkingBlock'
import { ToolCallRow } from './ToolCallRow'

function Divider({ label }: { label: string }) {
  return (
    <div style={{
      fontFamily: 'var(--font-mono)',
      fontSize: '12px',
      color: 'var(--text-muted)',
      textTransform: 'uppercase' as const,
      letterSpacing: '1px',
      padding: '40px 0 8px',
      borderBottom: '1px dashed var(--border-divider)',
      marginBottom: '16px',
    }}>
      {label}
    </div>
  )
}

const EMPTY_ARGS = {}

export function ReviewReflectCard() {
  return (
    <div style={{
      maxWidth: '820px',
      margin: '0 auto',
      padding: '40px 32px 80px',
      background: 'var(--bg-base)',
    }}>
      {/* Context: orchestrator thinking before triggering reflect */}
      <ThinkingBlock>
        The user is asking about how tool permissions work in the orchestrator phase.
        I need to check the memory system for any prior decisions about the permission
        fence and tool policy architecture. Let me reflect on what we know about the
        role-based tool vocabulary and phase gating.
      </ThinkingBlock>

      <div style={{ height: '12px' }} />

      <Divider label="STATE 1 -- JUST STARTED" />
      <KoanToolCard
        toolName="koan_reflect"
        args={EMPTY_ARGS}
        toolInput={{ question: 'How does the orchestrator tool permission model work, and what decisions have been made about phase gating?' }}
        result={{
          traces: [{ kind: 'thinking' }],
          iteration: 1,
          maxIterations: 10,
          model: 'claude-sonnet-4-6',
        }}
        inFlight={true}
      />

      <Divider label="STATE 2 -- ONE SEARCH DONE, THINKING" />
      <KoanToolCard
        toolName="koan_reflect"
        args={EMPTY_ARGS}
        toolInput={{ question: 'What is the current architecture for subagent spawning and how does the task manifest work?' }}
        result={{
          traces: [
            { kind: 'search', query: 'subagent spawn lifecycle task manifest', resultCount: 7, status: 'done' },
            { kind: 'thinking' },
          ],
          iteration: 2,
          maxIterations: 10,
          model: 'claude-sonnet-4-6',
        }}
        inFlight={true}
      />

      <Divider label="STATE 3 -- SEARCH IN PROGRESS" />
      <KoanToolCard
        toolName="koan_reflect"
        args={EMPTY_ARGS}
        toolInput={{ question: 'What conventions exist for the memory retrieval pipeline and how does RAG interact with the reflect tool?' }}
        result={{
          traces: [
            { kind: 'search', query: 'memory retrieval RAG pipeline', resultCount: 12, status: 'done' },
            { kind: 'search', query: 'reflect tool synthesis workflow', status: 'running' },
          ],
          iteration: 2,
          maxIterations: 10,
          model: 'claude-sonnet-4-6',
        }}
        inFlight={true}
      />

      <Divider label="STATE 4 -- MULTIPLE SEARCHES DONE, STREAMING ANSWER" />
      <KoanToolCard
        toolName="koan_reflect"
        args={EMPTY_ARGS}
        toolInput={{ question: 'How does the step-first workflow pattern control phase transitions and what invariants does it enforce?' }}
        result={{
          traces: [
            { kind: 'search', query: 'step-first workflow pattern', resultCount: 5, status: 'done' },
            { kind: 'search', query: 'phase transition validation', resultCount: 8, status: 'done' },
            { kind: 'search', query: 'koan_set_phase routing invariants', resultCount: 3, status: 'done' },
            { kind: 'search', query: 'turn outcome resolver completion gate', resultCount: 6, status: 'done' },
          ],
          answer: 'The step-first workflow pattern is the core control mechanism. The orchestrator loop (`run_agent_loop`) bootstraps by calling `_step_phase_handshake_core` to obtain step 1 guidance and injects it as the initial user turn. A **turn-outcome resolver** runs at each end-of-turn:\n\n- If the completion gate fails, the same step is re-injected\n- If more steps remain, the next step guidance is',
          iteration: 4,
          maxIterations: 10,
          model: 'claude-sonnet-4-6',
        }}
        inFlight={true}
      />

      <Divider label="STATE 5 -- DONE" />
      <KoanToolCard
        toolName="koan_reflect"
        args={EMPTY_ARGS}
        toolInput={{ question: 'How does the step-first workflow pattern control phase transitions and what invariants does it enforce?' }}
        result={{
          traces: [
            { kind: 'search', query: 'step-first workflow pattern', resultCount: 5, status: 'done' },
            { kind: 'search', query: 'phase transition validation', resultCount: 8, status: 'done' },
            { kind: 'search', query: 'koan_set_phase routing invariants', resultCount: 3, status: 'done' },
            { kind: 'search', query: 'turn outcome resolver completion gate', resultCount: 6, status: 'done' },
          ],
          answer: 'The step-first workflow pattern is the core control mechanism. The orchestrator loop (`run_agent_loop`) bootstraps by calling `_step_phase_handshake_core` to obtain step 1 guidance and injects it as the initial user turn. A **turn-outcome resolver** (`resolve_turn_outcome`) runs at each end-of-turn (terminal-text turn with no outstanding tool calls):\n\n- If the **completion gate fails**, the same step is re-injected\n- If **more steps remain**, the next step guidance is injected\n- If steps are **exhausted** and the agent is primary, it hands back to the user\n- If steps are **exhausted** and the agent is non-primary, it terminates\n\nAt the phase boundary, the primary agent calls `koan_suggest_next` to record suggestions, then ends its turn in terminal text. The user\'s reply resumes the loop. The agent then calls `koan_set_phase` to commit the transition.\n\n`is_valid_transition(workflow, from_phase, to_phase)` validates that `to_phase` is in the active workflow\'s `available_phases` and is not equal to `from_phase`. Any phase is reachable from any other -- there is no DAG of required successors.',
          citations: [
            { id: 42, title: 'Step-first workflow mechanics', type: 'procedure' },
            { id: 18, title: 'Phase gate not worth mechanical enforcement', type: 'decision' },
            { id: 87, title: 'Turn-outcome resolver design', type: 'lesson' },
            { id: 5, title: 'Orchestrator loop bootstrap sequence', type: 'context' },
            { id: 63, title: 'koan_set_phase routing contract', type: 'procedure' },
          ],
          iterations: 4,
          maxIterations: 10,
          model: 'claude-sonnet-4-6',
        }}
        inFlight={false}
      />

      <div style={{ height: '12px' }} />

      {/* Context: orchestrator reading a file after reflection */}
      <ToolCallRow
        tool="Read"
        command="koan/tools/tool_policy.py"
        status="done"
        metric="4.2 KB"
      />
    </div>
  )
}

export default ReviewReflectCard
