import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from report import parse_recipients


def test_league_specific_and_everyone_lines():
    r = parse_recipients("main: a@x.com, b@x.com\nleague2: c@x.com\nme@gmail.com")
    assert r == {"main": ["a@x.com", "b@x.com"], "league2": ["c@x.com"], "*": ["me@gmail.com"]}


def test_semicolons_blank_lines_and_junk():
    r = parse_recipients("\n  a@x.com; b@x.com  \n\nmain: not-an-email, c@x.com\n")
    assert r == {"*": ["a@x.com", "b@x.com"], "main": ["c@x.com"]}


def test_empty():
    assert parse_recipients("") == {} and parse_recipients(None) == {}
