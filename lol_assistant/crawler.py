import time
from collections import deque

import requests

from . import database

WANTED_GAME_MODE = "CLASSIC"  # excludes ARAM, Arena (CHERRY), URF... — classic 5v5 Summoner's Rift only


def crawl_matches(riot_client, conn, seed_puuids, target_count, matches_per_player=10, max_duration_seconds=None):
    if isinstance(seed_puuids, str):
        seed_puuids = [seed_puuids]

    start_time = time.time()
    queue = deque(seed_puuids)
    collected = 0

    def time_is_up():
        return max_duration_seconds is not None and (time.time() - start_time) >= max_duration_seconds

    while queue and collected < target_count and not time_is_up():
        puuid = queue.popleft()

        if database.player_already_explored(conn, puuid):
            continue
        database.mark_player_explored(conn, puuid)

        try:
            match_ids = riot_client.get_match_ids(puuid, count=matches_per_player)
        except requests.HTTPError as exc:
            print(f"Erreur pour le joueur {puuid} ({exc}), on passe.")
            continue

        for match_id in match_ids:
            if collected >= target_count or time_is_up():
                break
            if database.match_already_collected(conn, match_id):
                continue

            try:
                match_data = riot_client.get_match_detail(match_id)
            except requests.HTTPError as exc:
                print(f"Erreur pour le match {match_id} ({exc}), on passe.")
                continue

            # snowball: the 10 participants of this match become new seeds, whether or not
            # the match is kept (they are real players, whatever the game mode)
            for participant_puuid in match_data["metadata"]["participants"]:
                if not database.player_already_explored(conn, participant_puuid):
                    queue.append(participant_puuid)

            if match_data["info"].get("gameMode") != WANTED_GAME_MODE:
                continue  # off-topic (ARAM, Arena...): no reason to store it

            database.save_match(conn, match_id, riot_client.region, match_data)
            collected += 1

            if collected % 10 == 0:
                print(f"{collected}/{target_count} matchs collectés...")

    if time_is_up():
        reason = "temps écoulé"
    elif collected >= target_count:
        reason = "objectif atteint"
    else:
        reason = "file d'attente épuisée"

    print(f"Terminé ({reason}) : {collected} matchs collectés, {len(queue)} joueurs encore en attente dans la file.")
