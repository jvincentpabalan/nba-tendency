#!/usr/bin/env python3
"""
Parse the ATD Committee Master Tendency Scale CSV and emit a JSON lookup
keyed by the 2K26 tendency key used in mapper.py.

The CSV has a fixed structure:
  Row  1: column headers (CSV tendency names)
  Row  2: definitions
  Row  3: anti-default notes (skipped)
  Row  4: scale tier header labels (skipped)
  Rows 5–15: scale value tiers  (11 rows)
  Row 16: NBA norms (partial — Alley-Oop / Putback / Crash / Drive Right)
  Row 17: NBA norms (main row)
  Row 18: Featured ranges (skipped)
  Row 19: Primary/Star ranges (skipped)
  Row 20: Absolute caps
  Row 21: Additional caps (skipped — already in row 20 for relevant cols)

Usage:
    python3 scripts/parse_atd_csv.py ~/Downloads/atd.csv
    python3 scripts/parse_atd_csv.py ~/Downloads/atd.csv -o ui/src/data/tendency_guide.json
"""

import argparse
import csv
import json
import re
import sys
from pathlib import Path

# ── Name mapping: CSV column → 2K26 tendency key ─────────────────────────────
CSV_TO_KEY = {
    "Shot":                      "Freelance:Shot",
    "Touch":                     "Freelance:Touches",
    "Shot Close":                "Jump Shooting:Shot Close",
    "Shot Under":                "Jump Shooting:Shot Under Basket",
    "Shot Mid":                  "Jump Shooting:Shot Mid-Range",
    "Spot-Up Mid":               "Jump Shooting:Spot Up Shot Mid-Range",
    "Off-Screen Mid":            "Jump Shooting:Off Screen Shot Mid-Range",
    "Shot Three":                "Jump Shooting:Shot Three",
    "Spot-Up Three":             "Jump Shooting:Spot Up Shot Three",
    "Off-Screen Three":          "Jump Shooting:Off Screen Shot Three",
    "Contested Jumper Mid-Range":"Jump Shooting:Contested Jumper Mid-Range",
    "Contested Jumper Three":    "Jump Shooting:Contested Jumper Three",
    "Stepback Jumper Mid-Range": "Jump Shooting:Stepback Jumper Mid-Range",
    "Stepback Jumper Three":     "Jump Shooting:Stepback Jumper Three",
    "Spin Jumper":               "Jump Shooting:Spin Jumper",
    "Transition Pull-Up Three":  "Jump Shooting:Transition Pull Up Three",
    "Dribble Pull-Up Mid-Range": "Jump Shooting:Drive Pull Up Mid-Range",
    "Dribble Pull-Up Three":     "Jump Shooting:Drive Pull Up Three",
    "Drive":                     "Driving:Drive",
    "Spot-Up Drive":             "Driving:Spot Up Drive",
    "Off-Screen Drive":          "Driving:Off Screen Drive",
    "Use Glass":                 "Jump Shooting:Use Glass",
    "Step Through Shot":         "Jump Shooting:Step Through Shot",
    "Driving Layup":             "Layups And Dunks:Driving Layup",
    "Spin Layup":                "Layups And Dunks:Spin Layup",
    "Eurostep Layup":            "Layups And Dunks:Euro Step Layup",
    "Hop Step Layup":            "Layups And Dunks:Hop Step Layup",
    "Floater":                   "Layups And Dunks:Floater",
    "Standing Dunk":             "Layups And Dunks:Standing Dunk",
    "Driving Dunk":              "Layups And Dunks:Driving Dunk",
    "Flashy Dunk":               "Layups And Dunks:Flashy Dunk",
    "Alley-Oop Finish":          "Layups And Dunks:Alley-Oop",
    "Putback":                   "Layups And Dunks:Putback",
    "Crash":                     "Layups And Dunks:Crash",
    "Drive Right":               "Driving:Drive Right",
    "Triple Threat Pump Fake":   "Drive Setup:Triple Threat Pump Fake",
    "Triple Threat Jab Step":    "Drive Setup:Triple Threat Jab Step",
    "Triple Threat Idle":        "Drive Setup:Triple Threat Idle",
    "Triple Threat Shoot":       "Drive Setup:Triple Threat Shoot",
    "Setup with Size-Up":        "Drive Setup:Setup With Sizeup",
    "Setup with Hesitation":     "Drive Setup:Setup With Hesitation",
    "No Setup Dribble":          "Drive Setup:No Setup Dribble",
    "Driving Crossover":         "Driving:Driving Crossover",
    "Driving Double Crossover":  "Driving:Driving Double Crossover",
    "Driving Spin":              "Driving:Driving Spin",
    "Driving Half Spin":         "Driving:Driving Half Spin",
    "Driving Step Back":         "Driving:Driving Step Back",
    "Driving Behind The Back":   "Driving:Driving Behind The Back",
    "Driving Dribble Hesitation":"Driving:Driving Dribble Hesitation",
    "Drive In & Out":            "Driving:Driving In And Out",
    "No Drive Dribble Move":     "Driving:No Driving Dribble Move",
    "Attack Strong on Drive":    "Driving:Attack Strong On Drive",
    "Dish to Open Man":          "Passing:Dish To Open Man",
    "Flashy Pass":               "Passing:Flashy Pass",
    "Alley-Oop Pass":            "Passing:Alley-Oop Pass",
    "Roll vs Pop":               "Freelance:Roll vs. Pop",
    "Spot vs Cut":               "Freelance:Spot vs. Cut",
    "ISO vs Elite":              "Freelance:Iso vs. Elite Defender",
    "ISO vs Good":               "Freelance:Iso vs. Good Defender",
    "ISO vs Average":            "Freelance:Iso vs. Average Defender",
    "ISO vs Poor":               "Freelance:Iso vs. Poor Defender",
    "Play Discipline":           "Freelance:Play Discipline",
    "Post Up":                   "Post Game:Post Up",
    "Post Back Down":            "Post Game:Post Back Down",
    "Post Aggressive Back Down": "Post Game:Post Aggressive Backdown",
    "Post Face Up":              "Post Game:Post Face Up",
    "Post Spin":                 "Post Game:Post Spin",
    "Post Drive":                "Post Game:Post Drive",
    "Post Drop Step":            "Post Game:Post Drop Step",
    "Shoot From Post":           "Post Game:Shoot From Post",
    "Post Hook Left":            "Post Game:Post Hook Left",
    "Post Hook Right":           "Post Game:Post Hook Right",
    "Post Fade Left":            "Post Game:Post Fade Left",
    "Post Fade Right":           "Post Game:Post Fade Right",
    "Post Shimmy":               "Post Game:Post Shimmy Shot",
    "Post Hop Shot":             "Post Game:Post Hop Shot",
    "Post Step Back":            "Post Game:Post Step Back Shot",
    "Post Up & Under":           "Post Game:Post Up And Under",
    "Take Charge":               "Defense:Take Charge",
    "Foul":                      "Defense:Foul",
    "Hard Foul":                 "Defense:Hard Foul",
    "Pass Interception":         "Defense:Pass Interception",
    "On-Ball Steal":             "Defense:On-Ball Steal",
    "Block":                     "Defense:Block Shot",
    "Contest Shot":              "Defense:Contest Shot",
}

# Directional splits share the parent tendency's guide entry
PARENT_KEY = {
    "Jump Shooting:Shot Mid Left":          "Jump Shooting:Shot Mid-Range",
    "Jump Shooting:Shot Mid Left-Center":   "Jump Shooting:Shot Mid-Range",
    "Jump Shooting:Shot Mid Center":        "Jump Shooting:Shot Mid-Range",
    "Jump Shooting:Shot Mid Right-Center":  "Jump Shooting:Shot Mid-Range",
    "Jump Shooting:Shot Mid Right":         "Jump Shooting:Shot Mid-Range",
    "Jump Shooting:Shot Three Left":        "Jump Shooting:Shot Three",
    "Jump Shooting:Shot Three Left-Center": "Jump Shooting:Shot Three",
    "Jump Shooting:Shot Three Center":      "Jump Shooting:Shot Three",
    "Jump Shooting:Shot Three Right-Center":"Jump Shooting:Shot Three",
    "Jump Shooting:Shot Three Right":       "Jump Shooting:Shot Three",
    "Jump Shooting:Shot Close Left":        "Jump Shooting:Shot Close",
    "Jump Shooting:Shot Close Middle":      "Jump Shooting:Shot Close",
    "Jump Shooting:Shot Close Right":       "Jump Shooting:Shot Close",
}


def _cell(row, idx):
    return row[idx].strip() if idx < len(row) else ''


def parse_tier(text):
    """'LOW–HIGH = Label' or 'VALUE = Label' → {'range': [low, high], 'label': str} or None."""
    text = text.strip()
    if not text:
        return None
    m = re.match(r'^(\d+)(?:[–\-](\d+))?\s*=\s*(.+)$', text)
    if not m:
        return None
    low = int(m.group(1))
    high = int(m.group(2)) if m.group(2) else low
    return {'range': [low, high], 'label': m.group(3).strip()}


def parse_norm(text):
    """Extract 'X–Y' range from a norm cell. Returns 'X–Y' string or None."""
    m = re.search(r'(\d+)\s*[–\-]\s*(\d+)', text)
    return f"{m.group(1)}–{m.group(2)}" if m else None


def parse_cap(text):
    """Extract first integer from 'Absolute Cap: N' etc."""
    m = re.search(r'(\d+)', text)
    return int(m.group(1)) if m else None


def main():
    ap = argparse.ArgumentParser(description="Parse ATD CSV → tendency_guide.json")
    ap.add_argument('csv_path', help='Path to ATD Committee Master Tendency Scale CSV')
    ap.add_argument('-o', '--output', default='ui/src/data/tendency_guide.json',
                    help='Output path (default: ui/src/data/tendency_guide.json)')
    args = ap.parse_args()

    csv_path = Path(args.csv_path).expanduser()
    if not csv_path.exists():
        print(f"Error: {csv_path} not found", file=sys.stderr)
        sys.exit(1)

    with open(csv_path, newline='', encoding='utf-8-sig') as f:
        rows = list(csv.reader(f))

    if len(rows) < 20:
        print(f"Error: expected ≥20 rows, got {len(rows)}", file=sys.stderr)
        sys.exit(1)

    headers      = rows[0]        # Row 1 : CSV column names
    defs         = rows[1]        # Row 2 : definitions
    tier_rows    = rows[4:15]     # Rows 5–15: value scale tiers
    alt_norm_row = rows[15]       # Row 16: norm data for Alley-Oop/Putback/Crash/Drive Right
    nba_norm_row = rows[16]       # Row 17: main NBA norm row
    cap_row      = rows[19]       # Row 20: absolute caps

    guide = {}

    for col_idx, csv_name in enumerate(headers):
        csv_name = csv_name.strip()
        key = CSV_TO_KEY.get(csv_name)
        if not key:
            continue

        definition = _cell(defs, col_idx)

        # NBA norm: prefer row 17, fall back to row 16
        nba_norm = (parse_norm(_cell(nba_norm_row, col_idx))
                    or parse_norm(_cell(alt_norm_row, col_idx))
                    or None)

        cap = parse_cap(_cell(cap_row, col_idx))

        tiers = []
        for tr in tier_rows:
            t = parse_tier(_cell(tr, col_idx))
            if t:
                tiers.append(t)

        guide[key] = {
            'definition': definition,
            'tiers': tiers,
            'nba_norm': nba_norm,
            'cap': cap,
        }

    # Directional splits share their parent's guide entry
    for child, parent in PARENT_KEY.items():
        if parent in guide:
            guide[child] = guide[parent]

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(guide, indent=2, ensure_ascii=False) + '\n')
    print(f"Written {len(guide)} entries → {out}")


if __name__ == '__main__':
    main()
