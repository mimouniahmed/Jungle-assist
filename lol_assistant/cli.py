"""Interface en ligne de commande (phase 5) : demande une composition — à la main ou depuis
une partie en cours — puis génère et affiche le plan de jeu via generate_game_plan. Assemble
uniquement des briques déjà industrialisées (game_plan.py, live_game.py, riot_client.py),
aucune nouvelle logique métier ici."""

import anthropic
import requests

from .game_plan import generate_game_plan
from .live_game import get_composition_from_active_game
from .riot_client import RiotClient


def _prompt_team(label):
    raw = input(f"{label} (5 champions séparés par des virgules) : ")
    return [name.strip() for name in raw.split(",")]


def _prompt_manual_composition():
    your_team = _prompt_team("Votre équipe")
    enemy_team = _prompt_team("Équipe adverse")
    return your_team, enemy_team


def _prompt_live_composition():
    riot_id = input("Riot ID (pseudo#tag, ex: Spear Shot#1111) : ").strip()
    game_name, _, tag_line = riot_id.partition("#")
    client = RiotClient()
    return get_composition_from_active_game(client, game_name, tag_line)


def main():
    print("=== Jungle Assist — plan de jeu ===\n")
    print("1. Saisir les deux compositions à la main")
    print("2. Récupérer la composition depuis la partie en cours d'un joueur (Riot ID)")
    mode = input("Choix [1/2] : ").strip()

    while True:
        try:
            if mode == "2":
                your_team, enemy_team = _prompt_live_composition()
            else:
                your_team, enemy_team = _prompt_manual_composition()

            print("\nGénération du plan de jeu (appel Claude)...\n")
            game_plan_text, _, _ = generate_game_plan(your_team, enemy_team)
            print(game_plan_text)
            break
        except ValueError as e:
            print(f"\nErreur : {e}\n")
            retry = input("Réessayer ? [o/n] : ").strip().lower()
            if retry != "o":
                break
        except requests.exceptions.RequestException as e:
            print(f"\nErreur d'appel à l'API Riot (clé invalide ou expirée ? voir .env) : {e}\n")
            break
        except anthropic.AnthropicError as e:
            print(f"\nErreur d'appel à l'API Claude (clé invalide ? voir .env) : {e}\n")
            break
        except FileNotFoundError as e:
            print(f"\nArtefact du modèle manquant : {e}\n"
                  "(voir README, section phase 3 — data/ n'est pas versionné, à copier ou régénérer)\n")
            break


if __name__ == "__main__":
    main()
