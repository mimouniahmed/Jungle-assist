from types import SimpleNamespace

import pytest

from lol_assistant import database, rate_limiter
from lol_assistant.crawler import crawl_matches
from lol_assistant.live_game import get_composition_from_active_game
from lol_assistant.rate_limiter import RateLimiter


def test_rate_limiter_waits_when_window_is_full(monkeypatch):
    clock = {"now": 0.0}
    sleeps = []
    monkeypatch.setattr(rate_limiter.time, "time", lambda: clock["now"])
    monkeypatch.setattr(rate_limiter.time, "sleep", lambda s: sleeps.append(s))

    limiter = RateLimiter(max_calls=2, period_seconds=10)
    limiter.wait_if_needed()
    clock["now"] = 1.0
    limiter.wait_if_needed()
    clock["now"] = 2.0
    limiter.wait_if_needed()  # 3e appel dans la fenêtre : doit attendre la sortie du 1er

    assert sleeps == [pytest.approx(8.0)]


def test_database_deduplicates_matches_and_players():
    conn = database.get_connection(":memory:")
    database.save_match(conn, "EUW1_1", "europe", {"a": 1})
    database.save_match(conn, "EUW1_1", "europe", {"a": 2})
    database.mark_player_explored(conn, "p1")
    database.mark_player_explored(conn, "p1")

    assert database.match_already_collected(conn, "EUW1_1")
    assert not database.match_already_collected(conn, "EUW1_2")
    assert database.player_already_explored(conn, "p1")
    assert conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0] == 1


class FakeRiotClient:
    """Graphe joueurs -> matchs en mémoire, pour tester le snowball sans réseau."""

    region = "europe"

    def __init__(self):
        self.matches = {
            "M1": {"metadata": {"participants": ["A", "B"]}, "info": {"gameMode": "CLASSIC"}},
            "M2": {"metadata": {"participants": ["B", "C"]}, "info": {"gameMode": "CHERRY"}},
            "M3": {"metadata": {"participants": ["C", "D"]}, "info": {"gameMode": "CLASSIC"}},
        }
        self.player_matches = {"A": ["M1"], "B": ["M1", "M2"], "C": ["M2", "M3"], "D": ["M3"]}

    def get_match_ids(self, puuid, count=10):
        return self.player_matches.get(puuid, [])[:count]

    def get_match_detail(self, match_id):
        return self.matches[match_id]


def test_crawler_snowballs_and_keeps_only_classic_games():
    conn = database.get_connection(":memory:")
    crawl_matches(FakeRiotClient(), conn, seed_puuids="A", target_count=100)

    stored = {row[0] for row in conn.execute("SELECT match_id FROM matches")}
    assert stored == {"M1", "M3"}  # M2 (Arena) exploré pour le snowball, mais pas stocké
    assert database.player_already_explored(conn, "D")


def test_live_game_splits_teams(monkeypatch):
    monkeypatch.setattr(
        "lol_assistant.live_game.get_champion_id_to_name",
        lambda: {"1": "Annie", "2": "Olaf", "3": "Galio", "4": "Twisted Fate", "5": "Xin Zhao"},
    )
    game = {"participants": [
        {"puuid": "me", "teamId": 100, "championId": 1},
        {"puuid": "ally", "teamId": 100, "championId": 2},
        {"puuid": "e1", "teamId": 200, "championId": 3},
        {"puuid": "e2", "teamId": 200, "championId": 4},
        {"puuid": "e3", "teamId": 200, "championId": 5},
    ]}
    client = SimpleNamespace(get_puuid=lambda name, tag: "me", get_active_game=lambda puuid: game)

    your_team, enemy_team = get_composition_from_active_game(client, "Name", "TAG")
    assert your_team == ["Annie", "Olaf"]
    assert enemy_team == ["Galio", "Twisted Fate", "Xin Zhao"]


def test_live_game_raises_when_player_not_in_game():
    client = SimpleNamespace(get_puuid=lambda name, tag: "me", get_active_game=lambda puuid: None)
    with pytest.raises(ValueError, match="pas en partie"):
        get_composition_from_active_game(client, "Name", "TAG")
