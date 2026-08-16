"""
Map PlayerStats → NBA 2K26 tendencies.

All caps sourced from the official ATD Committee Master Tendency Scale CSV.
Scaling rule:
  _scale(raw, norm_low_raw, norm_high_raw, out_low, out_high)
  Maps raw stat linearly between anchors. out_high = absolute cap from guide.
  Values represent willingness/frequency (tendency), NOT skill.
"""

from __future__ import annotations
from stats_collector import PlayerStats


# ──────────────────────────────────────────────────────────────────────────────
# Core helpers
# ──────────────────────────────────────────────────────────────────────────────

def _scale(value: float,
           low_raw: float,
           high_raw: float,
           out_low: int = 5,
           out_high: int = 45,
           floor: int = 5) -> int:
    """
    Linearly map `value` in [low_raw, high_raw] → [out_low, out_high].
    Clamped: below low_raw pulls toward out_low; above high_raw capped at out_high.
    """
    if high_raw <= low_raw:
        return out_low
    ratio = (value - low_raw) / (high_raw - low_raw)
    ratio = max(0.0, min(1.0, ratio))
    result = out_low + ratio * (out_high - out_low)
    return int(max(floor, min(out_high, round(result))))


def _pct(num: float, denom: float) -> float:
    return num / denom if denom > 0 else 0.0


def _dir_split(left: float, lc: float, center: float, rc: float, right: float,
               base: int, cap: int) -> tuple[int, int, int, int, int]:
    """
    Distribute base tendency across 5 directional zones by shot frequency.
    Returns (left, left-center, center, right-center, right).
    The dominant zone equals base; others are proportionally lower.
    """
    total = left + lc + center + rc + right
    if total == 0:
        even = base // 2
        return even, even, base, even, even
    max_zone = max(left, lc, center, rc, right)
    results = []
    for freq in (left, lc, center, rc, right):
        val = round((freq / max_zone) * base)
        val = max(5, min(cap, val))
        results.append(val)
    return tuple(results)


# ──────────────────────────────────────────────────────────────────────────────
# Main mapper
# ──────────────────────────────────────────────────────────────────────────────

def compute(stats: PlayerStats) -> dict:
    """Return a flat dict of tendency_label → value."""
    t = {}
    # Use box-score FGA as primary denominator — zone-derived total_fga can be
    # undercounted for older seasons if some zones return 0 (inflates pct_3 to ~1.0).
    fga = stats.fga if stats.fga > 0 else max(stats.total_fga, 1.0)

    pct_ra         = _pct(stats.fga_restricted,  fga)
    pct_close      = _pct(stats.fga_paint_nonra, fga)
    pct_mid        = _pct(stats.fga_mid,         fga)
    # Use the higher of zone-sum and box-score 3PT FGA. Zone data occasionally
    # undercounts for older seasons (some shots fall outside categorized zones);
    # fg3a from general splits is authoritative. Taking the max recovers both.
    three_fga = max(stats.total_3pt_fga, stats.fg3a) if stats.total_3pt_fga > 0 else stats.fg3a
    pct_3          = _pct(three_fga,   fga)
    pct_stepback   = _pct(stats.fga_step_back,   fga)
    pct_turnaround = _pct(stats.fga_turnaround,  fga)
    iso_freq  = stats.synergy_iso
    post_freq = stats.synergy_post
    # Face-up ISO: remove post-up overlap to avoid inflating dribble moves.
    # Post-heavy bigs (post_freq > 3.5) have more of their unassisted FGM pool
    # coming from post self-creation, so use a higher subtraction coefficient.
    post_overlap_coef = 0.50 if post_freq > 3.5 else 0.30
    faceup_iso = max(0.0, iso_freq - post_freq * post_overlap_coef)

    # PnR ball-handler discount for ISO vs. defender tiers.
    # Pass-first guards accumulate unassisted FGM from PnR drives, not true isolation.
    # ast_ratio signals playmaking orientation: 0.1 = scorer, 0.5+ = PnR guard.
    # Discount linearly: full weight at ast_ratio≈0.1, floor 0.25 at ast_ratio≈0.5+.
    # Dribble-move tendencies (faceup_iso) are intentionally left undiscounted —
    # PnR ball handlers ARE creative with the ball even if they don't truly isolate.
    ast_ratio = _pct(stats.ast, stats.ast + stats.fga)
    iso_score_freq = iso_freq * max(0.25, 1.0 - ast_ratio * 1.5)

    # ── JUMP SHOOTING ─────────────────────────────────────────────────────

    # Shot Under Basket  — cap 85
    t["Jump Shooting:Shot Under Basket"] = _scale(pct_ra, 0, 0.45, 5, 85)

    # Shot Close  — cap 60
    t["Jump Shooting:Shot Close"] = _scale(pct_close, 0, 0.35, 5, 60)

    # Shot Mid-Range  — cap 45
    t["Jump Shooting:Shot Mid-Range"] = _scale(pct_mid, 0, 0.60, 5, 45)

    # Shot Three  — cap 75
    t["Jump Shooting:Shot Three"] = _scale(pct_3, 0, 0.50, 5, 75)

    # ── Directional Mid (cap 45) ──────────────────────────────────────────
    mid_base = t["Jump Shooting:Shot Mid-Range"]
    ml, mlc, mc, mrc, mr = _dir_split(
        stats.mid_left, stats.mid_left_center, stats.mid_center,
        stats.mid_right_center, stats.mid_right, mid_base, 45
    )
    t["Jump Shooting:Shot Mid Left"]         = ml
    t["Jump Shooting:Shot Mid Left-Center"]  = mlc
    t["Jump Shooting:Shot Mid Center"]       = mc
    t["Jump Shooting:Shot Mid Right-Center"] = mrc
    t["Jump Shooting:Shot Mid Right"]        = mr

    # ── Directional Three (cap 75) ────────────────────────────────────────
    three_base = t["Jump Shooting:Shot Three"]
    tl, tlc, tc, trc, tr = _dir_split(
        stats.three_left, stats.three_left_center, stats.three_center,
        stats.three_right_center, stats.three_right, three_base, 75
    )
    t["Jump Shooting:Shot Three Left"]         = tl
    t["Jump Shooting:Shot Three Left-Center"]  = tlc
    t["Jump Shooting:Shot Three Center"]       = tc
    t["Jump Shooting:Shot Three Right-Center"] = trc
    t["Jump Shooting:Shot Three Right"]        = tr

    # ── Directional Close (cap 60) ────────────────────────────────────────
    close_base = t["Jump Shooting:Shot Close"]
    cl, _, cc, _, cr = _dir_split(
        stats.close_left, 0, stats.close_center,
        0, stats.close_right, close_base, 60
    )
    t["Jump Shooting:Shot Close Left"]   = cl
    t["Jump Shooting:Shot Close Middle"] = cc
    t["Jump Shooting:Shot Close Right"]  = cr

    # ── Spot-Up / Off-Screen ──────────────────────────────────────────────
    cs_approx   = stats.catch_shoot_fga or (stats.synergy_spotup * 1.0)
    cs_mid_frac = pct_mid / max(pct_mid + pct_3, 0.01)
    cs_3_frac   = 1.0 - cs_mid_frac

    # Assisted rate — used by Spot Up Drive (pre-2013 only)
    _fgm_tracked = stats.assisted_fgm + stats.unassisted_fgm
    _spot_up_mid_scale = (
        stats.assisted_fgm / _fgm_tracked
        if stats.catch_shoot_fga == 0 and _fgm_tracked > 0
        else 1.0
    )

    # Spot Up Mid-Range — cap 55
    # 2013-14+: catch_shoot_fga is directly measured; split by cs_mid_frac.
    # Pre-2013: use PCT_UAST_2PM to derive assisted 2PT makes, then weight by mid-range share
    # of 2PT attempts. This is more direct than the old 3PT-anchored synergy_spotup proxy,
    # which under-estimated catch-mid for heavy mid-range shooters like Dirk. Scale ceiling
    # is higher (4.5 vs 3.0) because assisted_2pm × mid_share produces larger raw values.
    if stats.catch_shoot_fga > 0:
        _spot_up_mid_raw = stats.catch_shoot_fga * cs_mid_frac
        t["Jump Shooting:Spot Up Shot Mid-Range"] = _scale(_spot_up_mid_raw, 0, 3.0, 5, 55)
    else:
        _two_pt_fgm      = max(stats.fgm - stats.fg3m, 0.0)
        _assisted_2pm    = _two_pt_fgm * (1.0 - stats.pct_uast_2pm)
        _total_2pt_fga   = max(fga - three_fga, 1.0)
        _mid_2pt_share   = stats.fga_mid / _total_2pt_fga
        _spot_up_mid_raw = _assisted_2pm * _mid_2pt_share
        t["Jump Shooting:Spot Up Shot Mid-Range"] = _scale(_spot_up_mid_raw, 0, 4.5, 5, 55)
    t["Jump Shooting:Off Screen Shot Mid-Range"] = _scale(stats.synergy_offscreen * cs_mid_frac, 0, 1.5, 5, 50)  # cap 50
    # Spot Up Three — cap 75
    # 2013-14+: catch_shoot_fga is directly measured; split by cs_3_frac to isolate 3PT portion.
    # Pre-2013: synergy_spotup is ALREADY 3PT-anchored (total_3pt_fga × 0.96 proxy) — do NOT
    # multiply by cs_3_frac again. That double-discounts mid-range-heavy players like Dirk
    # whose 3PT shot fraction is small even though they genuinely spot up for threes.
    _spot_3_vol = (stats.catch_shoot_fga * cs_3_frac
                   if stats.catch_shoot_fga > 0
                   else stats.synergy_spotup)
    t["Jump Shooting:Spot Up Shot Three"]        = _scale(_spot_3_vol, 0, 3.0, 5, 75)   # cap 75
    t["Jump Shooting:Off Screen Shot Three"]     = _scale(stats.synergy_offscreen * cs_3_frac, 0, 1.5, 5, 65)  # cap 65

    # ── Contested jumpers — cap 55 ────────────────────────────────────────
    # Contested Jumper is a subset of base shooting tendency — must never exceed it.
    t["Jump Shooting:Contested Jumper Mid-Range"] = min(
        _scale(pct_mid, 0.05, 0.55, 5, 55),
        t["Jump Shooting:Shot Mid-Range"]
    )
    t["Jump Shooting:Contested Jumper Three"] = min(
        _scale(pct_3, 0.02, 0.40, 5, 55),
        t["Jump Shooting:Shot Three"]
    )

    # ── Stepback jumpers — cap 55 / 60 ───────────────────────────────────
    t["Jump Shooting:Stepback Jumper Mid-Range"] = _scale(pct_stepback, 0, 0.05, 5, 55)
    t["Jump Shooting:Stepback Jumper Three"]     = _scale(pct_stepback * pct_3, 0, 0.02, 5, 60)

    # Spin Jumper  — cap 45; self-created perimeter spin into jumper only.
    # Exclude post/fadeaway turnarounds: strip fadeaway overlap and post-frequency contribution.
    # A pure post player (high fadeaway, high post_freq) nets near zero here.
    spin_jump_raw = max(0.0, stats.fga_turnaround - stats.fga_fadeaway * 0.4 - post_freq * 0.15)
    t["Jump Shooting:Spin Jumper"] = _scale(spin_jump_raw, 0, 0.5, 5, 45)

    # Transition Pull-Up Three  — cap 45
    # synergy_transition is always 0 (defunct endpoint). Use PCT_PTS_FB × 3PT share as proxy:
    # fast-break scoring rate × tendency to shoot 3s = pull-up-3 transition frequency.
    t["Jump Shooting:Transition Pull Up Three"] = _scale(
        stats.pct_pts_fb * pct_3, 0, 0.08, 5, 45)

    # Drive Pull Up Mid-Range  — cap 70
    # pullup_2pt_fga from player tracking (2013-14+ only).
    # Pre-2013: many pull-up mid-range shots are labeled generic "Jump Shot" (not "Pullup Jump Shot").
    # fga_uast_2pt_jump captures that hidden bucket via FG2A × PCT_UAST_2PM from the "Jump Shot" row.
    # Adding it to the labeled pullups gives a complete picture of dribble-created 2PT attempts.
    if stats.pullup_2pt_fga > 0:
        pu2 = stats.pullup_2pt_fga
    else:
        pu2 = stats.fga_pullup * (1 - pct_3) + stats.fga_uast_2pt_jump

    # Drive Pull-Up Three: player-tracking pullup_3pt_fga when available (2013-14+).
    # Pre-2013 fallback: fg3a × PCT_UAST_3PM = estimated self-created 3PA.
    # Replaces fga_pullup × pct_3 which mixed 2PT/3PT pull-ups with no 3PT specificity.
    if stats.pullup_3pt_fga > 0:
        pu3 = stats.pullup_3pt_fga
    elif stats.pct_uast_3pm > 0:
        pu3 = stats.fg3a * stats.pct_uast_3pm
    else:
        pu3 = stats.fga_pullup * pct_3
    t["Jump Shooting:Drive Pull Up Mid-Range"] = _scale(pu2, 0, 8, 5, 70)
    # Drive Pull Up Three  — cap 50
    t["Jump Shooting:Drive Pull Up Three"]     = _scale(pu3, 0, 4, 5, 50)

    # Use Glass  — cap 45
    # Bank shots occur from interior/mid range only, not 3PT. Use non-3PT FGA as
    # denominator to get a meaningful rate instead of diluting with 3PT attempts.
    interior_fga = max(stats.fga_restricted + stats.fga_paint_nonra + stats.fga_mid, 1.0)
    pct_bank = _pct(stats.fga_bank_shot, interior_fga)
    t["Jump Shooting:Use Glass"] = _scale(pct_bank, 0, 0.12, 5, 45)

    # Step Through Shot  — cap 50
    # Definition: footwork move from a drive, paint catch, face-up, or post-ADJACENT situation.
    # Explicitly SEPARATE from post-move tendencies. Proxy: paint access rate
    # (weighted driving layup + paint non-RA shots) as a proxy for situations where step-through occurs.
    step_through_rate = (stats.fga_driving_layup * 0.6 + stats.fga_paint_nonra * 0.4) / max(fga, 1.0)
    t["Jump Shooting:Step Through Shot"] = _scale(step_through_rate, 0, 0.30, 5, 50)

    # ── LAYUPS AND DUNKS ─────────────────────────────────────────────────

    # Driving Layup  — cap 80
    pct_driv_layup = _pct(stats.fga_driving_layup + stats.fga_finger_roll, fga)
    t["Layups And Dunks:Driving Layup"] = _scale(pct_driv_layup, 0, 0.25, 5, 80)

    # Standing Dunk  — cap 85
    # Definition: selection weight of dunk vs. layup at the rim (stationary/catch/oreb).
    # Denominator = standing rim attempts only, not total FGA.
    # fga_dunk (ShotTypeSummary "Dunk") excludes alley-oops; minus driving dunks = standing dunks.
    # fga_layup (ShotTypeSummary "Layup") minus driving layups = catch/standing layups.
    standing_dunk = max(0.0, stats.fga_dunk - stats.fga_driving_dunk)
    standing_layup = max(0.0, stats.fga_layup - stats.fga_driving_layup)
    dunk_pref = standing_dunk / max(standing_dunk + standing_layup, 0.01)
    t["Layups And Dunks:Standing Dunk"] = _scale(dunk_pref, 0, 1.0, 5, 85)

    # Driving Dunk  — cap 80
    t["Layups And Dunks:Driving Dunk"] = _scale(_pct(stats.fga_driving_dunk, fga), 0, 0.15, 5, 80)

    # Flashy Dunk  — cap 70
    # Definition: sub-selection AFTER a dunk is chosen — style preference (flashy vs. safe animation).
    # NOT a measure of dunk volume. Proxy: driving dunk volume × driving-preference ratio.
    # Players who dunk primarily off drives (vs. standing catches) are more likely to use flashy animations.
    _driving_dunk_pref = _pct(stats.fga_driving_dunk, max(stats.fga_dunk, 0.01))
    # rate × preference so Flashy Dunk ≤ Driving Dunk (preference ≤ 1.0 always)
    t["Layups And Dunks:Flashy Dunk"] = _scale(_pct(stats.fga_driving_dunk, fga) * _driving_dunk_pref, 0, 0.08, 5, 70)

    # Alley-Oop  — cap 85
    t["Layups And Dunks:Alley-Oop"] = _scale(_pct(stats.fga_alley_oop, fga), 0, 0.05, 5, 85)

    # Putback  — cap 70
    # Definition: IMMEDIATE scoring decision after securing an offensive rebound (tip/lay-in/dunk vs. reset).
    # Does NOT control how often the player gets offensive rebounds — oreb frequency is explicitly excluded.
    # Proxy: putback FGA rate = putback attempts / offensive rebounds obtained.
    _putback_rate = _pct(stats.fga_putback, max(stats.oreb, 0.1))
    t["Layups And Dunks:Putback"] = _scale(_putback_rate, 0, 0.80, 5, 70)

    # Crash  — cap 65
    # CSV: "conditional frequency that meaningful contact during an attacking finish
    # produces a stumble, loss of balance, or fall." Separate from rebounding.
    # Proxy: drive-to-rim volume × contact drawn rate.
    crash_proxy = stats.fga_driving_layup * _pct(stats.fta, fga)
    t["Layups And Dunks:Crash"] = _scale(crash_proxy, 0, 2.0, 5, 65)

    # Spin Layup  — cap 70
    pct_floater = _pct(stats.fga_floater, fga)
    t["Layups And Dunks:Spin Layup"] = _scale(pct_driv_layup * 0.3, 0, 0.08, 5, 70)

    # Hop Step Layup  — cap 65
    t["Layups And Dunks:Hop Step Layup"] = _scale(pct_driv_layup * 0.35, 0, 0.09, 5, 65)

    # Euro Step Layup  — cap 75
    # Pre-2013 shot data rarely tags attempts as "Euro Step"; those shots land in fga_driving_layup.
    # When explicit data is missing, use a conservative floor estimate from driving layup volume
    # scaled by ISO profile so low-ISO bigs stay near No Package (5–7).
    euro_fga = stats.fga_euro_step
    if euro_fga < 0.05 and stats.fga_driving_layup > 0.5:
        # Pre-2013 floor estimate — no real data; 9% of driving layups × ISO scaler.
        # Calibrated so typical NBA guards land in 10–17 (Rare), known users ~22–26 (Selective).
        # Scaler: faceup_iso/3.0 so low-ISO bigs stay near No Package (5–7).
        euro_fga = stats.fga_driving_layup * 0.09 * min(1.0, faceup_iso / 3.0)
    t["Layups And Dunks:Euro Step Layup"] = _scale(_pct(euro_fga, fga), 0, 0.06, 5, 75)

    # Floater  — cap 75
    t["Layups And Dunks:Floater"] = _scale(pct_floater, 0, 0.06, 5, 75)

    # ── DRIVING ──────────────────────────────────────────────────────────

    # Drive  — cap 75
    # CSV: "overall selection weight for INITIATING an on-ball drive. Does NOT control
    # drive success, commitment after advantage, finishing type, or contact seeking."
    # Proxy: shots that required a drive (layup/dunk/euro/floater) + iso drive contribution.
    # Explicitly excludes RA% and close% which measure finishing location, not initiation.
    drive_vol = (stats.fga_driving_layup + stats.fga_driving_dunk
                 + stats.fga_euro_step + stats.fga_floater)
    drive_pct = _pct(drive_vol + faceup_iso * 0.3, fga)
    t["Driving:Drive"] = _scale(drive_pct, 0, 0.35, 5, 75)

    # Spot-Up Drive  — cap 70
    t["Driving:Spot Up Drive"] = _scale(
        stats.synergy_spotup * cs_mid_frac * _spot_up_mid_scale * 0.4, 0, 1.5, 5, 70)

    # Off-Screen Drive  — cap 60
    # Most off-screen reads are shot-first; 0.25 replaces 0.4 (was over-counting drive converts)
    t["Driving:Off Screen Drive"] = _scale(stats.synergy_offscreen * 0.25, 0, 0.6, 5, 60)

    # Drive Right  — cap 95; scale: 5-25 extreme left, 45 mild left, 50 balanced, 55 mild right, 75-95 extreme right.
    # Guide: "50 means evidence-backed balance, not unknown or missing research."
    # "For meaningful drivers (Drive 30+), unresolved direction must not be finalized as 50."
    # No directional drive data available from NBA.com API — set to 50 as a placeholder.
    # MUST be researched via tracking data, film, or scouting before finalizing any Drive ≥ 30 player.
    t["Driving:Drive Right"] = 50

    # Driving dribble moves — caps per CSV
    t["Driving:Driving Crossover"]          = _scale(faceup_iso, 0, 8,    5, 60)  # cap 60
    t["Driving:Driving Spin"]               = _scale(faceup_iso * 0.3, 0, 2, 5, 50)  # cap 50
    t["Driving:Driving Step Back"]          = _scale(pct_stepback, 0, 0.06, 5, 55)   # cap 55
    t["Driving:Driving Half Spin"]          = _scale(faceup_iso * 0.2, 0, 1.5, 5, 45)  # cap 45
    t["Driving:Driving Double Crossover"]   = _scale(faceup_iso * 0.15, 0, 1.0, 5, 40) # cap 40
    t["Driving:Driving Behind The Back"]    = _scale(faceup_iso * 0.15, 0, 1.0, 5, 50) # cap 50
    t["Driving:Driving Dribble Hesitation"] = _scale(faceup_iso * 0.25, 0, 2.0, 5, 65) # cap 65
    t["Driving:Driving In And Out"]         = _scale(faceup_iso * 0.15, 0, 1.5, 5, 65) # cap 65

    # No Driving Dribble Move  — cap 90
    # Definition: selection weight for straight-line continuation vs. adding a dribble move
    # once the player is attacking. This controls dribble moves during the drive (spin,
    # crossover, hesitation), NOT the finishing type (euro step, floater).
    # NBA norm: 5–35 (most players are in the move-creative range).
    #
    # Shot-type ratio gives a finishing-type signal (layup vs. euro/floater) that correlates
    # with drive creativity but is not a direct measure of mid-drive dribble moves.
    # faceup_iso is a better proxy for dribble-move creativity: high-ISO players who create
    # off the dribble habitually add moves during drives too.
    # Blend both: shot-type ratio anchors to observable data; faceup_iso captures the
    # creative profile that the shot-type data can't fully separate (especially pre-2013).
    total_drive_atts = stats.fga_driving_layup + euro_fga + stats.fga_floater
    if total_drive_atts >= 1.0:
        shot_type_pct = _pct(stats.fga_driving_layup, total_drive_atts)
    else:
        shot_type_pct = 0.85  # sparse data: default to straight-line
    # ISO-based penalty: elite ISO (faceup_iso ≥ 8) → 0.29 floor; low ISO → 0.85 baseline
    iso_pct = max(0.29, 0.85 - min(faceup_iso, 8) * 0.07)
    # Equal blend of shot-type signal and ISO creativity profile
    straight_drive_pct = shot_type_pct * 0.5 + iso_pct * 0.5
    t["Driving:No Driving Dribble Move"] = _scale(straight_drive_pct, 0.20, 0.90, 10, 90)

    # Attack Strong On Drive  — cap 90
    # CSV: "controls willingness to CONTINUE the downhill attack toward the basket once
    # a drive has begun, instead of stopping for an early pull-up or reset."
    # This is drive COMMITMENT, not FTA rate. Proxy: rim finishes vs pull-up stops.
    rim_finish_vol = stats.fga_driving_layup + stats.fga_driving_dunk + stats.fga_euro_step + stats.fga_floater
    # pullup_2pt_fga = player tracking (2013-14+); fga_pullup = shot-type detail (all seasons,
    # includes "Driving Jump shot" — mid-range pull-ups off a drive that stop short of the rim).
    # For pre-2013, NBA labeled pull-ups as generic "Jump Shot" → fga_pullup ≈ 0.
    # Add fga_uast_2pt_jump (unassisted portion of generic "Jump Shot" 2PT) to capture them.
    if stats.pullup_2pt_fga > 0:
        pullup_vol = stats.pullup_2pt_fga
    else:
        pullup_vol = stats.fga_pullup + stats.fga_uast_2pt_jump
    total_drive_vol = max(rim_finish_vol + pullup_vol, 1.0)
    rim_commit_ratio = _pct(rim_finish_vol, total_drive_vol)
    t["Driving:Attack Strong On Drive"] = _scale(rim_commit_ratio, 0.15, 0.90, 20, 90)

    # ── DRIVE SETUP ───────────────────────────────────────────────────────

    usage_proxy = _pct(stats.fga, max(stats.fga + stats.ast, 1))

    # Triple Threat Shoot  — cap 55
    # Post players shouldn't hit cap — interior finishing bypasses triple-threat.
    # Dampen by post_freq so center-heavy players read lower here.
    tt_shoot_raw = usage_proxy * (1 - post_freq / 20.0)
    t["Drive Setup:Triple Threat Shoot"]     = _scale(tt_shoot_raw, 0.25, 0.75, 15, 55)

    # Triple Threat Pump Fake  — cap 55
    t["Drive Setup:Triple Threat Pump Fake"] = _scale(stats.fta, 1, 9, 10, 55)

    # Triple Threat Jab Step  — cap 55
    t["Drive Setup:Triple Threat Jab Step"]  = _scale(faceup_iso * 0.5, 0, 3.0, 5, 55)

    # Triple Threat Idle  — cap 65
    # usage_proxy zeros out post players unfairly. Post players do idle in the post;
    # add a post_freq bonus so high-post players get a moderate idle tendency.
    idle_raw = max(0.0, 0.5 - usage_proxy) + post_freq * 0.04
    t["Drive Setup:Triple Threat Idle"]      = _scale(idle_raw, 0, 0.45, 5, 65)

    # Setup With Sizeup  — cap 55
    t["Drive Setup:Setup With Sizeup"]       = _scale(faceup_iso * 0.3, 0, 2.0, 5, 55)

    # Setup With Hesitation  — cap 55
    t["Drive Setup:Setup With Hesitation"]   = _scale(faceup_iso * 0.2, 0, 1.5, 5, 55)

    # No Setup Dribble  — cap 85
    t["Drive Setup:No Setup Dribble"]        = _scale(
        1 - _pct(faceup_iso, 10), 0.3, 1.0, 5, 85)

    # ── PASSING ──────────────────────────────────────────────────────────

    # Dish To Open Man  — cap 65
    # AST_PCT is pace/usage-adjusted (better than raw AST for multi-era players).
    # Retain a reduced post_freq bonus: draw-and-kick passes often don't register as assists.
    dish_raw = stats.ast_pct * 15 + post_freq * 0.2
    t["Passing:Dish To Open Man"] = _scale(dish_raw, 0.3, 8.0, 10, 65)

    # Flashy Pass  — cap 60
    t["Passing:Flashy Pass"] = _scale(stats.ast, 1, 12, 5, 60)

    # Alley-Oop Pass  — cap 65
    t["Passing:Alley-Oop Pass"] = _scale(stats.ast * 0.15, 0, 2.5, 5, 65)

    # ── FREELANCE ────────────────────────────────────────────────────────

    # Roll vs Pop  — cap 85; 5=pure pop, 85=pure roll
    pr_total = stats.synergy_pr_roll + stats.synergy_pr_ball
    if pr_total > 0.5:
        roll_frac = stats.synergy_pr_roll / pr_total
    else:
        # Infer from shot-location distribution.
        # RA shots are the strongest roll signal: lob catches, roll-to-rim finishes,
        # and cut dunks all land in the restricted area. Close-paint shots are a mild
        # roll signal (post finishes also land here, so weight less).
        # 3PT shots are the strongest pop signal: only stretch bigs pop for threes.
        # Mid-range is a mild pop signal (face-up scorers, pull-up bigs).
        #
        # Post finishes (drop steps, hook-and-lays, face-up drives) land in RA but
        # are NOT roll-to-rim plays. Discount RA's roll signal proportionally to
        # post frequency: at post_freq≥4, RA contribution is cut by ~90%, so
        # post-first bigs (Bosh, Aldridge) read as pop screeners rather than rollers.
        # Pure roll men (low post_freq) retain the full RA signal.
        post_ra_discount = min(post_freq / 4.0, 0.90)
        roll_weight = pct_ra * 2.5 * (1.0 - post_ra_discount) + pct_close * 0.5
        pop_weight  = pct_3  * 2.5 + pct_mid  * 1.0
        roll_frac   = roll_weight / max(roll_weight + pop_weight, 0.01)
    t["Freelance:Roll vs. Pop"] = _scale(roll_frac, 0, 1, 5, 85)

    # Spot vs Cut  — cap 85; high = spots up, low = cuts
    spot_frac = _pct(stats.synergy_spotup,
                     stats.synergy_spotup + max(stats.synergy_cut, 0.1))
    t["Freelance:Spot vs. Cut"] = _scale(spot_frac, 0, 1, 5, 85)

    # ISO vs defender tiers — caps per CSV (Elite=50, Good=60, Average=70, Poor=75)
    # CSV: Primary/Elite Creator vs Poor = 55-70, vs Good = 35-55, vs Elite = 25-45.
    # high_raw = ~4 poss/game ≈ elite ISO usage ceiling (Kobe/KD territory → caps out).
    # Stagger multipliers so the scale yields correct relative ordering.
    # Use iso_score_freq (PnR-discounted) so pass-first guards don't read as ISO scorers.
    t["Freelance:Iso vs. Elite Defender"]   = _scale(iso_score_freq * 0.50, 0, 2.5, 3, 50)  # cap 50
    t["Freelance:Iso vs. Good Defender"]    = _scale(iso_score_freq * 0.75, 0, 3.5, 5, 60)  # cap 60
    t["Freelance:Iso vs. Average Defender"] = _scale(iso_score_freq * 0.90, 0, 4.0, 5, 70)  # cap 70
    t["Freelance:Iso vs. Poor Defender"]    = _scale(iso_score_freq,        0, 4.0, 5, 75)  # cap 75

    # Play Discipline  — cap 90
    # Self-creation rate (primary) + usage rate (secondary).
    # Both measure "takes matters into own hands" vs. "finishes designed plays."
    # TOV rate alone is ball security, not play adherence — replaced.
    unassisted_pct = stats.unassisted_fgm / max(stats.fgm, 1.0)
    # USG_PCT: 0.15=role player, 0.20=avg, 0.30=star, 0.35+=primary engine
    usg_normalized = min(1.0, max(0.0, (stats.usg_pct - 0.10) / 0.25))
    freelance_index = unassisted_pct * 0.65 + usg_normalized * 0.35
    t["Freelance:Play Discipline"] = _scale(1.0 - freelance_index, 0.30, 0.87, 20, 90)

    # Shot  — cap 75
    # CSV tiers: 0-5 Non-Scoring, 10-15 Bailout, 20-25 Low-Usage, 30-35 Connector,
    #            40-45 Featured Role Scorer, 50-55 High-Volume Option,
    #            60-65 Primary Scoring Option, 70 Elite Scoring Engine, 75 Max Superstar.
    # FGA (60%) + PPG (40%): FGA drives shot-selection willingness; PPG anchors scoring role.
    # A player shooting 18 FGA at low efficiency reads as high-volume, not a connector.
    # ast_ratio discount: pass-first guards hold the ball far more than they shoot;
    # floor 0.60 so extreme PGs (Rondo, Nash) still retain 60% weight.
    # Rondo (~10 PPG, 10 FGA, ast_ratio=0.53) → 24 (Low-Usage). Dirk (23, 17, 0.14) → 61 (Primary).
    _shot_raw = stats.fga * 0.6 + stats.pts * 0.4
    _shot_adj = _shot_raw * max(0.60, 1.0 - ast_ratio)
    t["Freelance:Shot"] = _scale(_shot_adj, 2, 21, 10, 75)

    # Touches  — cap 75
    # CSV: NBA Norm 35-45, Featured 45-55, Primary/Hub 60-70, Max Hub 75.
    # FGA measures possession-ending involvement directly, independent of shooting efficiency.
    # pts would reward efficient scorers over high-usage ones — wrong for a touch/involvement signal.
    # USG_PCT is the cleanest proxy: it's already a possession-share (FGA+0.44×FTA+TOV / team_poss),
    # pace/era-normalized, and directly measures how often the player ends possessions.
    # FGA-based formulas conflated playmaking assists with scoring involvement — high-APG distributors
    # (Kidd 8.7 APG, ~14% USG) inflated to the same range as primary scorers (Dirk ~31% USG).
    # Scale: 10%=barely in offense (10), 20%=avg NBA (36), 25%=featured (49), 31%=hub (65), 35%=max (75).
    # Dirk 2010-11 (USG 0.314) → 65 (Primary Hub). LeBron/Westbrook → 75.
    # Kidd 2010-11 (USG ~0.135) → 19 pre-norm; after roster normalize → ~28 (Low-Touch Role). ✓
    t["Freelance:Touches"] = _scale(stats.usg_pct, 0.10, 0.35, 10, 75)

    # Transition Spot Up
    # synergy_transition is always 0 (defunct endpoint). PCT_PTS_FB is the only available
    # proxy for transition involvement; high fast-break scoring → spots up in transition.
    t["Freelance:Transition Spot Up"] = _scale(stats.pct_pts_fb, 0, 0.25, 5, 55)

    # ── POST GAME ─────────────────────────────────────────────────────────

    # Post Up  — cap 85
    # CSV: Featured/Primary 50-65, Star Post Hub 70-80, Extreme 85.
    # 8 poss/game ≈ primary post engine ceiling; 5.5 (Dirk) → ~60 (Primary Post Option).
    t["Post Game:Post Up"] = _scale(post_freq, 0, 8, 5, 85)

    # Post orientation signal: fadeaway → face-up player; hook → back-to-basket player.
    # face_up_pct = 1.0 means pure face-up scorer (Dirk); 0.0 means pure back-to-basket (hook-only center).
    # Neutral (0.5) when no post shot data exists. Used to differentiate Back Down vs. Face Up.
    _post_shot_vol = stats.fga_fadeaway + stats.fga_hook
    face_up_pct = _pct(stats.fga_fadeaway, _post_shot_vol) if _post_shot_vol > 0.05 else 0.5
    _post_back_pct = 1.0 - face_up_pct * 0.6  # dampens back-down for face-up players

    # Post Back Down  — cap 80
    # Back-to-basket orientation × post volume. Face-up scorers get lower Back Down.
    t["Post Game:Post Back Down"]           = _scale(post_freq * _post_back_pct, 0, 8, 5, 80)
    # Post Aggressive Backdown  — cap 70
    # More forceful subset. Naturally stays 10-20 pts below Back Down via slower scale (high_raw=12).
    t["Post Game:Post Aggressive Backdown"] = _scale(post_freq * _post_back_pct, 0, 12, 5, 70)
    # Post Face Up  — cap 60
    # Face-up orientation × post volume. HIGH for Dirk/Durant-type face-up scorers;
    # LOW for hook-shot bigs. These two tendencies now diverge correctly per guide.
    t["Post Game:Post Face Up"]             = _scale(post_freq * face_up_pct, 0, 6, 5, 60)
    # Post Spin  — cap 55
    # CSV: Regular 30-35, Advanced 35-45, Signature 50. Keep high_raw=12 so non-spinners stay low.
    t["Post Game:Post Spin"]                = _scale(post_freq, 0, 12, 5, 55)
    # Post Drive  — cap 55
    # CSV: Face-Up Driver 30-45, Primary Post-Drive 50.
    t["Post Game:Post Drive"]               = _scale(post_freq, 0, 11, 5, 55)
    # Post Drop Step  — cap 60
    # CSV: Power Big 35-45, Elite Drop-Step 50-55.
    t["Post Game:Post Drop Step"]           = _scale(post_freq, 0, 10, 5, 60)

    # Shoot From Post  — cap 75
    # CSV: Scoring-Oriented 40-55, Primary/Elite Post Scorer 60-70.
    # Guide: "Shoot From Post chooses shot vs pass, hold, reset, or exit" — not just post volume.
    # high_raw=3.5: (fadeaway+hook)×0.5 + post_freq×0.3; 3.5 = elite shot-first post player.
    # Was 4 — too loose; Dirk (2.74 raw) scored 53 and held/bailed in 2K instead of shooting.
    # 3.5 puts Dirk at 60, matching Post Up and triggering the AI shoot decision on-catch.
    #
    # Passmaking discount: post players who frequently pass out (high AST) select
    # the shot action less often — guide: "Jokic hub vs Embiid shot-first post scorer."
    # Threshold at AST > 4: below that, assists mostly come from drive kick-outs / transition,
    # not post-exit reads — so Dirk (2.7 AST) and Embiid (3 AST) are unaffected.
    # Jokic (9 AST) → 20% discount; LeBron (8 AST, when posting) → 16% discount.
    # Only fires when player actually posts (post_freq > 1).
    _post_pass_discount = min(0.35, max(0.0, stats.ast - 4.0) * 0.04) if post_freq > 1.0 else 0.0
    shoot_post_raw = ((stats.fga_fadeaway + stats.fga_hook) * 0.5 + post_freq * 0.3) * (1 - _post_pass_discount)
    t["Post Game:Shoot From Post"] = _scale(shoot_post_raw, 0, 3.5, 5, 75)

    # Hook left/right  — cap 50
    # Guide: "normally only one direction exceeds 40, with the weaker side 10-20 pts lower."
    # Dominant side uses full hook volume; weak side is dominant minus 15 (floored at 5).
    # Convention: right = dominant (most players are right-handed). Flip manually for lefties.
    # No shot-chart directional data available for post moves — verify vs. film/handedness.
    _hook_dom  = _scale(stats.fga_hook, 0, 3.0, 5, 50)
    _hook_weak = max(5, _hook_dom - 15)
    t["Post Game:Post Hook Right"] = _hook_dom
    t["Post Game:Post Hook Left"]  = _hook_weak

    # Fade left/right  — cap 50
    # fga_fadeaway (all fadeaways) covers both turnaround and face-up post fades.
    # Using fga_turnaround_fadeaway alone missed face-up faders like Dirk (1.4 face-up fades/game).
    # Same directional convention as hooks: right = dominant by default.
    # Flip manually for left-hand-dominant fade specialists (e.g., left-handed players).
    _fade_dom  = _scale(stats.fga_fadeaway, 0, 4.0, 5, 50)
    _fade_weak = max(5, _fade_dom - 15)
    t["Post Game:Post Fade Right"] = _fade_dom
    t["Post Game:Post Fade Left"]  = _fade_weak

    # Post move sub-types
    # Shimmy: straight-up turnaround jumpers (fga_turnaround minus the fadeaway subset).
    # Player pivots, fakes with the shoulder, shoots straight up — distinct from fade (which drifts).
    # Non-fadeaway turnarounds are the clearest API proxy for this move.
    # high_raw=1.5: elite shimmy user ceiling; 0.5/game → ~20 (occasional), 1.5/game → 45 (signature).
    _shimmy_raw = max(0.0, stats.fga_turnaround - stats.fga_turnaround_fadeaway)
    t["Post Game:Post Shimmy Shot"]    = _scale(_shimmy_raw, 0, 1.5, 5, 45)
    t["Post Game:Post Hop Shot"]       = 5   # cap 45 — no API proxy; film evidence required
    # Post Step Back: raw fga_step_back volume (per-game). pct_stepback × post_freq underscaled
    # because the percentage is tiny (~3%) even for active step-back users.
    # 0.5/game → ~20 (regular move), 1.5/game → 50 (signature).
    t["Post Game:Post Step Back Shot"] = _scale(stats.fga_step_back, 0, 1.5, 5, 50)  # cap 50
    t["Post Game:Post Up And Under"]   = 5   # cap 45 — no API proxy; film evidence required

    # ── DEFENSE ──────────────────────────────────────────────────────────

    # Pass Interception  — cap 85
    # Guide: "off-ball lane, bad-pass and dig attempts." STL is the primary proxy;
    # most stolen balls in-game are passing-lane reads for typical NBA players.
    t["Defense:Pass Interception"] = _scale(stats.stl, 0.2, 2.5, 20, 85)

    # On-Ball Steal  — cap 85
    # Guide: "direct reach, strip, swipe and ball-pressure attempts" — distinct from lane reads.
    # Without deflection/POA data, use PF/STL ratio as a style proxy:
    # High PF relative to STL → on-ball defender (fouls from pressure = more strip attempts).
    # Low PF + high STL → lane lurker (steals without contact = mostly interceptions).
    # Pivot at PF/STL ≈ 2 (typical NBA player); range 0.75–1.15.
    _foul_stl_ratio = _pct(stats.pf, max(stats.stl, 0.1))
    _onball_mod = min(1.15, max(0.75, _foul_stl_ratio / 2.0))
    t["Defense:On-Ball Steal"] = _scale(stats.stl * _onball_mod, 0.2, 2.5, 10, 85)

    # Block Shot  — cap 85
    t["Defense:Block Shot"] = _scale(stats.blk, 0.1, 3.0, 10, 85)

    # Contest Shot  — cap 85
    t["Defense:Contest Shot"] = _scale((stats.blk + stats.stl) / 2, 0.2, 2.5, 25, 85)

    # Take Charge  — cap 35
    t["Defense:Take Charge"] = _scale(stats.stl, 0.5, 3.0, 5, 35)

    # Foul  — cap 95
    t["Defense:Foul"] = _scale(stats.pf, 0.5, 5.0, 15, 95)

    # Hard Foul  — cap 40 (guide cap; PF is the only available proxy though guide says NOT to use
    # general physicality — acknowledged data gap; PF still the most correlated available stat)
    t["Defense:Hard Foul"] = _scale(stats.pf, 1.0, 5.0, 5, 40)

    return t


def to_2k26_json(tendencies: dict) -> dict:
    """Wrap tendencies dict in the 2K26 output format."""
    output = {
        "_version": "2K26",
        "_format": "label_based",
        "tendencies": {},
    }
    for label, value in tendencies.items():
        group = label.split(":")[0] if ":" in label else label
        output["tendencies"][label] = {
            "value": int(value),
            "type": "bitfield",
            "group": group,
            "length": None,
            "dynamic_dropdown": None,
        }
    return output
