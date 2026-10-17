import { useEffect, useState } from 'react'
import { getHealth, type Health } from './api/client'
import './App.css'

function App() {
  const [health, setHealth] = useState<Health | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getHealth()
      .then(setHealth)
      .catch((err: Error) => setError(err.message))
  }, [])

  return (
    <main className="app">
      <h1>Mini Subscriber Data Platform</h1>
      <p className="status" role="status">
        {error && `API unavailable: ${error}`}
        {!error && !health && 'Connecting to the API…'}
        {health && `API ${health.status} · database ${health.database} · today is ${health.today}`}
      </p>
    </main>
  )
}

export default App
