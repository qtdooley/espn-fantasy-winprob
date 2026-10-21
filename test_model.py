import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from model import (availability, top_n_points, matchup_remaining_periods, model_fppg,
                   period_date_anchor, prior_fppg, team_expected_remaining, win_probability)

NOW = datetime(2026, 10, 22, 5, 0)


def game(day, hour=19):
    return {"date": datetime(2026, 10, day, hour), "team": "XXX"}


def test_even_matchup_is_coin_flip():
    p, z, *_ = win_probability(100, 300, 100, 300)
    assert p == 0.5 and z == 0


def test_formula_matches_hand_calc():
    # A: 150 banked + 300 left = 450, B: 100 + 300 = 400
    # sigma = sqrt((.25*300)^2 * 2) = 106.07 ; z = 50 / 106.07 = 0.4714 ; Phi = 0.6813
    p, z, ea, eb = win_probability(150, 300, 100, 300)
    assert (ea, eb) == (450, 400)
    assert round(z, 4) == 0.4714 and round(p, 4) == 0.6813


def test_total_basis_is_wider_than_remaining_basis():
    p_rem, *_ = win_probability(400, 100, 300, 100, basis="remaining")
    p_tot, *_ = win_probability(400, 100, 300, 100, basis="total")
    assert p_rem > p_tot > 0.5


def test_finished_matchup_is_certain():
    assert win_probability(500, 0, 499, 0)[0] == 1.0
    assert win_probability(400, 0, 401, 0)[0] == 0.0


def test_prior_is_mean_of_projection_and_last_season():
    assert prior_fppg(40, 30) == 35
    assert prior_fppg(40, None) == 40
    assert prior_fppg(0, None) == 0


def test_blend_moves_from_prior_to_actual():
    assert model_fppg(None, 0, 40) == 40                  # opening week: all prior
    assert abs(model_fppg(60, 1, 40) - 260 / 6) < 1e-9    # one hot game barely moves it
    assert model_fppg(60, 5, 40) == 50                    # 5 games: 50/50
    assert model_fppg(60, 45, 40) == 58                   # mid-season: 90% actual
    assert model_fppg(45, 10, 0) == 45                    # no prior: actual only


def test_fppg_floor():
    assert model_fppg(12.0, 10, 18.0) == 25        # streamer with low averages -> floor
    assert model_fppg(None, 0, 0) == 25            # no stats at all -> floor
    assert model_fppg(12.0, 10, None, floor=0) == 12.0


def test_opening_week_window():
    # Opening night Tue Oct 20 is period 1; matchup runs through Sun Oct 25 = period 6
    periods, start, end = matchup_remaining_periods(1, date(2026, 10, 20), 1)
    assert periods == [1, 2, 3, 4, 5, 6] and end == date(2026, 10, 25)


def test_mid_week_window_and_override():
    # Thu Oct 29 is period 10; matchup 2 started Mon Oct 26 (period 7)
    periods, start, end = matchup_remaining_periods(10, date(2026, 10, 29), 7)
    assert start == date(2026, 10, 26) and periods == [10, 11, 12, 13]
    # Two-week matchup (e.g. All-Star break) ends a Sunday later
    periods, _, end = matchup_remaining_periods(10, date(2026, 10, 29), 7, weeks_in_matchup=2)
    assert end == date(2026, 11, 8) and periods[-1] == 20
    periods, _, _ = matchup_remaining_periods(10, date(2026, 10, 29), 7, end_override=date(2026, 10, 30))
    assert periods == [10, 11]


def test_period_date_anchor():
    dates = {3: date(2026, 10, 22), 5: date(2026, 10, 24)}
    assert period_date_anchor(1, dates, date(2000, 1, 1)) == date(2026, 10, 20)
    assert period_date_anchor(1, {}, date(2026, 10, 20)) == date(2026, 10, 20)


def test_top_n_cap():
    assert top_n_points([50, 40, 30], 2) == 90            # more players than the cap -> best 2
    assert top_n_points([30, 50], 10) == 80               # fewer than the cap -> all of them
    assert top_n_points([], 10) == 0


def test_daily_cap_13_play_vs_8_play():
    def p(day_list):
        return {"fppg": 30, "injury_status": "ACTIVE", "expected_return": None,
                "schedule": {d: game(d + 19) for d in day_list}}
    # 13 players have a game on period 4, only 8 of them on period 5
    roster = [p([4, 5]) for _ in range(8)] + [p([4]) for _ in range(5)]
    pts, games = team_expected_remaining(roster, [4, 5], NOW, 10)
    assert games == 10 + 8 and pts == 30 * 18


def test_out_players_never_count_toward_the_cap():
    healthy = [{"fppg": 30, "injury_status": "ACTIVE", "expected_return": None,
                "schedule": {4: game(23)}} for _ in range(9)]
    hurt = [{"fppg": 60, "injury_status": "OUT", "expected_return": None,
             "schedule": {4: game(23)}} for _ in range(3)]
    pts, games = team_expected_remaining(healthy + hurt, [4], NOW, 10)
    assert games == 9 and pts == 270


def test_out_player_returns_after_expected_date():
    assert availability("OUT", datetime(2026, 10, 23), date(2026, 10, 25)) == 0.0
    assert availability("OUT", datetime(2026, 10, 26), date(2026, 10, 25)) == 0.8
    assert availability(None, datetime(2026, 10, 26), None) == 1.0
    assert availability("DAY_TO_DAY", datetime(2026, 10, 26), None) == 1.0


def test_started_games_and_other_weeks_are_ignored():
    players = [{
        "fppg": 40, "injury_status": "ACTIVE", "expected_return": None,
        # period 3 already tipped off (in ESPN's live score), 4 & 5 upcoming, 9 is next week
        "schedule": {3: game(22, 1), 4: game(23), 5: game(24), 9: game(30)},
    }]
    pts, games = team_expected_remaining(players, [3, 4, 5, 6], NOW, 1)
    assert pts == 80 and games == 2


def test_dropped_player_points_stay_banked_and_pickup_only_adds_future_games():
    # Team A banked 200 incl. 60 from a player since dropped. Pickup has 2 games left.
    pickup = {"fppg": 30, "injury_status": "ACTIVE", "expected_return": None,
              "schedule": {4: game(23), 5: game(24)}}
    rem_a, _ = team_expected_remaining([pickup], [4, 5], NOW, 1)
    p, _, exp_a, exp_b = win_probability(200, rem_a, 200, 40)
    assert (exp_a, exp_b) == (260, 240) and p > 0.5
