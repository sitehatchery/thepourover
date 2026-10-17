import { useOpenProfile } from '../lib/useOpenProfile'

type Props = { email: string | null; profileId: string | null; fallback?: string }

/** An email (or id) that opens the subscriber activity dialog for its person. */
export default function EmailLink({ email, profileId, fallback = '' }: Props) {
  const open = useOpenProfile()
  const label = email ?? fallback
  if (!profileId) return <span className="cell-muted">{label}</span>
  return (
    <button type="button" className="link-btn cell-email" onClick={() => open(profileId)}>
      {label || profileId}
    </button>
  )
}
