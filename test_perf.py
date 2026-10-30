import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from perf import build_perf


def write(tmp, proj_rows, pts_rows):
    h = tmp / "history"
    h.mkdir(parents=True)
    pd.DataFrame(proj_rows, columns=["date", "scoring_period", "matchup_period", "team_id", "fantasy_team",
                                     "player_id", "player", "injury_status", "fppg_model", "proj_points",
                                     "in_top_n"]).to_csv(h / "projections.csv", index=False)
    pd.DataFrame(pts_rows, columns=["date", "scoring_period", "fantasy_team", "team_id", "player", "player_id",
                                    "slot", "opponent", "points", "counted"]).to_csv(h / "player_points.csv", index=False)


def P(sp, tid, pid, proj, mp=2, d="2026-10-26"):
    return [d, sp, mp, tid, f"T{tid}", pid, f"p{pid}", "ACTIVE", proj, proj, True]


def A(sp, tid, pid, pts, slot="PG"):
    return ["x", sp, f"T{tid}", tid, f"p{pid}", pid, slot, "BOS", pts, slot not in ("BE", "IR")]


def test_team_and_player_math(tmp_path):
    proj = [P(7, 1, 11, 40), P(7, 1, 12, 30), P(7, 1, 13, 20),   # 3 projected, cap 2 -> team proj 70
            P(8, 1, 11, 40, d="2026-10-27")]                   # day 8 has no actuals yet -> excluded
    pts = [A(7, 1, 11, 50), A(7, 1, 12, 10, slot="BE"),          # bench points don't count for the team
           A(7, 1, 13, 25), A(7, 1, 14, 15)]                     # 14 = pickup with no projection
    write(tmp_path, proj, pts)
    index, weeks = build_perf(tmp_path, max_per_day=2)
    assert index == [{"mp": 2, "start": "2026-10-26", "end": "2026-10-26", "days": 1}]
    wk = weeks[2]
    assert [d["sp"] for d in wk["days"]] == ["7"]
    t = wk["teams"][0]
    assert t["days"]["7"] == [70.0, 90.0]                        # proj top-2 = 70; counted = 50+25+15
    players = {p["name"]: p for p in wk["players"]["1"]}
    assert players["p12"]["act"] == 10 and players["p12"]["days"]["7"][2] == "BE"
    assert players["p14"]["proj"] == 0 and players["p14"]["days"]["7"][3] is False
    names = [p["name"] for p in wk["players"]["1"]]
    assert names[0] == "p12"                                     # |10-30| = 20 is the biggest miss


def test_player_days_keep_their_own_dates(tmp_path):
    proj = [P(7, 1, 11, 40), P(8, 1, 11, 35, d="2026-10-27"), P(9, 1, 12, 20, d="2026-10-28")]
    pts = [A(7, 1, 11, 45), A(8, 1, 11, 30), A(9, 1, 12, 26)]
    write(tmp_path, proj, pts)
    wk = build_perf(tmp_path)[1][2]
    p11 = next(p for p in wk["players"]["1"] if p["name"] == "p11")
    assert p11["days"] == {"7": [40.0, 45.0, "PG", True], "8": [35.0, 30.0, "PG", True]}
    assert (p11["proj"], p11["act"], p11["games"]) == (75.0, 75.0, 2)
    assert wk["teams"][0]["days"] == {"7": [40.0, 45.0], "8": [35.0, 30.0], "9": [20.0, 26.0]}


def test_no_history_yet(tmp_path):
    assert build_perf(tmp_path) == ([], {})
