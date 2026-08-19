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

def compute(stats: PlayerStats, trace: list[str] | None = None) -> dict:
    """Return a flat dict of tendency_label → value.

    trace: list of short tendency names (e.g. ["Shot Three", "Post Hook Right"]).
           When provided, prints intermediate formula values for those tendencies.
    """
    _trace = {k.lower() for k in (trace or [])}

    def _emit(label: str, **vals):
        """Print intermediate formula values when tracing a tendency."""
        if not _trace:
            return
        short = label.split(":", 1)[-1].lower() if ":" in label else label.lower()
        if short in _trace:
            print(f"\n  [trace] {label}")
            for k, v in vals.items():
                print(f"    {k} = {v}")

    t = {}
    # Use box-score FGA as primary denominator — zone-derived total_fga can be
    # undercounted for older seasons if some zones return 0 (inflates pct_3 to ~1.0).
    fga = stats.fga if stats.fga > 0 else max(stats.total_fga, 1.0)

    pct_ra         = _pct(stats.fga_restricted,  fga)
    pct_close      = _pct(stats.fga_paint_nonra, fga)
    pct_mid        = _pct(stats.fga_mid,         fga)
    # fg3a from general splits is authoritative. Zone data can both undercount (shots
    # fall outside categorized zones) AND overcount (miscategorized near-3PT mid-range
    # shots). Use fg3a as primary; fall back to zone sum only when fg3a is unavailable.
    three_fga = stats.fg3a if stats.fg3a > 0 else stats.total_3pt_fga
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
    # high_raw=0.55: average wing (24% RA) → ~40 (within norm 20-45);
    # elite rim-runners (55-60% RA) hit cap. 0.45 was too tight — mapped
    # average wings to 48+ (above norm).
    t["Jump Shooting:Shot Under Basket"] = _scale(pct_ra, 0, 0.55, 5, 85)

    # Shot Close  — cap 60
    t["Jump Shooting:Shot Close"] = _scale(pct_close, 0, 0.35, 5, 60)

    # Shot Mid-Range  — cap 45
    t["Jump Shooting:Shot Mid-Range"] = _scale(pct_mid, 0, 0.60, 5, 45)

    # Shot Three  — cap 75
    # Two-factor intent discount — both reduce "would shoot a three" frequency:
    # (1) Rim-attacker (rim_vol): drive-first players accumulate threes situationally
    #     when the defense concedes them, not by actively seeking the arc.
    #     Rose (rim_vol≈34%) → ~17% discount; Allen (rim_vol≈10%) → ~5% discount.
    # (2) Distributor (_pass_discount): pass-first players scan for kickout reads
    #     rather than pulling the trigger. Kidd (ast_ratio≈0.75) → ~18% discount;
    #     scorers (Kobe, ast_ratio≈0.30) → no discount.
    _rim_vol    = stats.fga_restricted / max(fga, 1.0)
    _ast_ratio  = stats.ast / max(stats.ast + stats.fgm, 0.01)
    _pass_discount = max(0.0, (_ast_ratio - 0.40) * 0.5)
    _three_intent = pct_3 * (1.0 - _rim_vol * 0.5) * (1.0 - _pass_discount)
    _emit("Jump Shooting:Shot Three",
          pct_3=f"{pct_3:.3f}", fg3a=f"{stats.fg3a:.2f}", fga=f"{fga:.2f}",
          rim_vol=f"{_rim_vol:.3f}", rim_discount=f"{_rim_vol*0.5:.3f}",
          ast_ratio=f"{_ast_ratio:.3f}", pass_discount=f"{_pass_discount:.3f}",
          three_intent=f"{_three_intent:.3f}",
          result=_scale(_three_intent, 0, 0.50, 5, 75))
    t["Jump Shooting:Shot Three"] = _scale(_three_intent, 0, 0.50, 5, 75)

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
    # Pre-2013: synergy_spotup proxy uses pct_uast_3pm to filter pull-ups, but high-volume
    # C&S shooters (Deng 2010-11: 4.04 3PA/game, 97% catch-and-shoot) were capping at 75
    # despite not being true specialists. Raise high_raw to 8.0 so only Ray Allen / Korver
    # level volume (7+ C&S 3PA/game equivalent) reaches the cap; Deng-type players land ~45.
    _spot_3_hrw = 3.0 if stats.catch_shoot_fga > 0 else 8.0
    _emit("Jump Shooting:Spot Up Shot Three",
          catch_shoot_fga=f"{stats.catch_shoot_fga:.2f}",
          synergy_spotup=f"{stats.synergy_spotup:.3f}", cs_3_frac=f"{cs_3_frac:.3f}",
          spot_3_vol=f"{_spot_3_vol:.3f}", high_raw=_spot_3_hrw,
          result=_scale(_spot_3_vol, 0, _spot_3_hrw, 5, 75))
    t["Jump Shooting:Spot Up Shot Three"]        = _scale(_spot_3_vol, 0, _spot_3_hrw, 5, 75)   # cap 75
    # high_raw raised to 2.5 (was 1.5): the pre-2013 synergy_offscreen proxy (assisted 3PT makes
    # × 0.30 / 0.55) inflates for high-volume 3PT shooters who catch and shoot but don't
    # actually run many off-screen actions. A true curl/flare specialist hits cap at ~2.5;
    # ball-handlers and spot-up players land in Selective (20-35) range.
    t["Jump Shooting:Off Screen Shot Three"]     = _scale(stats.synergy_offscreen * cs_3_frac, 0, 2.5, 5, 65)  # cap 65

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

    # Dunk distribution: estimate how many of a player's dunks are driving vs. standing.
    # Pre-2013: ShotTypePlayerDashboard detail ("Driving Dunk"/"Driving Slam Dunk") is sparse;
    # some driving dunks appear only in the ShotTypeSummary "Dunk" total. For perimeter players
    # (low post_freq), almost all dunks are off drives — use fga_dunk as a floor, discounted
    # proportionally to post orientation so post bigs aren't over-credited with driving dunks.
    _post_dunk_frac = min(0.65, post_freq / 8.0)  # 0 for guards, 0.65 for heavy post bigs
    _driving_dunk_est = max(stats.fga_driving_dunk, stats.fga_dunk * (1.0 - _post_dunk_frac))

    # Standing Dunk  — cap 85
    # Definition: selection weight of dunk vs. layup at the rim (stationary/catch/oreb).
    # Uses _driving_dunk_est so standing dunk isn't inflated when driving dunk detail is sparse.
    standing_dunk = max(0.0, stats.fga_dunk - _driving_dunk_est)
    standing_layup = max(0.0, stats.fga_layup - stats.fga_driving_layup)
    dunk_pref = standing_dunk / max(standing_dunk + standing_layup, 0.01)
    t["Layups And Dunks:Standing Dunk"] = _scale(dunk_pref, 0, 1.0, 5, 85)

    # Driving Dunk  — cap 80
    t["Layups And Dunks:Driving Dunk"] = _scale(_pct(_driving_dunk_est, fga), 0, 0.15, 5, 80)

    # Flashy Dunk  — cap 70
    # Sub-selection preference after choosing to dunk (flashy vs. safe animation).
    # Proxy: driving dunk rate × drive-preference ratio (driving dunks / all dunks).
    # Uses _driving_dunk_est so pre-2013 data gaps don't suppress athletic slashers.
    # high_raw lowered to 0.05 (was 0.08): elite in-traffic dunkers approach cap sooner.
    _driving_dunk_pref = _pct(_driving_dunk_est, max(stats.fga_dunk, 0.01))
    t["Layups And Dunks:Flashy Dunk"] = _scale(_pct(_driving_dunk_est, fga) * _driving_dunk_pref, 0, 0.05, 5, 70)

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
    # Proxy: faceup_iso (drive-first identity). Drive-first players attack from any catch
    # position including spot-up; C&S specialists rarely convert a spot-up to a drive.
    # The old formula used cs_mid_frac × assisted_rate, which penalised unassisted
    # creators (exactly who drives out of spot-ups) and was wrong for guards like Rose.
    t["Driving:Spot Up Drive"] = _scale(faceup_iso, 0, 11, 5, 70)

    # Off-Screen Drive  — cap 60
    # Most off-screen reads are shot-first; 0.25 replaces 0.4 (was over-counting drive converts)
    t["Driving:Off Screen Drive"] = _scale(stats.synergy_offscreen * 0.25, 0, 0.6, 5, 60)

    # Drive Right  — cap 95; scale: 5-25 extreme left, 45 mild left, 50 balanced, 55 mild right, 75-95 extreme right.
    # Guide: "50 means evidence-backed balance, not unknown or missing research."
    # "For meaningful drivers (Drive 30+), unresolved direction must not be finalized as 50."
    # No directional drive data available from NBA.com API — set to 50 as a placeholder.
    # MUST be researched via tracking data, film, or scouting before finalizing any Drive ≥ 30 player.
    t["Driving:Drive Right"] = 50

    # Driving dribble moves — caps per CSV.
    # Design constraint: for an elite attacker (Rose-level, faceup_iso ≈ 14), at most
    # 2-3 moves should reach 40+; the rest should land around 15-20. The old high_raws
    # were too tight — every move capped for any high-ISO player, making all attackers
    # look like they use every move equally.
    #
    # Primary moves (Crossover, Hesitation): calibrated so elite ISO (≈14) caps,
    #   moderate ISO (≈7, LeBron-level) lands 40-50.
    # Secondary move (Spin): elite ISO ≈42 (3rd move for best handles), moderate ≈27.
    # Tertiary moves (Half Spin, Double Crossover, BtB, In And Out): wide high_raws
    #   so even Rose lands ≈15-20 — not signature moves for most players.
    t["Driving:Driving Crossover"]          = _scale(faceup_iso,        0, 10,  5, 60)  # cap 60; primary
    t["Driving:Driving Spin"]               = _scale(faceup_iso * 0.3,  0, 5.0, 5, 50)  # cap 50; secondary — Rose≈42
    t["Driving:Driving Step Back"]          = _scale(pct_stepback, 0, 0.06, 5, 55)      # cap 55 (unchanged)
    t["Driving:Driving Half Spin"]          = _scale(faceup_iso * 0.2,  0, 7.5, 5, 45)  # cap 45; tertiary — Rose≈20
    t["Driving:Driving Double Crossover"]   = _scale(faceup_iso * 0.15, 0, 6.0, 5, 40)  # cap 40; tertiary — Rose≈17
    t["Driving:Driving Behind The Back"]    = _scale(faceup_iso * 0.15, 0, 8.0, 5, 50)  # cap 50; tertiary — Rose≈17
    t["Driving:Driving Dribble Hesitation"] = _scale(faceup_iso * 0.25, 0, 2.8, 5, 65)  # cap 65; primary — sits alongside crossover
    t["Driving:Driving In And Out"]         = _scale(faceup_iso * 0.15, 0, 10.0, 5, 65)  # cap 65; tertiary — Rose≈18

    # No Driving Dribble Move  — cap 90
    # Definition: frequency that player attacks straight-line without adding a mid-drive
    # counter (spin, crossover, hesitation). Must be INVERSELY related to individual dribble
    # move tendencies — if Crossover/Hesitation are high, this must be low.
    #
    # Previous approach blended shot-type finishing ratio (straight layup vs. euro/floater)
    # with faceup_iso. Problem: a player can use a crossover mid-drive and still finish with
    # a straight layup — finishing type is the wrong proxy for mid-drive move usage.
    # The floored iso_pct (min 0.29) also prevented elite ISO players from going below ~55.
    #
    # Pure faceup_iso inverse: the only available signal that directly measures "how often
    # does this player create via dribble moves." High ISO = frequently adds moves = low No Move.
    # Calibrated so faceup_iso ≈ 0 → 90 (cap, drives straight always);
    #              faceup_iso ≈ 10 → 10 (out_low, almost always adds a move).
    no_move_raw = max(0.0, 1.0 - faceup_iso / 10.0)
    t["Driving:No Driving Dribble Move"] = _scale(no_move_raw, 0, 1.0, 10, 90)

    # Dribble-move suppression: when No Driving Dribble Move is high (≥70), the player
    # almost never adds a counter move mid-drive. Cap all individual move tendencies at 5
    # so the game doesn't trigger animations that never happened in real life (e.g. Dirk
    # doing a behind-the-back crossover). Threshold 70 matches faceup_iso ≈ 3 or below —
    # players who are clearly straight-line drivers, not creative ball-handlers.
    _no_move_val = t["Driving:No Driving Dribble Move"]
    if _no_move_val >= 70:
        for _move_key in [
            "Driving:Driving Crossover", "Driving:Driving Spin",
            "Driving:Driving Half Spin", "Driving:Driving Double Crossover",
            "Driving:Driving Behind The Back", "Driving:Driving Dribble Hesitation",
            "Driving:Driving In And Out",
        ]:
            t[_move_key] = 5

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
    # Pull-up intensity discount: non-drivers who shoot many mid-range shots tend to
    # stop and rise rather than continue downhill. pct_mid is the era-independent signal
    # (always from shot zones; never sparse). Coefficient 0.20.
    #
    # CRITICAL: the discount must fade to zero for genuine high-Drive players.
    # Elite slashers (Rose Drive=75) both drive aggressively AND pull up — their pull-up
    # game is additive, not a substitute for rim attacks. Applying a full pct_mid discount
    # to them would wrongly penalize their Attack Strong.
    # drive_inverse = max(0, 1 - Drive/75). Non-drivers (Dirk Drive=19) → 0.747 weight,
    # so discount fires at full strength. Elite drivers (Rose Drive=75) → 0.0 weight,
    # so discount is suppressed entirely and rim_commit_ratio maps without modification.
    _drive_inverse = max(0.0, 1.0 - t["Driving:Drive"] / 75.0)
    pullup_disc = pct_mid * 0.20 * _drive_inverse
    attack_adj = max(0.0, rim_commit_ratio - pullup_disc)
    t["Driving:Attack Strong On Drive"] = _scale(attack_adj, 0.15, 0.90, 20, 90)

    # ── DRIVE SETUP ───────────────────────────────────────────────────────

    usage_proxy = _pct(stats.fga, max(stats.fga + stats.ast, 1))

    # Triple Threat Shoot  — cap 55
    # Post players shouldn't hit cap — interior finishing bypasses triple-threat.
    # Dampen by post_freq so center-heavy players read lower here.
    tt_shoot_raw = usage_proxy * (1 - post_freq / 20.0)
    t["Drive Setup:Triple Threat Shoot"]     = _scale(tt_shoot_raw, 0.25, 0.75, 15, 55)

    # Triple Threat Pump Fake  — cap 55
    # Good perimeter shooters (mid + 3PT) draw defenders out and exploit pump fakes more.
    # FTA adds a contact-seeker supplement (bigs who pump fake to draw fouls).
    # high_raw=14: Dirk (pct_sum≈0.68 × 17.3 FGA × 0.7 + 7 FTA × 0.4 ≈ 11) → ~44.
    _pump_shooting_threat = (pct_mid + pct_3) * fga
    _pump_raw = _pump_shooting_threat * 0.7 + stats.fta * 0.4
    t["Drive Setup:Triple Threat Pump Fake"] = _scale(_pump_raw, 0, 14, 5, 55)

    # Triple Threat Jab Step  — cap 55
    # Jab step is used both to initiate drives (faceup_iso) AND to create space for
    # mid-range shots (mid-range shooters jab to put the defender on their heels before rising).
    # pct_mid × fga = absolute mid-range shot volume (direct proxy for jab-into-mid-range).
    _jab_raw = faceup_iso * 0.4 + pct_mid * fga * 0.3
    t["Drive Setup:Triple Threat Jab Step"]  = _scale(_jab_raw, 0, 5.0, 5, 55)

    # Triple Threat Idle  — cap 65
    # Decisiveness on catch: elite mid-range shooters act immediately (low idle);
    # non-shooters and distributors deliberate longer (high idle).
    # pct_mid is the strongest signal — mid-range players always have a clear action plan.
    # pct_3 contributes less (3PT spot-ups still involve some hold time).
    # usg_pct: high-usage scorers are decisive regardless of shot profile.
    # pass_hold: distributors scan for reads → higher idle.
    _shot_decisiveness = pct_mid * 3.0 + pct_3 * 0.5 + stats.usg_pct * 0.5
    _pass_hold = max(0.0, (ast_ratio - 0.25) * 0.15)
    idle_raw = max(0.03, 0.38 - _shot_decisiveness * 0.18 + _pass_hold)
    t["Drive Setup:Triple Threat Idle"]      = _scale(idle_raw, 0, 0.45, 5, 65)

    # Setup With Sizeup  — cap 55
    t["Drive Setup:Setup With Sizeup"]       = _scale(faceup_iso * 0.3, 0, 3.0, 5, 55)

    # Setup With Hesitation  — cap 55
    t["Drive Setup:Setup With Hesitation"]   = _scale(faceup_iso * 0.2, 0, 2.5, 5, 55)

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

    # Post orientation signal.
    # Back-to-basket: hook shots + turnaround shots (both start with back to defender).
    # Face-up: fadeaways (catch facing up, then fade) + unassisted 2PT jumpers weighted by
    #   post_affinity (a post player's unassisted mid-range = caught facing up, self-created shot).
    #   post_affinity = how post-heavy vs perimeter-ISO this player is; scales down the
    #   uast_2pt_jump contribution for perimeter creators who happen to hit mid-range pull-ups.
    # face_up_pct is a CONDITIONAL PREFERENCE: given a post catch, how often does the player face up?
    # Neutral (0.5) when no post shot data exists.
    _btb_vol = stats.fga_hook + stats.fga_turnaround
    _pullup_vol = max(stats.pullup_2pt_fga, stats.fga_pullup, 0.01)
    _post_affinity = min(1.0, _btb_vol / max(0.5, _pullup_vol))
    # Exclude turnaround fadeaways from the face-up pool: a turnaround fadeaway starts
    # back-to-basket (the player pivots, puts the defender behind them, then fades).
    # These shots already appear in fga_turnaround (btb_vol); counting them again in
    # fga_fadeaway double-credits faceup orientation and understates back-down tendency
    # for players like Dirk whose signature move IS the turnaround fade.
    _pure_faceup_fades = max(0.0, stats.fga_fadeaway - stats.fga_turnaround_fadeaway)
    _faceup_vol = _pure_faceup_fades + stats.fga_uast_2pt_jump * _post_affinity
    _post_orientation_vol = _faceup_vol + _btb_vol
    face_up_pct = _pct(_faceup_vol, _post_orientation_vol) if _post_orientation_vol > 0.05 else 0.5
    # Dampening coefficient reduced to 0.15 (was 0.3): back-down and face-up orientation
    # are not mutually exclusive — a player can back down to gain position and then fade.
    # The lower coefficient lets conditional back-down score reflect actual backing-down
    # frequency rather than being excessively suppressed by the face-up fade volume.
    _post_back_pct = 1.0 - face_up_pct * 0.15  # mild dampening for extreme face-up players

    # Post Back Down  — cap 80
    # Conditional preference (given a post catch, how often does player back down?) × volume.
    # high_raw lowered to 6.5 (was 8) so back-down-oriented players exceed their Post Up score
    # when they consistently back down even if total post volume is moderate.
    t["Post Game:Post Back Down"]           = _scale(post_freq * _post_back_pct, 0, 6.5, 5, 80)
    # Post Aggressive Backdown  — cap 70
    # More forceful subset; stays 10-20 pts below Back Down via slower scale (high_raw=10).
    t["Post Game:Post Aggressive Backdown"] = _scale(post_freq * _post_back_pct, 0, 10, 5, 70)
    # Post Face Up  — cap 60
    # Conditional preference: given a post catch, how often does the player initiate facing up?
    # Scaled from face_up_pct directly (not × post_freq) — it's orientation, not volume.
    # 0.85 ceiling: a player with ~85%+ face-up orientation hits cap (60).
    t["Post Game:Post Face Up"]             = _scale(face_up_pct, 0, 0.85, 5, 60)
    # Post Spin  — cap 55
    # CSV: Regular 30-35, Advanced 40-45, Signature 50. Elite post players with high turnaround
    # volume (spinning into shots) register here. fga_turnaround is the strongest direct signal;
    # post_freq supplies a frequency floor so medium-post players get modest spin values.
    # high_raw=6.0: at 6.0 → cap. Dirk (turnaround≈0.77 × 1.5 + 5.5 × 0.5 ≈ 3.9) → ~38.
    _spin_raw = stats.fga_turnaround * 1.5 + post_freq * 0.5
    t["Post Game:Post Spin"]                = _scale(_spin_raw, 0, 6.0, 5, 55)
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
    # high_raw = 1.5: a player taking 1.5 hook shots/game hits the cap — that's a dedicated
    # hook specialist. The old high_raw of 3.0 was too generous (3/game is unrealistic for
    # modern bigs), deflating moderate hook users like Boozer (0.76/game → was 16, now 28).
    _hook_dom  = _scale(stats.fga_hook, 0, 1.5, 5, 50)
    _hook_weak = max(5, _hook_dom - 15)
    _emit("Post Game:Post Hook Right",
          fga_hook=f"{stats.fga_hook:.3f}", high_raw=1.5,
          hook_dom=_hook_dom, hook_weak=_hook_weak)
    t["Post Game:Post Hook Right"] = _hook_dom
    t["Post Game:Post Hook Left"]  = _hook_weak

    # Fade left/right  — cap 50
    # fga_fadeaway (all fadeaways) covers both turnaround and face-up post fades.
    # Using fga_turnaround_fadeaway alone missed face-up faders like Dirk (1.4 face-up fades/game).
    #
    # Directional convention: RIGHT-handed players fade LEFT (away from their dominant hand,
    # creating separation from the defender). Left = dominant for most NBA players.
    # Flip labels manually for left-handed players.
    #
    # Scaling: high_raw=2.5 (lower than prior 4.0) so genuine fadeaway artists like Dirk
    # (≈2.05/game) reach signature tier (40-45) on their dominant side. An outlier with
    # 4+ fadeaways/game hits the cap (50).
    # Weak side = 40% of dominant value (produces ~10-20 range for typical dominant 40-45 values).
    _fade_dom  = _scale(stats.fga_fadeaway, 0, 2.5, 10, 50)
    _fade_weak = max(5, int(_fade_dom * 0.40))
    t["Post Game:Post Fade Left"]  = _fade_dom   # dominant for right-handed players
    t["Post Game:Post Fade Right"] = _fade_weak  # weak side for right-handed players

    # Post move sub-types
    # Shimmy: straight-up turnaround jumpers (fga_turnaround minus the fadeaway subset).
    # Player pivots, fakes with the shoulder, shoots straight up — distinct from fade (which drifts).
    # Non-fadeaway turnarounds are the clearest API proxy for this move.
    # high_raw=1.5: elite shimmy user ceiling; 0.5/game → ~20 (occasional), 1.5/game → 45 (signature).
    _shimmy_raw = max(0.0, stats.fga_turnaround - stats.fga_turnaround_fadeaway)
    t["Post Game:Post Shimmy Shot"]    = _scale(_shimmy_raw, 0, 1.5, 5, 45)

    # Post Hop Shot  — cap 45
    # No direct API proxy exists. Post mastery heuristic: high-volume post players develop
    # a broader counter repertoire. post_mastery = min(1.0, post_freq / 7.0) where 7 = elite
    # post volume (8 poss/game ≈ primary engine). Dirk (5.5) → mastery 0.786 → ~25.
    # Verify with film: hop shot users should be confirmed before finalizing.
    _post_mastery = min(1.0, post_freq / 7.0)
    t["Post Game:Post Hop Shot"]       = _scale(_post_mastery * 0.65, 0, 1.0, 5, 45)

    # Post Step Back Shot  — cap 50
    # CSV: Signature 40-45. high_raw lowered to 0.60 so 0.49/game (Dirk) maps to ~42
    # (Signature Post Stepback tier). Prior high_raw=1.5 mapped Dirk to ~20 (Occasional),
    # understating his signature move. 1.0+/game → cap (50 = Extreme).
    t["Post Game:Post Step Back Shot"] = _scale(stats.fga_step_back, 0, 0.60, 5, 50)

    # Post Up And Under  — cap 45
    # No direct API proxy. Post mastery heuristic: elite post players use more counters.
    # Scaled slightly below Hop Shot (0.55 vs 0.65) — up-and-under requires more footwork
    # mastery, so only the most post-capable players reach signature territory.
    t["Post Game:Post Up And Under"]   = _scale(_post_mastery * 0.55, 0, 1.0, 5, 45)

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

    # ── CROSS-GROUP CAPS ──────────────────────────────────────────────────────
    # Shot Three cap: players with a low overall shot role (Freelance:Shot) cannot be
    # "Primary Three-Point Scorers" in-game even if their 3PT attempt rate is high.
    # Base: Freelance:Shot + 25, floored at 35. Role players (Shot=15) → cap 40; scorers → 75.
    # Distributor adjustment (_ast_ratio reused from Shot Three section above):
    #   pure distributors (Kidd, ast_ratio≈0.75) get a lower floor AND smaller addend,
    #   because their shot-seeking role is genuinely lower than their shot-selection implies.
    #   Kidd: floor→30, addend→16 → cap = max(30, 19+16) = 35.
    _shot_role  = t["Freelance:Shot"]
    _pass_adj   = max(0.0, (_ast_ratio - 0.40) * 1.0)   # _ast_ratio computed in Shot Three section
    _three_floor = int(35 * (1.0 - _pass_adj * 0.4))     # 35 → ~30 for Kidd-level distributor
    _three_add   = int(25 * (1.0 - _pass_adj))           # 25 → ~16 for Kidd-level distributor
    _shot_three_cap = max(_three_floor, min(75, _shot_role + _three_add))
    t["Jump Shooting:Shot Three"] = min(t["Jump Shooting:Shot Three"], _shot_three_cap)
    for _dir in ["Shot Three Left", "Shot Three Left-Center", "Shot Three Center",
                 "Shot Three Right-Center", "Shot Three Right"]:
        t[f"Jump Shooting:{_dir}"] = min(t[f"Jump Shooting:{_dir}"], _shot_three_cap)

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
