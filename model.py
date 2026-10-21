"""
Pure functions for the weekly win-probability model (no ESPN calls, easy to test).

Model, per matchup:
    expected_total = banked + expected_remaining
    sigma_team     = SD_PCT * expected_remaining          (default basis)
                  or SD_PCT * expected_total              (SD_BASIS="total")
    z              = (exp_total_A - exp_total_B) / sqrt(sigma_A^2 + sigma_B^2)
    P(A wins)      = Phi(z)

"banked" is ESPN's own live matchup score, so it already contains points scored
by players who have since been dropped and excludes bench points.
"expected_remaining" is built from the CURRENT roster only, game by game, for the
games left in this matchup period, filling the active lineup each day.
"""

from datetime import date, datetime, timedelta
from math import erf, sqrt

# Most specific slot first, so flexible players don't steal a slot someone else needs.
SLOT_ORDER = ["PG", "SG", "SF", "PF", "C", "SG/SF", "G/F", "PF/C", "F/C", "G", "F", "UT"]

# Probability a player suits up for a game, by ESPN injuryStatus.
DEFAULT_AVAILABILITY = {
    "ACTIVE": 1.0,
    "DAY_TO_DAY": 0.75,
    "QUESTIONABLE": 0.5,
    "DOUBTFUL": 0.25,
    "OUT": 0.0,
    "SUSPENSION": 0.0,
    "INJURY_RESERVE": 0.0,
}
RETURNING_AVAILABILITY = 0.8  # OUT player whose expected return date has passed


def prior_fppg(projected, last_season):
    """Pre-season basis: mean of ESPN's season projection and last season's FPPG (whichever exist)."""
    vals = [v for v in (projected, last_season) if v]
    return sum(vals) / len(vals) if vals else 0.0


def model_fppg(recent, games_played, prior, floor: float = 25.0, prior_games: float = 5) -> float:
    """
    Rate used for future games.
      recent       this season's last-30 FPPG (or season FPPG)
      games_played games this season
      prior        projection / last-season basis (see prior_fppg)
    Blend: (gp * recent + prior_games * prior) / (gp + prior_games)
      0 games -> all prior; 5 games -> 50/50; 20 games -> 80% this season.
    Never below `floor`: streamers are usually short-term injury fill-ins whose
    averages understate their current role.
    """
    gp = games_played or 0
    if recent and gp > 0 and prior:
        base = (gp * recent + prior_games * prior) / (gp + prior_games)
    elif recent:
        base = recent
    else:
        base = prior or 0.0
    return max(base, floor)


def period_date_anchor(cur_period: int, period_dates: dict, fallback: date) -> date:
    """
    Calendar date of the current scoring period. ESPN scoring periods are consecutive
    days, so any period with a known game date pins all of them.
    """
    if not period_dates:
        return fallback
    p = min(period_dates, key=lambda k: abs(k - cur_period))
    return period_dates[p] - timedelta(days=p - cur_period)


def matchup_remaining_periods(cur_period: int, cur_date: date, start_period: int,
                              weeks_in_matchup: int = 1, end_override: date | None = None):
    """
    Scoring periods left in the current matchup, today included.
    ESPN H2H matchups end on Sunday; a matchup spanning several weeks
    (All-Star break, multi-week playoff rounds) ends that many Sundays later.
    Returns (periods, start_date, end_date).
    """
    start_date = cur_date - timedelta(days=cur_period - start_period)
    end_date = end_override or (
        start_date + timedelta(days=6 - start_date.weekday() + 7 * (weeks_in_matchup - 1)))
    days_left = (end_date - cur_date).days
    return list(range(cur_period, cur_period + days_left + 1)), start_date, end_date


def normal_cdf(z: float) -> float:
    return 0.5 * (1.0 + erf(z / sqrt(2.0)))


def availability(status, game_dt: datetime, expected_return: date | None,
                 table=DEFAULT_AVAILABILITY) -> float:
    status = status or "ACTIVE"
    p = table.get(status, 1.0)
    if p == 0.0 and expected_return and game_dt.date() >= expected_return:
        return RETURNING_AVAILABILITY
    return p


def best_lineup_points(candidates, slot_counts: dict) -> float:
    """
    candidates: list of (expected_points, eligible_slot_names) for players with a game today.
    slot_counts: active slot name -> count (no BE / IR).
    Greedy: best player first, into the most specific open slot he is eligible for.
    """
    open_slots = dict(slot_counts)
    total = 0.0
    for pts, eligible in sorted(candidates, key=lambda c: c[0], reverse=True):
        for slot in SLOT_ORDER:
            if open_slots.get(slot, 0) > 0 and slot in eligible:
                open_slots[slot] -= 1
                total += pts
                break
    return total


def team_expected_remaining(players, scoring_periods, now: datetime, slot_counts: dict):
    """
    players: dicts with keys fppg, slots (set of slot names), injury_status,
             expected_return (date|None), schedule ({period_int: {'date': datetime}}).
    scoring_periods: remaining scoring-period ids (ints) in this matchup.
    Only games that tip off after `now` count; anything already started is in ESPN's live score.
    Returns (expected_points, expected_games_used).
    """
    total, games = 0.0, 0
    for period in scoring_periods:
        cands = []
        for p in players:
            g = p["schedule"].get(period)
            if not g or g["date"] <= now or not p["fppg"]:
                continue
            a = availability(p["injury_status"], g["date"], p["expected_return"])
            if a > 0:
                cands.append((p["fppg"] * a, p["slots"]))
        total += best_lineup_points(cands, slot_counts)
        games += min(len(cands), sum(slot_counts.values()))
    return total, games


def win_probability(banked_a, remaining_a, banked_b, remaining_b,
                    sd_pct: float = 0.25, basis: str = "remaining"):
    """Returns (P(A wins), z, expected_total_a, expected_total_b)."""
    exp_a, exp_b = banked_a + remaining_a, banked_b + remaining_b
    if basis == "total":
        sa, sb = sd_pct * exp_a, sd_pct * exp_b
    else:
        sa, sb = sd_pct * remaining_a, sd_pct * remaining_b
    sigma = sqrt(sa ** 2 + sb ** 2)
    diff = exp_a - exp_b
    if sigma == 0:  # matchup is over: score is final
        p = 1.0 if diff > 0 else 0.0 if diff < 0 else 0.5
        return p, float("inf") if diff > 0 else float("-inf") if diff < 0 else 0.0, exp_a, exp_b
    z = diff / sigma
    return normal_cdf(z), z, exp_a, exp_b
