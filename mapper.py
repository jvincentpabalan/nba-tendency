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
    # Prefer box-score fg3a for the 3PT numerator — more reliable than zone sum for old seasons
    three_fga = stats.total_3pt_fga if stats.total_3pt_fga > 0 else stats.fg3a
    pct_3          = _pct(three_fga,   fga)
    pct_stepback   = _pct(stats.fga_step_back,   fga)
    pct_turnaround = _pct(stats.fga_turnaround,  fga)
    iso_freq  = stats.synergy_iso
    post_freq = stats.synergy_post
    # Face-up ISO: remove post-up overlap to avoid inflating dribble moves
    faceup_iso = max(0.0, iso_freq - post_freq * 0.3)

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

    # Pre-2013 discount for spot-up mid: the 3PT-anchored synergy_spotup proxy
    # over-estimates mid-range spot-ups for ISO players whose mid-range is self-created.
    # assisted_rate (AssitedShotPlayerDashboard) ≈ C&S fraction of FGM; multiplying by it
    # prevents inflating Spot Up Mid / Spot Up Drive for players like Melo or Kobe.
    # For 2013+, catch_shoot_fga is the real measured value — no adjustment needed.
    _fgm_tracked = stats.assisted_fgm + stats.unassisted_fgm
    _spot_up_mid_scale = (
        stats.assisted_fgm / _fgm_tracked
        if stats.catch_shoot_fga == 0 and _fgm_tracked > 0
        else 1.0
    )

    t["Jump Shooting:Spot Up Shot Mid-Range"]    = _scale(cs_approx * cs_mid_frac * _spot_up_mid_scale, 0, 3.0, 5, 55)  # cap 55
    t["Jump Shooting:Off Screen Shot Mid-Range"] = _scale(stats.synergy_offscreen * cs_mid_frac, 0, 1.5, 5, 50)  # cap 50
    t["Jump Shooting:Spot Up Shot Three"]        = _scale(cs_approx * cs_3_frac, 0, 3.0, 5, 75)   # cap 75
    t["Jump Shooting:Off Screen Shot Three"]     = _scale(stats.synergy_offscreen * cs_3_frac, 0, 1.5, 5, 65)  # cap 65

    # ── Contested jumpers — cap 55 ────────────────────────────────────────
    t["Jump Shooting:Contested Jumper Mid-Range"] = _scale(pct_mid, 0.05, 0.55, 5, 55)
    t["Jump Shooting:Contested Jumper Three"]     = _scale(pct_3,  0.02, 0.40, 5, 55)

    # ── Stepback jumpers — cap 55 / 60 ───────────────────────────────────
    t["Jump Shooting:Stepback Jumper Mid-Range"] = _scale(pct_stepback, 0, 0.05, 5, 55)
    t["Jump Shooting:Stepback Jumper Three"]     = _scale(pct_stepback * pct_3, 0, 0.02, 5, 60)

    # Spin Jumper  — cap 45; self-created perimeter spin into jumper only.
    # Exclude post/fadeaway turnarounds: strip fadeaway overlap and post-frequency contribution.
    # A pure post player (high fadeaway, high post_freq) nets near zero here.
    spin_jump_raw = max(0.0, stats.fga_turnaround - stats.fga_fadeaway * 0.4 - post_freq * 0.15)
    t["Jump Shooting:Spin Jumper"] = _scale(spin_jump_raw, 0, 0.5, 5, 45)

    # Transition Pull-Up Three  — cap 45
    t["Jump Shooting:Transition Pull Up Three"] = _scale(
        stats.synergy_transition * pct_3, 0, 1.0, 5, 45)

    # Drive Pull Up Mid-Range  — cap 70
    # pullup_2pt_fga from player tracking (2013-14+ only).
    # Pre-2013: many pull-up mid-range shots are labeled generic "Jump Shot" (not "Pullup Jump Shot").
    # fga_uast_2pt_jump captures that hidden bucket via FG2A × PCT_UAST_2PM from the "Jump Shot" row.
    # Adding it to the labeled pullups gives a complete picture of dribble-created 2PT attempts.
    if stats.pullup_2pt_fga > 0:
        pu2 = stats.pullup_2pt_fga
    else:
        pu2 = stats.fga_pullup * (1 - pct_3) + stats.fga_uast_2pt_jump

    pu3 = stats.pullup_3pt_fga or (stats.fga_pullup * pct_3)
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
    t["Jump Shooting:Step Through Shot"] = _scale(post_freq, 0, 8, 5, 50)

    # ── LAYUPS AND DUNKS ─────────────────────────────────────────────────

    # Driving Layup  — cap 80
    pct_driv_layup = _pct(stats.fga_driving_layup + stats.fga_finger_roll, fga)
    t["Layups And Dunks:Driving Layup"] = _scale(pct_driv_layup, 0, 0.25, 5, 80)

    # Standing Dunk  — cap 85
    standing_dunk = max(0.0, stats.fga_dunk - stats.fga_driving_dunk)
    t["Layups And Dunks:Standing Dunk"] = _scale(_pct(standing_dunk, fga), 0, 0.10, 5, 85)

    # Driving Dunk  — cap 80
    t["Layups And Dunks:Driving Dunk"] = _scale(_pct(stats.fga_driving_dunk, fga), 0, 0.08, 5, 80)

    # Flashy Dunk  — cap 70
    t["Layups And Dunks:Flashy Dunk"] = _scale(_pct(stats.fga_driving_dunk, fga), 0, 0.08, 5, 70)

    # Alley-Oop  — cap 85
    t["Layups And Dunks:Alley-Oop"] = _scale(_pct(stats.fga_alley_oop, fga), 0, 0.05, 5, 85)

    # Putback  — cap 70
    off_reb = stats.synergy_off_reb or stats.oreb
    t["Layups And Dunks:Putback"] = _scale(off_reb, 0, 3.5, 5, 70)

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
    t["Layups And Dunks:Euro Step Layup"] = _scale(_pct(stats.fga_euro_step, fga), 0, 0.06, 5, 75)

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
    t["Driving:Off Screen Drive"] = _scale(stats.synergy_offscreen * 0.4, 0, 0.6, 5, 60)

    # Drive Right  — neutral 50 (no directional drive data from API)
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
    # Measures straight-line continuation vs. adding a dribble move on attack.
    # When total drive volume >= 1.0/game: ratio of driving layups vs. fancy finishes (euro/floater).
    # When < 1.0/game: shot-type ratio is unreliable (max-floor distorts it for rare drivers like
    # late-career Kidd). Estimate from ISO profile instead — high faceup_iso = move-creative
    # even when driving infrequently; low ISO = defaults to straight line.
    total_drive_atts = stats.fga_driving_layup + stats.fga_euro_step + stats.fga_floater
    if total_drive_atts >= 1.0:
        straight_drive_pct = _pct(stats.fga_driving_layup, total_drive_atts)
    else:
        # Low-volume driver: infer tendency from ISO creativity profile
        # Baseline 0.85 (straight-line) minus ISO penalty (up to 0.56 for elite movers)
        straight_drive_pct = max(0.35, 0.85 - min(faceup_iso, 8) * 0.07)
    t["Driving:No Driving Dribble Move"] = _scale(straight_drive_pct, 0.20, 0.90, 10, 90)

    # Attack Strong On Drive  — cap 90
    # CSV: "controls willingness to CONTINUE the downhill attack toward the basket once
    # a drive has begun, instead of stopping for an early pull-up or reset."
    # This is drive COMMITMENT, not FTA rate. Proxy: rim finishes vs pull-up stops.
    rim_finish_vol = stats.fga_driving_layup + stats.fga_driving_dunk + stats.fga_euro_step + stats.fga_floater
    # pullup_2pt_fga = player tracking (2013-14+); fga_pullup = shot-type detail (all seasons,
    # includes "Driving Jump shot" — mid-range pull-ups off a drive that stop short of the rim).
    pullup_vol = stats.pullup_2pt_fga or stats.fga_pullup
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
    # Raw AST underestimates post players who draw help and kick out.
    # Add post_freq bonus to account for draw-and-kick behavior.
    dish_raw = stats.ast + post_freq * 0.4
    t["Passing:Dish To Open Man"] = _scale(dish_raw, 0.5, 14, 10, 65)

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
        # Infer: high 3PT profile + high post = pop tendency
        roll_frac = max(0.0, 1.0 - pct_3 / 0.25 - post_freq / 10) * 0.6
    t["Freelance:Roll vs. Pop"] = _scale(roll_frac, 0, 1, 5, 85)

    # Spot vs Cut  — cap 85; high = spots up, low = cuts
    spot_frac = _pct(stats.synergy_spotup,
                     stats.synergy_spotup + max(stats.synergy_cut, 0.1))
    t["Freelance:Spot vs. Cut"] = _scale(spot_frac, 0, 1, 5, 85)

    # ISO vs defender tiers — caps per CSV (Elite=50, Good=60, Average=70, Poor=75)
    # Ordering: Poor > Average > Good > Elite (attack weaker defenders more freely).
    # Stagger multipliers and high_raw so the scale yields correct relative ordering.
    t["Freelance:Iso vs. Elite Defender"]   = _scale(iso_freq * 0.50, 0,  7, 3, 50)  # cap 50
    t["Freelance:Iso vs. Good Defender"]    = _scale(iso_freq * 0.75, 0,  9, 5, 60)  # cap 60
    t["Freelance:Iso vs. Average Defender"] = _scale(iso_freq * 0.90, 0,  9, 5, 70)  # cap 70
    t["Freelance:Iso vs. Poor Defender"]    = _scale(iso_freq,        0,  8, 5, 75)  # cap 75

    # Play Discipline  — cap 90
    # Recalibrated anchors: NBA norm TOV rate ~12-20%; disciplined players rarely exceed 15%.
    tov_rate = _pct(stats.tov, stats.fga + stats.ast + stats.tov)
    t["Freelance:Play Discipline"] = _scale(1 - tov_rate, 0.75, 0.97, 20, 90)

    # Shot  — cap 75
    t["Freelance:Shot"] = _scale(stats.fga, 5, 25, 15, 75)

    # Touches  — cap 75
    t["Freelance:Touches"] = _scale(stats.pts + stats.ast, 5, 45, 20, 75)

    # Transition Spot Up
    t["Freelance:Transition Spot Up"] = _scale(
        stats.synergy_transition * pct_3, 0, 1.5, 5, 55)

    # ── POST GAME ─────────────────────────────────────────────────────────

    # Post Up  — cap 85
    t["Post Game:Post Up"] = _scale(post_freq, 0, 10, 5, 85)

    # Post Back Down  — cap 80
    t["Post Game:Post Back Down"]           = _scale(post_freq, 0, 11, 5, 80)
    # Post Aggressive Backdown  — cap 70
    t["Post Game:Post Aggressive Backdown"] = _scale(post_freq, 0, 12, 5, 70)
    # Post Face Up  — cap 60
    t["Post Game:Post Face Up"]             = _scale(post_freq, 0, 10, 5, 60)
    # Post Spin  — cap 55
    t["Post Game:Post Spin"]                = _scale(post_freq, 0, 12, 5, 55)
    # Post Drive  — cap 55
    t["Post Game:Post Drive"]               = _scale(post_freq, 0, 14, 5, 55)
    # Post Drop Step  — cap 60
    t["Post Game:Post Drop Step"]           = _scale(post_freq, 0, 12, 5, 60)

    # Shoot From Post  — cap 75
    shoot_post_raw = (stats.fga_fadeaway + stats.fga_hook) * 0.5 + post_freq * 0.3
    t["Post Game:Shoot From Post"] = _scale(shoot_post_raw, 0, 5, 5, 75)

    # Hook left/right  — cap 50
    hook_per_side = stats.fga_hook / 2
    t["Post Game:Post Hook Left"]  = _scale(hook_per_side, 0, 1.5, 5, 50)
    t["Post Game:Post Hook Right"] = _scale(hook_per_side, 0, 1.5, 5, 50)

    # Fade left/right  — cap 50
    fade_per_side = stats.fga_fadeaway / 2
    t["Post Game:Post Fade Left"]  = _scale(fade_per_side, 0, 2.0, 5, 50)
    t["Post Game:Post Fade Right"] = _scale(fade_per_side, 0, 2.0, 5, 50)

    # Post move sub-types
    t["Post Game:Post Shimmy Shot"]    = _scale(post_freq, 0, 14, 5, 45)   # cap 45
    t["Post Game:Post Hop Shot"]       = _scale(post_freq, 0, 14, 5, 45)   # cap 45
    t["Post Game:Post Step Back Shot"] = _scale(pct_stepback * post_freq, 0, 0.8, 5, 50)  # cap 50
    t["Post Game:Post Up And Under"]   = _scale(post_freq, 0, 16, 5, 45)   # cap 45

    # ── DEFENSE ──────────────────────────────────────────────────────────

    # Pass Interception  — cap 85
    t["Defense:Pass Interception"] = _scale(stats.stl, 0.2, 2.5, 20, 85)

    # On-Ball Steal  — cap 85
    t["Defense:On-Ball Steal"] = _scale(stats.stl, 0.2, 2.5, 15, 85)

    # Block Shot  — cap 85
    t["Defense:Block Shot"] = _scale(stats.blk, 0.1, 3.0, 10, 85)

    # Contest Shot  — cap 85
    t["Defense:Contest Shot"] = _scale((stats.blk + stats.stl) / 2, 0.2, 2.5, 25, 85)

    # Take Charge  — cap 35
    t["Defense:Take Charge"] = _scale(stats.stl, 0.5, 3.0, 5, 35)

    # Foul  — cap 95
    t["Defense:Foul"] = _scale(stats.pf, 0.5, 5.0, 15, 95)

    # Hard Foul  — cap 45
    t["Defense:Hard Foul"] = _scale(stats.pf, 1.0, 5.0, 5, 45)

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
