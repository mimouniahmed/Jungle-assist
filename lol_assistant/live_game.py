import json
from pathlib import Path

import requests

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CHAMPION_MAP_CACHE = DATA_DIR / "champion_id_map.json"


def get_champion_id_to_name(cache_path=CHAMPION_MAP_CACHE):
    """Maps each numeric championId (as returned by Spectator-V5) to the champion name (the
    same format used everywhere else in the project: dataset, SHAP, game_plan.py).
    Source: Data Dragon, Riot's static, unauthenticated CDN for game data (no API key
    needed). Cached locally to avoid downloading it on every call."""
    if cache_path.exists():
        with open(cache_path) as f:
            return json.load(f)

    versions = requests.get("https://ddragon.leagueoflegends.com/api/versions.json").json()
    latest = versions[0]
    champions = requests.get(
        f"https://ddragon.leagueoflegends.com/cdn/{latest}/data/en_US/champion.json"
    ).json()["data"]

    id_to_name = {entry["key"]: entry["id"] for entry in champions.values()}

    with open(cache_path, "w") as f:
        json.dump(id_to_name, f)

    return id_to_name


def get_composition_from_active_game(riot_client, game_name, tag_line):
    """Input shortcut: instead of typing 10 champion names by hand, read them from a player's
    live game (Spectator-V5). Once both teams are extracted, the live game itself is no longer
    used — neither its state (kills, gold, timers) nor its outcome; only the 10 champion names
    matter, exactly as for a hand-typed composition. This does not change the product contract
    (a hypothetical composition as input), only how it is entered.

    Raises ValueError if the player is not currently in a game."""
    puuid = riot_client.get_puuid(game_name, tag_line)
    game = riot_client.get_active_game(puuid)
    if game is None:
        raise ValueError(f"{game_name}#{tag_line} n'est pas en partie actuellement.")

    id_to_name = get_champion_id_to_name()

    me = next(p for p in game["participants"] if p["puuid"] == puuid)
    my_team_id = me["teamId"]

    your_team = []
    enemy_team = []
    for p in game["participants"]:
        champion_name = id_to_name[str(p["championId"])]
        if p["teamId"] == my_team_id:
            your_team.append(champion_name)
        else:
            enemy_team.append(champion_name)

    return your_team, enemy_team
