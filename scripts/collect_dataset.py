"""Large-scale collection: restarts snowball sampling from every player already seen in
data/matches.db but never explored, for a maximum duration rather than a fixed number of
matches.

Usage: python scripts/collect_dataset.py [hours] [db_path]
"""
import json
import sys

from lol_assistant.crawler import crawl_matches
from lol_assistant.database import get_connection
from lol_assistant.riot_client import RiotClient

DB_PATH = sys.argv[2] if len(sys.argv) > 2 else "data/matches.db"
HOURS = float(sys.argv[1]) if len(sys.argv) > 1 else 3.0


def find_unexplored_seeds(conn):
    explored = {row[0] for row in conn.execute("SELECT puuid FROM explored_players")}

    candidates = set()
    for (raw_json,) in conn.execute("SELECT raw_json FROM matches"):
        match_data = json.loads(raw_json)
        candidates.update(match_data["metadata"]["participants"])

    return sorted(candidates - explored)


def main():
    conn = get_connection(DB_PATH)
    client = RiotClient(region="europe")

    seeds = find_unexplored_seeds(conn)
    print(f"{len(seeds)} graines non explorées trouvées dans {DB_PATH}.")

    if not seeds:
        print("Aucune graine disponible, arrêt.")
        return

    print(f"Lancement pour {HOURS}h, cible large (100000 matchs, le temps sera la vraie limite)...")
    crawl_matches(
        client,
        conn,
        seed_puuids=seeds,
        target_count=100_000,
        max_duration_seconds=int(HOURS * 3600),
    )


if __name__ == "__main__":
    main()
