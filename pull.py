"""
Daily ESPN Fantasy Basketball pull + weekly win probability.

Writes to ./data/:
  rosters.csv                 current rosters, injury status, season / last-30 FPPG, games left
  schedule.csv                every remaining NBA game for every rostered player
  yesterday_points.csv        each rostered player's fantasy points yesterday
  win_probability.csv         this week's matchups: banked, expected remaining, expected total, z, P(win)
  history/player_points.csv   growing log of daily points (player credited to the team that had him that day)
  history/win_probability.csv growing log of each day's win probabilities

Env vars: ESPN_LEAGUE_ID, ESPN_YEAR (2027 = the 2026-27 season), ESPN_S2, ESPN_SWID,
          SD_PCT (default 0.25), SD_BASIS ("remaining" default, or "total"),
          MIN_FPPG (default 25: floor on every player's projected FPPG)
"""

import os
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
from espn_api.basketball import League

from model import model_fppg, team_expected_remaining, win_probability

LEAGUE_ID = int(os.environ["ESPN_LEAGUE_ID"])
YEAR = int(os.environ.get("ESPN_YEAR") or 2027)
ESPN_S2 = os.environ.get("ESPN_S2") or None
SWID = os.environ.get("ESPN_SWID") or None
SD_PCT = float(os.environ.get("SD_PCT") or 0.25)
SD_BASIS = os.environ.get("SD_BASIS") or "remaining"
MIN_FPPG = float(os.environ.get("MIN_FPPG") or 25)  # floor on projected FPPG for every rostered player
OUT = Path(os.environ.get("ESPN_OUT_DIR") or "data")

# ESPN lineupSlotId -> name for active slots (12 = BE, 13 = IR are excluded)
SLOT_ID_NAME = {0: "PG", 1: "SG", 2: "SF", 3: "PF", 4: "C", 5: "G", 6: "F",
                7: "SG/SF", 8: "G/F", 9: "PF/C", 10: "F/C", 11: "UT"}
DEFAULT_SLOTS = {"PG": 1, "SG": 1, "SF": 1, "PF": 1, "C": 1, "G": 1, "F": 1, "UT": 3}


def fppg(player, split):
    return player.stats.get(f"{YEAR}_{split}", {}).get("applied_avg")


def active_slot_counts(league) -> dict:
    """Read the league's starting-lineup slots from ESPN settings (one small request)."""
    try:
        data = league.espn_request.league_get(params={"view": "mSettings"})
        counts = data["settings"]["rosterSettings"]["lineupSlotCounts"]
        slots = {SLOT_ID_NAME[int(k)]: v for k, v in counts.items()
                 if int(k) in SLOT_ID_NAME and v > 0}
        return slots or DEFAULT_SLOTS
    except Exception as e:  # never let this kill the daily run
        print(f"Could not read lineup slots ({e}); using default 10-man lineup")
        return DEFAULT_SLOTS


def append_dedup(df: pd.DataFrame, path: Path, keys: list):
    """Append rows to a CSV log, keeping the newest row for each key (safe to re-run)."""
    if df.empty:
        return
    df = df.astype({k: str for k in keys})
    if path.exists():
        old = pd.read_csv(path, dtype={k: str for k in keys})
        df = pd.concat([old, df], ignore_index=True)
    df.drop_duplicates(subset=keys, keep="last").to_csv(path, index=False)


def main():
    (OUT / "history").mkdir(parents=True, exist_ok=True)
    league = League(league_id=LEAGUE_ID, year=YEAR, espn_s2=ESPN_S2, swid=SWID)
    now = datetime.now()
    today = date.today()
    slot_counts = active_slot_counts(league)

    # ---------- Current rosters: drives everything forward-looking ----------
    cur_period = league.scoringPeriodId
    matchup_id = league.currentMatchupPeriod
    week_periods = sorted(int(p) for p in league.settings.matchup_periods.get(str(matchup_id), []))
    remaining_periods = [p for p in week_periods if p >= cur_period]

    roster_rows, sched_rows, model_players = [], [], {}
    for team in league.teams:
        model_players[team.team_id] = []
        for p in team.roster:
            season, last30 = fppg(p, "total"), fppg(p, "last_30")
            rate = model_fppg(last30, season, p.projected_avg_points, MIN_FPPG)
            schedule = {int(k): v for k, v in p.schedule.items()}
            games_left = sum(1 for k, g in schedule.items()
                             if k in remaining_periods and g["date"] > now)
            model_players[team.team_id].append({
                "fppg": rate,
                "slots": set(p.eligibleSlots),
                "injury_status": p.injuryStatus,
                "expected_return": p.expected_return_date,
                "schedule": schedule,
            })
            roster_rows.append({
                "fantasy_team": team.team_name, "team_id": team.team_id,
                "player": p.name, "player_id": p.playerId, "nba_team": p.proTeam,
                "position": p.position, "lineup_slot": p.lineupSlot,
                "injury_status": p.injuryStatus, "injured": p.injured,
                "expected_return": p.expected_return_date,
                "fppg_season": season, "fppg_last30": last30,
                "fppg_projected": p.projected_avg_points, "fppg_model": rate,
                "games_left_this_matchup": games_left,
            })
            for k, g in schedule.items():
                if g["date"] > now:
                    sched_rows.append({
                        "fantasy_team": team.team_name, "player": p.name,
                        "player_id": p.playerId, "scoring_period": k,
                        "in_current_matchup": k in remaining_periods,
                        "game_datetime": g["date"], "opponent": g["team"],
                    })

    pd.DataFrame(roster_rows).to_csv(OUT / "rosters.csv", index=False)
    pd.DataFrame(sched_rows).sort_values(["game_datetime", "player"]).to_csv(
        OUT / "schedule.csv", index=False)

    # ---------- Yesterday's points, credited to whoever rostered the player that day ----------
    yday = cur_period - 1
    pts_rows = []
    if yday >= 1:
        for box in league.box_scores(scoring_period=yday, matchup_total=False):
            for team, lineup in ((box.home_team, box.home_lineup), (box.away_team, box.away_lineup)):
                for bp in lineup:
                    pts_rows.append({
                        "date": today - timedelta(days=1), "scoring_period": yday,
                        "fantasy_team": getattr(team, "team_name", team),
                        "team_id": getattr(team, "team_id", team),
                        "player": bp.name, "player_id": bp.playerId,
                        "slot": bp.slot_position, "opponent": bp.pro_opponent,
                        "points": bp.points,
                        "counted": bp.slot_position not in ("BE", "IR"),
                    })
    pts = pd.DataFrame(pts_rows)
    pts.to_csv(OUT / "yesterday_points.csv", index=False)
    append_dedup(pts, OUT / "history" / "player_points.csv",
                 ["scoring_period", "team_id", "player_id"])

    # ---------- Win probability for the current matchup period ----------
    wp_rows = []
    for box in league.box_scores():  # current matchup, ESPN live totals
        if not box.home_team or not box.away_team:  # bye week
            continue
        home, away = box.home_team, box.away_team
        rem_h, g_h = team_expected_remaining(model_players[home.team_id], remaining_periods, now, slot_counts)
        rem_a, g_a = team_expected_remaining(model_players[away.team_id], remaining_periods, now, slot_counts)
        p_home, z, exp_h, exp_a = win_probability(
            box.home_score, rem_h, box.away_score, rem_a, SD_PCT, SD_BASIS)
        wp_rows.append({
            "run_date": today, "matchup_period": matchup_id,
            "home_team": home.team_name, "away_team": away.team_name,
            "home_banked": box.home_score, "away_banked": box.away_score,
            "home_exp_remaining": round(rem_h, 1), "away_exp_remaining": round(rem_a, 1),
            "home_exp_games": g_h, "away_exp_games": g_a,
            "home_exp_total": round(exp_h, 1), "away_exp_total": round(exp_a, 1),
            "z": round(z, 3), "home_win_prob": round(p_home, 4),
            "away_win_prob": round(1 - p_home, 4),
            "sd_pct": SD_PCT, "sd_basis": SD_BASIS,
        })
    wp = pd.DataFrame(wp_rows)
    wp.to_csv(OUT / "win_probability.csv", index=False)
    append_dedup(wp, OUT / "history" / "win_probability.csv",
                 ["run_date", "matchup_period", "home_team"])

    # ---------- Summary (shows on the GitHub Actions run page) ----------
    lines = [f"### Matchup {matchup_id} — {today}  (σ = {SD_PCT:.0%} of {SD_BASIS})", "",
             "| Home | Exp | Win % | Away | Exp | Win % |", "|---|---:|---:|---|---:|---:|"]
    for r in wp_rows:
        lines.append(f"| {r['home_team']} | {r['home_exp_total']} | {r['home_win_prob']:.0%} "
                     f"| {r['away_team']} | {r['away_exp_total']} | {r['away_win_prob']:.0%} |")
    summary = "\n".join(lines)
    print(summary)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(summary + "\n")


if __name__ == "__main__":
    main()
