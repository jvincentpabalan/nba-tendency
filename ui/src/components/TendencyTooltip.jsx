import { useState, useRef, useCallback } from 'react'
import { createPortal } from 'react-dom'
import styles from './TendencyTooltip.module.css'

const TOOLTIP_WIDTH = 340
const GAP = 10 // px between trigger and tooltip

/**
 * Find the tier whose range contains `value`.
 * If no exact match, returns the nearest tier by boundary distance.
 */
function findTier(tiers, value) {
  if (!tiers?.length) return null

  // Exact range match
  const exact = tiers.find(t => value >= t.range[0] && value <= t.range[1])
  if (exact) return exact

  // Nearest tier
  let best = null
  let bestDist = Infinity
  for (const t of tiers) {
    const dist = Math.min(Math.abs(value - t.range[0]), Math.abs(value - t.range[1]))
    if (dist < bestDist) {
      bestDist = dist
      best = t
    }
  }
  return best
}

function formatTierRange(range) {
  const [lo, hi] = range
  return lo === hi ? String(lo) : `${lo}–${hi}`
}

export default function TendencyTooltip({ guide, value, children }) {
  const [pos, setPos] = useState(null)
  const triggerRef = useRef(null)
  const hideTimerRef = useRef(null)

  const show = useCallback(() => {
    if (!guide) return
    clearTimeout(hideTimerRef.current)
    const rect = triggerRef.current?.getBoundingClientRect()
    if (!rect) return

    let x = rect.right + GAP
    let y = rect.top

    // Flip left if tooltip would overflow right viewport edge
    if (x + TOOLTIP_WIDTH > window.innerWidth - 8) {
      x = rect.left - TOOLTIP_WIDTH - GAP
    }

    // Keep tooltip within viewport vertically (rough estimate: 250px max height)
    y = Math.min(y, window.innerHeight - 260)
    y = Math.max(y, 8)

    setPos({ x, y })
  }, [guide])

  const hide = useCallback(() => {
    hideTimerRef.current = setTimeout(() => setPos(null), 80)
  }, [])

  const keepOpen = useCallback(() => {
    clearTimeout(hideTimerRef.current)
  }, [])

  if (!guide) {
    return <span>{children}</span>
  }

  const tier = findTier(guide.tiers, value)

  return (
    <>
      <span ref={triggerRef} onMouseEnter={show} onMouseLeave={hide} className={styles.trigger}>
        {children}
      </span>

      {pos && createPortal(
        <div
          className={styles.popup}
          style={{ left: pos.x, top: pos.y, width: TOOLTIP_WIDTH }}
          onMouseEnter={keepOpen}
          onMouseLeave={hide}
        >
          {guide.definition && (
            <p className={styles.definition}>{guide.definition}</p>
          )}

          {tier && (
            <div className={styles.tier}>
              <span className={styles.tierRange}>{formatTierRange(tier.range)}</span>
              <span className={styles.tierLabel}>{tier.label}</span>
            </div>
          )}

          <div className={styles.meta}>
            {guide.nba_norm && (
              <span className={styles.metaItem}>
                <span className={styles.metaKey}>NBA Norm</span>
                <span className={styles.metaVal}>{guide.nba_norm}</span>
              </span>
            )}
            {guide.cap != null && (
              <span className={styles.metaItem}>
                <span className={styles.metaKey}>Cap</span>
                <span className={styles.metaVal}>{guide.cap}</span>
              </span>
            )}
          </div>
        </div>,
        document.body
      )}
    </>
  )
}
