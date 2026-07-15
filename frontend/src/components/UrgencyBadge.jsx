export default function UrgencyBadge({ level }) {
  const label = level || 'Unknown'
  return <span className={`urgency-badge urgency-${label}`}>{label}</span>
}
