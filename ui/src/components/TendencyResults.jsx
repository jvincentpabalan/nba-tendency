import { useState, useCallback, useRef } from 'react'
import styles from './TendencyResults.module.css'
import TendencyTooltip from './TendencyTooltip'
import guide from '../data/tendency_guide.json'

const GROUP_ORDER = [
  'Freelance',
  'Jump Shooting',
  'Layups And Dunks',
  'Driving',
  'Drive Setup',
  'Post Game',
  'Passing',
  'Defense',
]

function valueColor(value) {
  if (value >= 75) return '#00c896'
  if (value >= 50) return '#4da6ff'
  if (value >= 25) return '#fdb927'
  return '#ff6b6b'
}

function clamp(val) {
  const n = parseInt(val, 10)
  if (isNaN(n)) return 0
  return Math.max(0, Math.min(99, n))
}

export default function TendencyResults({ result }) {
  const { player_name, season, season_type, tendencies } = result
  const [collapsed, setCollapsed] = useState({})
  const [editMode, setEditMode] = useState(false)
  // overrides: { [key]: number } — only keys the user changed
  const [overrides, setOverrides] = useState({})

  // Effective value for a key: override if set, else original
  const effectiveValue = useCallback((key) => {
    return key in overrides ? overrides[key] : tendencies[key].value
  }, [overrides, tendencies])

  // Group tendencies
  const groups = {}
  for (const [key, entry] of Object.entries(tendencies)) {
    if (!groups[entry.group]) groups[entry.group] = []
    const name = key.split(':').slice(1).join(':')
    groups[entry.group].push({ key, name, ...entry })
  }

  const orderedGroups = [
    ...GROUP_ORDER.filter(g => groups[g]),
    ...Object.keys(groups).filter(g => !GROUP_ORDER.includes(g)),
  ]

  const [copied, setCopied] = useState(false)
  const copyTimerRef = useRef(null)

  const editedCount = Object.keys(overrides).length
  const hasEdits = editedCount > 0

  function toggleGroup(g) {
    setCollapsed(prev => ({ ...prev, [g]: !prev[g] }))
  }

  function handleValueChange(key, raw) {
    const val = clamp(raw)
    if (val === tendencies[key].value) {
      // Matches original — remove override
      setOverrides(prev => {
        const next = { ...prev }
        delete next[key]
        return next
      })
    } else {
      setOverrides(prev => ({ ...prev, [key]: val }))
    }
  }

  function handleInputChange(key, raw) {
    // Allow empty string while typing; commit on blur
    setOverrides(prev => ({ ...prev, [key]: raw }))
  }

  function handleInputBlur(key, raw) {
    const val = clamp(raw)
    if (val === tendencies[key].value) {
      setOverrides(prev => {
        const next = { ...prev }
        delete next[key]
        return next
      })
    } else {
      setOverrides(prev => ({ ...prev, [key]: val }))
    }
  }

  function handleReset(key) {
    setOverrides(prev => {
      const next = { ...prev }
      delete next[key]
      return next
    })
  }

  function handleResetAll() {
    setOverrides({})
  }

  function buildPayload() {
    const mergedTendencies = {}
    for (const [key, entry] of Object.entries(tendencies)) {
      mergedTendencies[key] = { ...entry, value: effectiveValue(key) }
    }
    return { _version: result._version, _format: result._format, tendencies: mergedTendencies }
  }

  function handleCopy() {
    const json = JSON.stringify(buildPayload(), null, 2)
    navigator.clipboard.writeText(json).then(() => {
      setCopied(true)
      clearTimeout(copyTimerRef.current)
      copyTimerRef.current = setTimeout(() => setCopied(false), 2000)
    })
  }

  function handleDownload() {
    const blob = new Blob([JSON.stringify(buildPayload(), null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    const slug = player_name.replace(/\s+/g, '_').toLowerCase()
    const stSlug = (season_type || 'regular_season').replace(/\s+/g, '_').toLowerCase()
    a.download = `${slug}_${season}_${stSlug}.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className={styles.root}>
      <div className={styles.resultHeader}>
        <div>
          <h2 className={styles.playerName}>{player_name}</h2>
          <p className={styles.meta}>{season} &middot; {season_type}</p>
        </div>
        <div className={styles.headerActions}>
          <div className={styles.headerButtons}>
            {editMode && hasEdits && (
              <button className={styles.resetAllBtn} onClick={handleResetAll}>
                Reset all ({editedCount})
              </button>
            )}
            {editMode && hasEdits && (
              <span className={styles.editBadge}>{editedCount} edited</span>
            )}
            <button
              className={`${styles.editBtn}${editMode ? ' ' + styles.active : ''}`}
              onClick={() => setEditMode(m => !m)}
            >
              {editMode ? 'Done Editing' : 'Edit Tendencies'}
            </button>
            <button className={styles.downloadBtn} onClick={handleCopy}>
              {copied ? 'Copied!' : 'Copy JSON'}
            </button>
            <button className={styles.downloadBtn} onClick={handleDownload}>
              Download JSON
            </button>
          </div>
        </div>
      </div>

      <div className={styles.groups}>
        {orderedGroups.map(group => {
          const items = groups[group]
          const isCollapsed = collapsed[group]
          return (
            <div key={group} className={styles.groupCard}>
              <button
                className={styles.groupHeader}
                onClick={() => toggleGroup(group)}
              >
                <span className={styles.groupName}>{group}</span>
                <span className={styles.groupCount}>{items.length}</span>
                <span className={styles.chevron}>{isCollapsed ? '▸' : '▾'}</span>
              </button>
              {!isCollapsed && (
                <div className={styles.tendencyList}>
                  {items.map(t => {
                    const isEdited = t.key in overrides
                    const currentVal = effectiveValue(t.key)
                    const displayVal = isEdited && typeof overrides[t.key] === 'string'
                      ? overrides[t.key]
                      : currentVal

                    return (
                      <div
                        key={t.key}
                        className={`${styles.tendencyRow}${isEdited ? ' ' + styles.edited : ''}`}
                      >
                        <span className={styles.tendencyName}>
                          {isEdited && <span className={styles.editedDot} title="Edited" />}
                          <TendencyTooltip guide={guide[t.key]} value={currentVal}>
                            {t.name}
                          </TendencyTooltip>
                        </span>
                        <div className={styles.barTrack}>
                          <div
                            className={styles.barFill}
                            style={{
                              width: `${(clamp(currentVal) / 99) * 100}%`,
                              background: isEdited ? '#c8102e' : valueColor(currentVal),
                            }}
                          />
                        </div>
                        {editMode ? (
                          <div className={styles.editControls}>
                            <input
                              className={styles.valueInput}
                              type="number"
                              min={0}
                              max={99}
                              value={typeof overrides[t.key] === 'string' ? overrides[t.key] : currentVal}
                              onChange={e => handleInputChange(t.key, e.target.value)}
                              onBlur={e => handleInputBlur(t.key, e.target.value)}
                            />
                            <button
                              className={`${styles.resetBtn}${isEdited ? ' ' + styles.visible : ''}`}
                              onClick={() => handleReset(t.key)}
                              title="Reset to computed value"
                              disabled={!isEdited}
                            >
                              ↺
                            </button>
                          </div>
                        ) : (
                          <span
                            className={styles.tendencyValue}
                            style={{ color: isEdited ? '#c8102e' : valueColor(currentVal) }}
                          >
                            {currentVal}
                          </span>
                        )}
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
