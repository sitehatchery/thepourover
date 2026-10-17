import { useEffect, useState } from 'react'
import { apiGet } from '../api/client'
import type { Person } from '../api/types'

/** Shows "Person: email ×" when a table is filtered to one profile (e.g. from a Subscribers count link). */
export default function PersonFilterTag({ profileId, onRemove }: { profileId: string; onRemove: () => void }) {
  const [label, setLabel] = useState(profileId)

  useEffect(() => {
    apiGet<Person>(`/profiles/${encodeURIComponent(profileId)}`)
      .then((p) => setLabel(p.email ?? p.profile_id))
      .catch(() => setLabel(profileId))
  }, [profileId])

  return (
    <ul className="tags person-filter" aria-label="Filtered to one person">
      <li className="tag">
        Person: {label}
        <button type="button" className="tag-remove" aria-label="Show everyone" onClick={onRemove}>
          ×
        </button>
      </li>
    </ul>
  )
}
