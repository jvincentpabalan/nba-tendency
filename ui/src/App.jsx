import { useState, useEffect } from 'react'
import TendencyResults from './components/TendencyResults'
import styles from './App.module.css'

const SEASONS = []
for (let y = 2024; y >= 1996; y--) {
  SEASONS.push(`${y}-${String(y + 1).slice(-2)}`)
}

const SEASON_TYPES = ['Regular Season', 'Playoffs', 'Pre Season']

function prevSeason(s) {
  const yr = parseInt(s.split('-')[0]) - 1
  return `${yr}-${String(yr + 1).slice(-2)}`
}

export default function App() {
  const [teams, setTeams] = useState([])

  // Primary season: controls roster lookup AND is always the first analysis season.
  const [season, setSeason] = useState('2024-25')
  // Additional seasons to blend (on top of the primary).
  const [extraSeasons, setExtraSeasons] = useState([])
  // Value shown in the "add season" picker.
  const [addSeasonPick, setAddSeasonPick] = useState(prevSeason('2024-25'))

  const [seasonType, setSeasonType] = useState('Regular Season')
  const [blendEnabled, setBlendEnabled] = useState(false)
  const [blendPct, setBlendPct] = useState(70)

  const [selectedTeam, setSelectedTeam] = useState(null)
  const [roster, setRoster] = useState([])
  const [rosterLoading, setRosterLoading] = useState(false)
  const [selectedPlayer, setSelectedPlayer] = useState(null)
  const [generating, setGenerating] = useState(false)
  const [error, setError] = useState(null)

  const [rosterPlayers, setRosterPlayers] = useState([])
  const [activePlayerId, setActivePlayerId] = useState(null)
  const [generatingAll, setGeneratingAll] = useState(false)
  const [generateAllProgress, setGenerateAllProgress] = useState(null) // { current, total } | null

  // All seasons sent to the API (primary + extras).
  const allSeasons = [season, ...extraSeasons]
  // Seasons already in the analysis list (for filtering the add-picker).
  const seasonSet = new Set(allSeasons)

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

  function handleSeasonChange(e) {
    const next = e.target.value
    setSeason(next)
    setExtraSeasons([])
    setAddSeasonPick(prevSeason(next))
    setRoster([])
    setSelectedPlayer(null)
  }

  function handleAddSeason() {
    if (!addSeasonPick || seasonSet.has(addSeasonPick)) return
    setExtraSeasons(prev => [...prev, addSeasonPick])
    // Advance the picker to the next unselected season.
    const nextPick = SEASONS.find(s => !seasonSet.has(s) && s !== addSeasonPick)
    if (nextPick) setAddSeasonPick(nextPick)
  }

  function handleRemoveExtraSeason(s) {
    setExtraSeasons(prev => prev.filter(x => x !== s))
  }

  async function handleGenerate() {
    if (!selectedPlayer) return
    setGenerating(true)
    setError(null)
    try {
      const body = {
        player_id: selectedPlayer.player_id,
        player_name: selectedPlayer.player_name,
        seasons: allSeasons,
        season_type: blendEnabled ? 'Regular Season' : seasonType,
        blend_pct: blendEnabled ? blendPct : null,
      }
      const res = await fetch('/api/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!res.ok) {
        const b = await res.json().catch(() => ({}))
        throw new Error(b.detail || 'Generation failed')
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

  async function handleGenerateAll() {
    if (!canGenerateAll) return
    setGeneratingAll(true)
    setError(null)
    const total = roster.length
    for (let i = 0; i < total; i++) {
      const player = roster[i]
      setGenerateAllProgress({ current: i + 1, total })
      try {
        const body = {
          player_id: player.player_id,
          player_name: player.player_name,
          seasons: allSeasons,
          season_type: blendEnabled ? 'Regular Season' : seasonType,
          blend_pct: blendEnabled ? blendPct : null,
        }
        const res = await fetch('/api/generate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        })
        if (!res.ok) {
          const b = await res.json().catch(() => ({}))
          throw new Error(`${player.player_name}: ${b.detail || 'Generation failed'}`)
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
      }
    }
    setGeneratingAll(false)
    setGenerateAllProgress(null)
  }

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

  const canGenerate = !!selectedPlayer && !generating && !generatingAll
  const canGenerateAll = !!selectedTeam && roster.length > 0 && !generating && !generatingAll
  const hasRoster = rosterPlayers.length > 0
  const canNormalize = rosterPlayers.length >= 2
  const activePlayer = rosterPlayers.find(p => p.result._player_id === activePlayerId) ?? null

  // Seasons available to add (not already in the list).
  const availableToAdd = SEASONS.filter(s => !seasonSet.has(s))

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

          {/* Primary season */}
          <div className={styles.field}>
            <label className={styles.label}>Season</label>
            <select className={styles.select} value={season} onChange={handleSeasonChange}>
              {SEASONS.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>

          {/* Multi-season chips + add row */}
          {extraSeasons.length > 0 && (
            <div className={styles.seasonChips}>
              <span className={styles.seasonChip} title="Primary season (controls roster)">
                {season}
              </span>
              {extraSeasons.map(s => (
                <span key={s} className={styles.seasonChip}>
                  {s}
                  <button
                    className={styles.seasonChipRemove}
                    onClick={() => handleRemoveExtraSeason(s)}
                    title="Remove season"
                  >
                    ✕
                  </button>
                </span>
              ))}
            </div>
          )}

          <div className={styles.addSeasonRow}>
            <select
              className={styles.addSeasonSelect}
              value={addSeasonPick}
              onChange={e => setAddSeasonPick(e.target.value)}
              disabled={availableToAdd.length === 0}
            >
              {availableToAdd.map(s => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
            <button
              className={styles.addSeasonBtn}
              onClick={handleAddSeason}
              disabled={availableToAdd.length === 0 || seasonSet.has(addSeasonPick)}
              title="Add season to blend"
            >
              + Add
            </button>
          </div>

          {/* Blend toggle */}
          <div className={styles.blendSection}>
            <label className={styles.blendToggle}>
              <input
                type="checkbox"
                checked={blendEnabled}
                onChange={e => setBlendEnabled(e.target.checked)}
              />
              <span>Blend RS + Playoffs</span>
            </label>
            {blendEnabled && (
              <div className={styles.blendPctRow}>
                <span className={styles.blendPctLabel}>RS weight</span>
                <input
                  type="range"
                  min={50}
                  max={90}
                  step={5}
                  value={blendPct}
                  className={styles.blendSlider}
                  onChange={e => setBlendPct(parseInt(e.target.value))}
                />
                <span className={styles.blendPctValue}>{blendPct}% / {100 - blendPct}%</span>
              </div>
            )}
          </div>

          {/* Season type (hidden when blending RS+PO) */}
          {!blendEnabled && (
            <div className={styles.field}>
              <label className={styles.label}>Season Type</label>
              <select className={styles.select} value={seasonType} onChange={e => setSeasonType(e.target.value)}>
                {SEASON_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>
          )}

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

          <button
            className={styles.generateAllBtn}
            onClick={handleGenerateAll}
            disabled={!canGenerateAll}
          >
            {generatingAll ? (
              <>
                <span className={styles.spinner} />
                {generateAllProgress
                  ? `${generateAllProgress.current} / ${generateAllProgress.total}`
                  : 'Starting…'}
              </>
            ) : 'Generate Entire Roster'}
          </button>

          {(generating || generatingAll) && (
            <p className={styles.hint}>
              {generatingAll && generateAllProgress
                ? `${generateAllProgress.current} of ${generateAllProgress.total} players — fetching from NBA.com…`
                : `Fetching stats from NBA.com${allSeasons.length > 1 ? ` (${allSeasons.length} seasons…)` : ' (~15s)'}${blendEnabled ? ' — RS + PO' : ''}`}
            </p>
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
