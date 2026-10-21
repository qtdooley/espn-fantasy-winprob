import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from model import (availability, best_lineup_points, model_fppg,
                   team_expected_remaining, win_probability)

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


def test_fppg_floor():
    assert model_fppg(12.0, 15.0, 20.0) == 25        # streamer with low averages -> floor
    assert model_fppg(None, None, None) == 25        # no stats at all -> floor
    assert model_fppg(41.5, 38.0, 40.0) == 41.5      # starter keeps his last-30
    assert model_fppg(None, 33.0, 30.0) == 33.0      # no last-30 yet -> season
    assert model_fppg(12.0, None, None, floor=0) == 12.0


def test_lineup_cap_and_slot_specificity():
    slots = {"C": 1, "UT": 1}
    cands = [(50, {"C", "UT"}), (40, {"PG", "UT"}), (30, {"C", "UT"})]
    # 50 takes C, 40 takes UT, 30 sits
    assert best_lineup_points(cands, slots) == 90


def test_out_player_returns_after_expected_date():
    assert availability("OUT", datetime(2026, 10, 23), date(2026, 10, 25)) == 0.0
    assert availability("OUT", datetime(2026, 10, 26), date(2026, 10, 25)) == 0.8
    assert availability(None, datetime(2026, 10, 26), None) == 1.0


def test_started_games_and_other_weeks_are_ignored():
    players = [{
        "fppg": 40, "slots": {"UT"}, "injury_status": "ACTIVE", "expected_return": None,
        # period 3 already tipped off (in ESPN's live score), 4 & 5 upcoming, 9 is next week
        "schedule": {3: game(22, 1), 4: game(23), 5: game(24), 9: game(30)},
    }]
    pts, games = team_expected_remaining(players, [3, 4, 5, 6], NOW, {"UT": 1})
    assert pts == 80 and games == 2


def test_dropped_player_points_stay_banked_and_pickup_only_adds_future_games():
    # Team A banked 200 incl. 60 from a player since dropped. Pickup has 2 games left.
    pickup = {"fppg": 30, "slots": {"UT"}, "injury_status": "ACTIVE", "expected_return": None,
              "schedule": {4: game(23), 5: game(24)}}
    rem_a, _ = team_expected_remaining([pickup], [4, 5], NOW, {"UT": 1})
    p, _, exp_a, exp_b = win_probability(200, rem_a, 200, 40)
    assert (exp_a, exp_b) == (260, 240) and p > 0.5
