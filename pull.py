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
          MIN_FPPG (default 25: floor on every player's projected FPPG),
          PRIOR_GAMES (default 5: weight of projection / last season, in games),
          MATCHUP_END (optional YYYY-MM-DD override for the matchup's last day),
          MAX_PER_DAY (default 10: most players counted on any one day)
"""

import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
from espn_api.basketball import League

from model import (availability, matchup_remaining_periods, model_fppg, period_date_anchor,
                   prior_fppg, team_expected_remaining, win_probability)

YEAR = int(os.environ.get("ESPN_YEAR") or 2027)
ESPN_S2 = os.environ.get("ESPN_S2") or None
SWID = os.environ.get("ESPN_SWID") or None
SD_PCT = float(os.environ.get("SD_PCT") or 0.25)
SD_BASIS = os.environ.get("SD_BASIS") or "remaining"
MIN_FPPG = float(os.environ.get("MIN_FPPG") or 25)  # floor on projected FPPG for every rostered player
PRIOR_GAMES = float(os.environ.get("PRIOR_GAMES") or 5)  # weight of projection/last season, in games
# Last day of the current matchup (YYYY-MM-DD) if ESPN's differs from "the coming Sunday"
MATCHUP_END = (date.fromisoformat(os.environ["MATCHUP_END"])
               if os.environ.get("MATCHUP_END") else None)
OUT_DEFAULT = Path(os.environ.get("ESPN_OUT_DIR") or "data")

MAX_PER_DAY = int(os.environ.get("MAX_PER_DAY") or 10)  # most players counted on any one day


def fppg(player, split):
    return player.stats.get(f"{YEAR}_{split}", {}).get("applied_avg")


def games_played(player):
    total = player.stats.get(f"{YEAR}_total", {})
    gp = (total.get("total") or {}).get("GP")
    if gp is None and total.get("applied_avg"):
        gp = round(total.get("applied_total", 0) / total["applied_avg"])
    return int(gp or 0)


def last_season_fppg(league, player_ids) -> dict:
    """playerId -> last season's fantasy points per game, scored with this league's settings."""
    out = {}
    if not player_ids:
        return out
    try:
        data = league.espn_request.get_player_card(
            player_ids, league.finalScoringPeriod, additional_filters=[f"00{YEAR - 1}"])
        for entry in data.get("players", []):
            pl = entry.get("player", entry)
            for s in pl.get("stats", []):
                if s.get("id") == f"00{YEAR - 1}" and s.get("appliedAverage"):
                    out[pl.get("id", entry.get("id"))] = round(s["appliedAverage"], 2)
    except Exception as e:  # never let this kill the daily run
        print(f"Could not load last-season averages ({e}); using projections only")
    return out


def append_dedup(df: pd.DataFrame, path: Path, keys: list, keep: str = "last"):
    """Append rows to a CSV log, keeping one row per key: the newest (keep="last") or the
    first one ever written (keep="first"). Safe to re-run."""
    if df.empty:
        return
    df = df.astype({k: str for k in keys})
    if path.exists():
        old = pd.read_csv(path, dtype={k: str for k in keys})
        df = pd.concat([old, df], ignore_index=True)
    df.drop_duplicates(subset=keys, keep=keep).to_csv(path, index=False)


def main(league_id=None, out_dir=None, espn_s2=None, swid=None, label=None):
    """Pull one league into out_dir. Returns that league's meta dict (also saved as meta.json)."""
    league_id = int(league_id or os.environ["ESPN_LEAGUE_ID"])
    OUT = Path(out_dir) if out_dir else OUT_DEFAULT
    league = League(league_id=league_id, year=YEAR,
                    espn_s2=espn_s2 or ESPN_S2, swid=swid or SWID)
    (OUT / "history").mkdir(parents=True, exist_ok=True)
    label = label or league.settings.name
    now = datetime.now()
    today = date.today()

    # ---------- Which days (scoring periods) are left in this matchup ----------
    cur_period = league.scoringPeriodId
    matchup_id = league.currentMatchupPeriod
    period_dates = {}
    for team in league.teams:
        for p in team.roster:
            for k, g in p.schedule.items():
                period_dates.setdefault(int(k), g["date"].date())
    cur_date = period_date_anchor(cur_period, period_dates, today)
    played = [int(x) for x in getattr(league, "matchup_ids", {}).get(matchup_id, [])]
    start_period = min(played) if played else cur_period
    weeks = max(1, len(league.settings.matchup_periods.get(str(matchup_id), [1])))
    remaining_periods, wk_start, wk_end = matchup_remaining_periods(
        cur_period, cur_date, start_period, weeks, MATCHUP_END)

    # ---------- Last season's FPPG for every rostered player (one request) ----------
    last_season = last_season_fppg(league, [p.playerId for t in league.teams for p in t.roster])

    roster_rows, sched_rows, model_players = [], [], {}
    for team in league.teams:
        model_players[team.team_id] = []
        for p in team.roster:
            season, last30 = fppg(p, "total"), fppg(p, "last_30")
            gp = games_played(p)
            prior = prior_fppg(p.projected_avg_points, last_season.get(p.playerId))
            rate = model_fppg(last30 or season, gp, prior, MIN_FPPG, PRIOR_GAMES)
            schedule = {int(k): v for k, v in p.schedule.items()}
            games_left = sum(1 for k, g in schedule.items()
                             if k in remaining_periods and g["date"] > now)
            model_players[team.team_id].append({
                "fppg": rate,
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
                "games_played": gp, "fppg_season": season, "fppg_last30": last30,
                "fppg_projected": p.projected_avg_points,
                "fppg_last_season": last_season.get(p.playerId),
                "fppg_prior": round(prior, 2), "fppg_model": round(rate, 2),
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

    # ---------- Today's projection snapshot, for "performance vs projection" ----------
    # Each player with a game today: projected points (FPPG x P(plays)), and whether he's in
    # his team's top MAX_PER_DAY. The first run of the day sets it (keep="first"), so later
    # runs can't rewrite the morning projection after the games; they only add pickups.
    if cur_date == today:
        snap_rows = []
        for team in league.teams:
            day = []
            for p, mp in zip(team.roster, model_players[team.team_id]):
                g = mp["schedule"].get(cur_period)
                if not g:
                    continue
                a = availability(mp["injury_status"], g["date"], mp["expected_return"])
                day.append((mp["fppg"] * a, p, mp))
            day.sort(key=lambda x: x[0], reverse=True)
            for rank, (proj, p, mp) in enumerate(day):
                snap_rows.append({
                    "date": today, "scoring_period": cur_period, "matchup_period": matchup_id,
                    "team_id": team.team_id, "fantasy_team": team.team_name,
                    "player_id": p.playerId, "player": p.name, "injury_status": p.injuryStatus,
                    "fppg_model": round(mp["fppg"], 2), "proj_points": round(proj, 2),
                    "in_top_n": rank < MAX_PER_DAY,
                })
        append_dedup(pd.DataFrame(snap_rows), OUT / "history" / "projections.csv",
                     ["scoring_period", "team_id", "player_id"], keep="first")
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
        rem_h, g_h = team_expected_remaining(model_players[home.team_id], remaining_periods, now, MAX_PER_DAY)
        rem_a, g_a = team_expected_remaining(model_players[away.team_id], remaining_periods, now, MAX_PER_DAY)
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
            "matchup_start": wk_start, "matchup_end": wk_end,
        })
    wp = pd.DataFrame(wp_rows)
    wp.to_csv(OUT / "win_probability.csv", index=False)
    append_dedup(wp, OUT / "history" / "win_probability.csv",
                 ["run_date", "matchup_period", "home_team"])

    # ---------- Summary (shows on the GitHub Actions run page) ----------
    meta = {
        "league_name": label, "espn_league_name": league.settings.name,
        "matchup_period": matchup_id, "matchup_start": str(wk_start), "matchup_end": str(wk_end),
        "days_left": len(remaining_periods), "updated_at": now.isoformat(timespec="minutes"),
        "espn_day": str(cur_date),  # the day ESPN considers "today"; lags overnight until ESPN rolls over
        "max_per_day": MAX_PER_DAY, "sd_pct": SD_PCT, "sd_basis": SD_BASIS, "min_fppg": MIN_FPPG,
    }
    (OUT / "meta.json").write_text(json.dumps(meta, indent=2))

    lines = [f"## {label}", "", f"### Matchup {matchup_id}: {wk_start:%a %b %-d} – {wk_end:%a %b %-d}  "
             f"({len(remaining_periods)} days left, top {MAX_PER_DAY} players/day, "
             f"σ = {SD_PCT:.0%} of {SD_BASIS})", "",
             "If these dates don't match ESPN's matchup dates, set the repo variable "
             "`MATCHUP_END` (YYYY-MM-DD).", "",
             "| Home | Now | Games left | Exp | Win % | Away | Now | Games left | Exp | Win % |",
             "|---|---:|---:|---:|---:|---|---:|---:|---:|---:|"]
    for r in wp_rows:
        lines.append(
            f"| {r['home_team']} | {r['home_banked']} | {r['home_exp_games']} | {r['home_exp_total']} "
            f"| {r['home_win_prob']:.0%} | {r['away_team']} | {r['away_banked']} | {r['away_exp_games']} "
            f"| {r['away_exp_total']} | {r['away_win_prob']:.0%} |")
    summary = "\n".join(lines)
    print(summary)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(summary + "\n")
    return meta


if __name__ == "__main__":
    main()
