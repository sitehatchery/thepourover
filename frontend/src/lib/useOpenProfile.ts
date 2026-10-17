import { useSearchParams } from 'react-router-dom'

/** Opens the subscriber activity dialog by adding ?profile=<id> to the current URL (so it's linkable). */
export function useOpenProfile() {
  const [params, setParams] = useSearchParams()
  return (profileId: string) => {
    const next = new URLSearchParams(params)
    next.set('profile', profileId)
    setParams(next)
  }
}
