import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react'
import { apiGet } from '../api/client'
import type { Person } from '../api/types'
import { useOpenProfile } from '../lib/useOpenProfile'
import './ProfileSearch.css'

/** Header lookup: find anyone by part of an email, an app user id or a visitor id. */
export default function ProfileSearch() {
  const openProfile = useOpenProfile()
  const listId = useId()
  const [term, setTerm] = useState('')
  const [results, setResults] = useState<{ term: string; people: Person[] }>({ term: '', people: [] })
  const [active, setActive] = useState(0)
  const [open, setOpen] = useState(false)
  const boxRef = useRef<HTMLDivElement>(null)

  const query = term.trim()
  useEffect(() => {
    if (query.length < 2) return
    const timer = setTimeout(() => {
      apiGet<Person[]>(`/profiles/search?q=${encodeURIComponent(query)}`)
        .then((people) => setResults({ term: query, people }))
        .catch(() => setResults({ term: query, people: [] }))
    }, 200)
    return () => clearTimeout(timer)
  }, [query])

  useEffect(() => {
    const onClick = (e: MouseEvent) => !boxRef.current?.contains(e.target as Node) && setOpen(false)
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [])

  const people = query.length >= 2 && results.term === query ? results.people : []
  const showList = open && query.length >= 2 && results.term === query

  function choose(person: Person) {
    openProfile(person.profile_id)
    setTerm('')
    setOpen(false)
  }

  function onKey(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'ArrowDown') setActive((i) => Math.min(i + 1, people.length - 1))
    else if (e.key === 'ArrowUp') setActive((i) => Math.max(i - 1, 0))
    else if (e.key === 'Enter' && people[active]) choose(people[active])
    else if (e.key === 'Escape') setOpen(false)
    else return
    e.preventDefault()
  }

  return (
    <div className="profile-search" ref={boxRef}>
      <input
        className="input search-input"
        type="search"
        placeholder="Find anyone: email, u_…, v_…"
        aria-label="Find a subscriber"
        role="combobox"
        aria-expanded={showList}
        aria-controls={listId}
        aria-activedescendant={showList && people[active] ? `${listId}-${active}` : undefined}
        value={term}
        onChange={(e) => {
          setTerm(e.target.value)
          setActive(0)
          setOpen(true)
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={onKey}
      />
      {showList && (
        <ul className="search-results" id={listId} role="listbox">
          {people.length === 0 && <li className="search-empty">No one matches “{query}”.</li>}
          {people.map((p, i) => (
            <li
              key={p.profile_id}
              id={`${listId}-${i}`}
              role="option"
              aria-selected={i === active}
              className={i === active ? 'search-result active' : 'search-result'}
              onMouseEnter={() => setActive(i)}
              onMouseDown={(e) => {
                e.preventDefault()
                choose(p)
              }}
            >
              <span className="search-email">{p.email ?? p.profile_id}</span>
              <span className="search-meta">
                {p.is_subscriber ? (p.status === 'active' ? 'Subscriber' : 'Unsubscribed') : 'App only'}
                {p.app_user_id && ` · ${p.app_user_id}`}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
