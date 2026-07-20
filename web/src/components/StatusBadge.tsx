export function StatusBadge({ status }: { status?: string }) {
  const s = (status || 'unknown').toLowerCase()
  return <span className={`badge status-${s}`}>{s}</span>
}

export function SeverityBadge({ severity }: { severity?: string }) {
  const s = (severity || 'unknown').toLowerCase()
  return <span className={`badge severity-${s}`}>{s}</span>
}
