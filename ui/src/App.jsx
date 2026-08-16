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
  const [error, setError] = useState(null)

  // rosterPlayers: [{ result, overrides: {} }]
  // result contains _player_id, _touch_raw, _shot_raw, tendencies, etc.
  const [rosterPlayers, setRosterPlayers] = useState([])
  const [activePlayerId, setActivePlayerId] = useState(null)

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
      const result = await res.json()
      setRosterPlayers(prev => {
        const exists = prev.findIndex(p => p.result._player_id === result._player_id)
        if (exists !== -1) {
          const next = [...prev]
          next[exists] = { ...next[exists], result }
          return next
        }
        return [...prev, { result, overrides: {} }]
      })
      setActivePlayerId(result._player_id)
    } catch (e) {
      setError(e.message)
    } finally {
      setGenerating(false)
    }
  }

  // Normalize Freelance:Shot and Freelance:Touches across all roster players.
  // The star player (highest raw score) keeps their individually-computed value.
  // All others scale proportionally down from that anchor.
  function handleNormalize() {
    if (rosterPlayers.length < 2) return

    const touchRaws = rosterPlayers.map(p => p.result._touch_raw ?? 0)
    const shotRaws  = rosterPlayers.map(p => p.result._shot_raw  ?? 0)

    const maxTouchRaw = Math.max(...touchRaws)
    const maxShotRaw  = Math.max(...shotRaws)

    const starTouchVal = rosterPlayers[touchRaws.indexOf(maxTouchRaw)]
      .result.tendencies['Freelance:Touches'].value
    const starShotVal = rosterPlayers[shotRaws.indexOf(maxShotRaw)]
      .result.tendencies['Freelance:Shot'].value

    setRosterPlayers(prev => prev.map((p, i) => {
      const touchRatio = maxTouchRaw > 0 ? touchRaws[i] / maxTouchRaw : 0
      const shotRatio  = maxShotRaw  > 0 ? shotRaws[i]  / maxShotRaw  : 0

      const normTouch = Math.round(Math.max(10, Math.min(75, touchRatio * starTouchVal)))
      const normShot  = Math.round(Math.max(10, Math.min(75, shotRatio  * starShotVal)))

      const newOverrides = { ...p.overrides }
      if (normTouch !== p.result.tendencies['Freelance:Touches'].value) {
        newOverrides['Freelance:Touches'] = normTouch
      } else {
        delete newOverrides['Freelance:Touches']
      }
      if (normShot !== p.result.tendencies['Freelance:Shot'].value) {
        newOverrides['Freelance:Shot'] = normShot
      } else {
        delete newOverrides['Freelance:Shot']
      }

      return { ...p, overrides: newOverrides }
    }))
  }

  function handleOverrideChange(playerId, key, val) {
    setRosterPlayers(prev => prev.map(p =>
      p.result._player_id === playerId
        ? { ...p, overrides: { ...p.overrides, [key]: val } }
        : p
    ))
  }

  function handleResetOverride(playerId, key) {
    setRosterPlayers(prev => prev.map(p => {
      if (p.result._player_id !== playerId) return p
      const next = { ...p.overrides }
      delete next[key]
      return { ...p, overrides: next }
    }))
  }

  function handleResetAll(playerId) {
    setRosterPlayers(prev => prev.map(p =>
      p.result._player_id === playerId ? { ...p, overrides: {} } : p
    ))
  }

  function handleRemovePlayer(playerId) {
    setRosterPlayers(prev => {
      const next = prev.filter(p => p.result._player_id !== playerId)
      if (activePlayerId === playerId) {
        setActivePlayerId(next.length > 0 ? next[next.length - 1].result._player_id : null)
      }
      return next
    })
  }

  function handleTeamChange(e) {
    const team = teams.find(t => t.id === parseInt(e.target.value))
    setSelectedTeam(team || null)
  }

  function handlePlayerChange(e) {
    const player = roster.find(p => p.player_id === parseInt(e.target.value))
    setSelectedPlayer(player || null)
  }

  function handleSeasonChange(e) {
    setSeason(e.target.value)
    setRoster([])
    setSelectedPlayer(null)
  }

  const canGenerate = !!selectedPlayer && !generating
  const hasRoster = rosterPlayers.length > 0
  const canNormalize = rosterPlayers.length >= 2
  const activePlayer = rosterPlayers.find(p => p.result._player_id === activePlayerId) ?? null

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

          {hasRoster && (
            <div className={styles.rosterSection}>
              <div className={styles.rosterSectionHeader}>
                <span className={styles.sidebarTitle}>Roster ({rosterPlayers.length})</span>
                <button
                  className={styles.clearRosterBtn}
                  onClick={() => setRosterPlayers([])}
                >
                  Clear
                </button>
              </div>

              <div className={styles.rosterList}>
                {rosterPlayers.map(p => {
                  const isActive = p.result._player_id === activePlayerId
                  return (
                    <div
                      key={p.result._player_id}
                      className={`${styles.rosterItem}${isActive ? ' ' + styles.rosterItemActive : ''}`}
                      onClick={() => setActivePlayerId(p.result._player_id)}
                    >
                      <span className={styles.rosterItemName}>{p.result.player_name}</span>
                      <button
                        className={styles.rosterRemoveBtn}
                        onClick={e => { e.stopPropagation(); handleRemovePlayer(p.result._player_id) }}
                        title="Remove"
                      >
                        ✕
                      </button>
                    </div>
                  )
                })}
              </div>

              {canNormalize && (
                <button className={styles.normalizeBtn} onClick={handleNormalize}>
                  Normalize Freelance
                </button>
              )}
            </div>
          )}
        </aside>

        <main className={styles.main}>
          {activePlayer ? (
            <TendencyResults
              key={activePlayer.result._player_id}
              result={activePlayer.result}
              overrides={activePlayer.overrides}
              onOverrideChange={(key, val) => handleOverrideChange(activePlayer.result._player_id, key, val)}
              onResetOverride={(key) => handleResetOverride(activePlayer.result._player_id, key)}
              onResetAll={() => handleResetAll(activePlayer.result._player_id)}
              onRemove={() => handleRemovePlayer(activePlayer.result._player_id)}
            />
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
