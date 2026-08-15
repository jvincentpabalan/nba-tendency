import { useState, useEffect } from 'react'
import TendencyResults from './components/TendencyResults'
import styles from './App.module.css'

const SEASONS = []
for (let y = 2024; y >= 1996; y--) {
  SEASONS.push(`${y}-${String(y + 1).slice(-2)}`)
}

const SEASON_TYPES = ['Regular Season', 'Playoffs', 'Pre Season']

export default function App() {
  const [teams, setTeams] = useState([])
  const [season, setSeason] = useState('2024-25')
  const [seasonType, setSeasonType] = useState('Regular Season')
  const [selectedTeam, setSelectedTeam] = useState(null)
  const [roster, setRoster] = useState([])
  const [rosterLoading, setRosterLoading] = useState(false)
  const [selectedPlayer, setSelectedPlayer] = useState(null)
  const [generating, setGenerating] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetch('/api/teams').then(r => r.json()).then(setTeams).catch(() => {})
  }, [])

  useEffect(() => {
    if (!selectedTeam) {
      setRoster([])
      setSelectedPlayer(null)
      return
    }
    setRosterLoading(true)
    setSelectedPlayer(null)
    setError(null)
    fetch(`/api/roster?team_id=${selectedTeam.id}&season=${season}`)
      .then(r => {
        if (!r.ok) throw new Error('Failed to load roster')
        return r.json()
      })
      .then(data => {
        setRoster(data)
        setRosterLoading(false)
      })
      .catch(e => {
        setError(e.message)
        setRosterLoading(false)
      })
  }, [selectedTeam, season])

  async function handleGenerate() {
    if (!selectedPlayer) return
    setGenerating(true)
    setResult(null)
    setError(null)
    try {
      const res = await fetch('/api/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          player_id: selectedPlayer.player_id,
          player_name: selectedPlayer.player_name,
          season,
          season_type: seasonType,
        }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || 'Generation failed')
      }
      setResult(await res.json())
    } catch (e) {
      setError(e.message)
    } finally {
      setGenerating(false)
    }
  }

  function handleTeamChange(e) {
    const team = teams.find(t => t.id === parseInt(e.target.value))
    setSelectedTeam(team || null)
    setResult(null)
  }

  function handlePlayerChange(e) {
    const player = roster.find(p => p.player_id === parseInt(e.target.value))
    setSelectedPlayer(player || null)
    setResult(null)
  }

  function handleSeasonChange(e) {
    setSeason(e.target.value)
    setRoster([])
    setSelectedPlayer(null)
    setResult(null)
  }

  const canGenerate = !!selectedPlayer && !generating

  return (
    <div className={styles.app}>
      <header className={styles.header}>
        <div className={styles.headerInner}>
          <span className={styles.logo}>NBA</span>
          <h1>2K26 Tendency Generator</h1>
        </div>
      </header>

      <div className={styles.layout}>
        <aside className={styles.sidebar}>
          <div className={styles.sidebarTitle}>Configure</div>

          <div className={styles.field}>
            <label className={styles.label}>Season</label>
            <select className={styles.select} value={season} onChange={handleSeasonChange}>
              {SEASONS.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>

          <div className={styles.field}>
            <label className={styles.label}>Season Type</label>
            <select className={styles.select} value={seasonType} onChange={e => setSeasonType(e.target.value)}>
              {SEASON_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>

          <div className={styles.field}>
            <label className={styles.label}>Team</label>
            <select className={styles.select} value={selectedTeam?.id || ''} onChange={handleTeamChange}>
              <option value=''>Select a team…</option>
              {teams.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
          </div>

          <div className={styles.field}>
            <label className={styles.label}>Player</label>
            <select
              className={styles.select}
              value={selectedPlayer?.player_id || ''}
              onChange={handlePlayerChange}
              disabled={!selectedTeam || rosterLoading || roster.length === 0}
            >
              <option value=''>
                {rosterLoading ? 'Loading roster…' : !selectedTeam ? 'Select a team first' : 'Select a player…'}
              </option>
              {roster.map(p => (
                <option key={p.player_id} value={p.player_id}>
                  {p.number ? `#${p.number} ` : ''}{p.player_name}{p.position ? ` · ${p.position}` : ''}
                </option>
              ))}
            </select>
          </div>

          <button
            className={styles.generateBtn}
            onClick={handleGenerate}
            disabled={!canGenerate}
          >
            {generating ? (
              <>
                <span className={styles.spinner} />
                Generating…
              </>
            ) : 'Generate Tendencies'}
          </button>

          {generating && (
            <p className={styles.hint}>Fetching stats from NBA.com (~15s)</p>
          )}

          {error && <p className={styles.error}>{error}</p>}
        </aside>

        <main className={styles.main}>
          {result ? (
            <TendencyResults result={result} />
          ) : (
            <div className={styles.empty}>
              <div className={styles.emptyIcon}>🏀</div>
              <p>Select a team and player, then click <strong>Generate Tendencies</strong></p>
            </div>
          )}
        </main>
      </div>
    </div>
  )
}
