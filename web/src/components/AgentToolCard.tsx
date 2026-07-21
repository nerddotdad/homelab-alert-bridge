type Props = {
  name: string
  phase: string
  detail?: string
}

/** Compact tool progress card shown inline in the agent feed. */
export function AgentToolCard({ name, phase, detail }: Props) {
  const running = phase === 'started' || phase === 'running'
  return (
    <div className={`agent-tool ${running ? 'running' : 'done'}`}>
      <div className="agent-tool-head">
        <span className="agent-tool-name">{name || 'tool'}</span>
        <span className="agent-tool-phase">{running ? 'running' : 'done'}</span>
      </div>
      {detail ? <pre className="agent-tool-detail">{detail}</pre> : null}
    </div>
  )
}
