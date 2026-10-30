"""
Performance vs projection, built from two daily logs in data/<league>/history/:

  projections.csv    morning snapshot: each player with a game that day, projected points
  player_points.csv  next morning: what each rostered player actually scored that day

Team, per day:   actual = points that counted (ESPN active lineup, not bench/IR)
                 projected = top MAX_PER_DAY projected players that day (what the model counts)
Player, per day: actual = his points (bench games included) vs his projection
Only days that are finished (actuals exist) appear. Tracking starts the first day a
projection snapshot was saved.
"""

from datetime import date
from pathlib import Path

import pandas as pd

KEYS = ["scoring_period", "team_id", "player_id"]


def _read(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, dtype={k: str for k in KEYS})


def _r(x) -> float:
    return round(float(x), 1)


def build_perf(league_dir: Path, max_per_day: int = 10):
    """Returns (index, weeks): index = [{mp, start, end, days}], weeks = {mp: week_json}."""
    proj = _read(league_dir / "history" / "projections.csv")
    pts = _read(league_dir / "history" / "player_points.csv")
    if proj.empty or pts.empty:
        return [], {}

    pts["counted"] = pts["counted"].astype(str).str.lower() == "true"
    pts["points"] = pts["points"].astype(float)
    proj["proj_points"] = proj["proj_points"].astype(float)

    done = sorted(set(proj["scoring_period"]) & set(pts["scoring_period"]), key=int)
    if not done:
        return [], {}
    proj = proj[proj["scoring_period"].isin(done)]
    pts = pts[pts["scoring_period"].isin(done)]
    day_info = (proj.groupby("scoring_period")
                .agg(date=("date", "first"), mp=("matchup_period", "first")).to_dict("index"))

    # player-day rows: every projected game, plus unprojected games that scored (late pickups)
    m = proj.merge(pts[KEYS + ["points", "counted", "slot", "player", "fantasy_team"]],
                   on=KEYS, how="outer", suffixes=("", "_pts"))
    m["player"] = m["player"].fillna(m["player_pts"])
    m["fantasy_team"] = m["fantasy_team"].fillna(m["fantasy_team_pts"])
    m["proj_points"] = m["proj_points"].fillna(0.0)
    m["points"] = m["points"].fillna(0.0)
    m["counted"] = m["counted"].fillna(False).astype(bool)
    m["projected"] = m["date"].notna()
    m = m[m["projected"] | (m["points"] != 0)]
    m["mp"] = m["scoring_period"].map(lambda s: int(day_info[s]["mp"]))

    team_names = (m.dropna(subset=["fantasy_team"]).drop_duplicates(["team_id"], keep="last")
                  .set_index("team_id")["fantasy_team"].to_dict())

    index, weeks = [], {}
    for mp, wk in m.groupby("mp"):
        sps = sorted(wk["scoring_period"].unique(), key=int)
        days = [{"sp": sp, "date": day_info[sp]["date"],
                 "label": date.fromisoformat(day_info[sp]["date"]).strftime("%a %-m/%-d")} for sp in sps]
        teams, players = [], {}
        for tid, tw in wk.groupby("team_id"):
            tdays, tp, ta = {}, 0.0, 0.0
            for sp, td in tw.groupby("scoring_period"):
                p_ = td.loc[td["projected"], "proj_points"].nlargest(max_per_day).sum()
                a_ = td.loc[td["counted"], "points"].sum()
                tdays[sp] = [_r(p_), _r(a_)]
                tp += p_
                ta += a_
            teams.append({"id": tid, "name": team_names.get(tid, f"Team {tid}"),
                          "days": tdays, "proj": _r(tp), "act": _r(ta)})
            plist = []
            for pid, pw in tw.groupby("player_id"):
                pdays = {r.scoring_period: [_r(r.proj_points), _r(r.points),
                                            (r.slot if isinstance(r.slot, str) else ""), bool(r.projected)]
                         for r in pw.itertuples()}
                plist.append({"name": pw["player"].dropna().iloc[-1] if pw["player"].notna().any() else pid,
                              "days": pdays, "proj": _r(pw["proj_points"].sum()),
                              "act": _r(pw["points"].sum()), "games": int(len(pw))})
            plist.sort(key=lambda p: abs(p["act"] - p["proj"]), reverse=True)
            players[tid] = plist
        teams.sort(key=lambda t: t["act"] - t["proj"], reverse=True)
        dates = [d["date"] for d in days]
        weeks[int(mp)] = {"matchup_period": int(mp), "days": days, "teams": teams, "players": players,
                          "max_per_day": max_per_day}
        index.append({"mp": int(mp), "start": min(dates), "end": max(dates), "days": len(days)})
    index.sort(key=lambda w: w["mp"], reverse=True)
    return index, weeks
