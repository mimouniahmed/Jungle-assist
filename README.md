# Jungle Assist — League of Legends game plans from a team composition

🇫🇷 [Version française](README.fr.md)

[![tests](https://github.com/mimouniahmed/Jungle-assist/actions/workflows/tests.yml/badge.svg)](https://github.com/mimouniahmed/Jungle-assist/actions/workflows/tests.yml)
![Python 3.12](https://img.shields.io/badge/python-3.12-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

An **end-to-end** data pipeline: **12,482 ranked matches** collected from the Riot Games API, an **XGBoost** win-prediction model, **SHAP** explainability, and a natural-language **game plan** written by an LLM (Claude API).

**Question**: given a composition (5 champions vs 5), which in-game facts should a team focus on, and through which champion?

```
Riot API ──► SQLite ──► pandas ──► XGBoost + SHAP ──► per-composition ──► LLM ──► CLI
(ingestion)  (raw)     (features)   (model)          fact ranking           (game plan)
```

## Key results

| | |
|---|---|
| **Data** | 12,482 matches collected by *snowball sampling*, 12,346 of them valid 5v5 games, i.e. **123,460 rows** (match × player) and 173 champions |
| **Model** | XGBoost on 27 early-game facts + champion + role, 60/20/20 split **by match** |
| **Performance (test)** | Accuracy **0.780**, ROC-AUC **0.860**, F1 0.786, log loss 0.465, Brier 0.152 (naive baseline: 0.50) |
| **Calibration** | Near-perfect: when the model predicts a 70% win chance, the team actually wins ~70% of the time |
| **Explainability** | Global SHAP importance + **champion × fact interactions** (4,844 pairs), aggregated into a ranking specific to each composition |
| **Product** | A CLI that takes 10 champions, typed in or read from a live game, and returns a reasoned game plan |

<p align="center">
  <img src="docs/figures/shap_importance.png" alt="Global SHAP importance of in-game facts" width="48%">
  <img src="docs/figures/calibration.png" alt="Model calibration curve" width="40%">
</p>

## Technical highlights

- **Detecting and fixing data leakage**, the trickiest part of the project:
  - `maxKillDeficit` was always 0 for the losing team, so the field nearly encoded the outcome. The detection rule was generalised to every field instead of being handled case by case;
  - a first model that looked too good (AUC 0.887) was dominated by `earliestBaron`. Baron only spawns at 20:00 (2026 patch, verified), so this field could never be an early-game fact: it was a classification error, not a signal. After the fix, AUC drops to 0.860 and importance is spread across legitimate facts;
  - `turretPlatesTaken` was assumed to stop at 14 min, but patch 26.01 removed that limit. Confirmed empirically (up to 41 plates in the data), the field was excluded.
- **Separating causes from consequences**: a winning team piles up towers and kills *because it is already winning*. The model therefore only uses early-game facts (before ~20 min), selected from 128 Riot fields.
- **Granularity matched to the question**: one row per (match, player) rather than per team, to keep the champion ↔ fact link. "Team" and "player" fields are told apart empirically, since Riot does not document them.
- **Rigorous evaluation**: `GroupShuffleSplit` on `match_id`, so the 10 rows of a match never straddle train and test. Hyperparameter search on the validation set with early stopping, then a single evaluation on the test set.
- **From SHAP attribution to advice**: for a hypothetical composition, the facts are not observed. The ranking combines global importance with the **strongest** interaction among the 5 champions (the maximum rather than the sum, which diluted the signal), producing advice such as "prioritise this fact, through this champion".
- **Robust ingestion**: a Riot client with **proactive** rate limiting (sliding window, 100 calls / 120 s) and retry on `429`, a collection BFS that resumes where it stopped, and filtering of off-topic modes (Arena, ARAM).
- **A first approach dropped for a stated reason**: a Factorization Machine on champion embeddings. Its symmetric counter term (`dot(A,B) = dot(B,A)`) cannot carry any signal when the blue/red side assignment is arbitrary.
- **Engineering**: an installable Python package, a `lol-assistant` command, input validation (a typo returns the closest champion name), network-free `pytest` tests, and GitHub Actions CI.

➡️ **[Detailed technical log](docs/journal.md)** (every decision, error and fix, phase by phase) · **[Power BI exploration guide](docs/powerbi_guide.md)**

> The notebooks, the technical log, and the CLI and generated game plans are in French.

## Usage example

```
$ lol-assistant
=== Jungle Assist — plan de jeu ===

1. Saisir les deux compositions à la main
2. Récupérer la composition depuis la partie en cours d'un joueur (Riot ID)
Choix [1/2] : 1
Votre équipe (5 champions séparés par des virgules) : Jayce, Sylas, Yone, Yunara, Lulu
Équipe adverse (5 champions séparés par des virgules) : Darius, Lee Sin, Ahri, Jinx, Thresh
```

For this team, the ranking highlights `voidMonsterKill` (through Jayce), `firstTurretKilledTime` (Yone), the level lead in lane (Sylas), first dragon and vision advantage (Lulu). The LLM turns this ranking, together with the enemy team's, into a written game plan.

## Installation

```bash
git clone https://github.com/mimouniahmed/Jungle-assist.git
cd Jungle-assist
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -e ".[dev]"
cp .env.example .env       # fill in RIOT_API_KEY and ANTHROPIC_API_KEY
pytest                     # unit tests, no network or key needed
```

The data (`data/`: SQLite database, model, SHAP artefacts) is not versioned. To rebuild it, run `python scripts/collect_dataset.py <hours>`, then `notebooks/03_model_training.ipynb`, which produces the model and the SHAP artefacts read by the CLI.

## Project structure

```
├── lol_assistant/               # Python package
│   ├── riot_client.py           # Riot API client (Account, Match-V5, Spectator-V5)
│   ├── rate_limiter.py          # proactive sliding-window rate limiting
│   ├── database.py              # SQLite storage (raw JSON, deduplication)
│   ├── crawler.py               # snowball collection (BFS), game-mode filter
│   ├── game_plan.py             # per-composition fact ranking + prompt + LLM
│   ├── live_game.py             # composition read from a live game
│   └── cli.py                   # command-line interface
├── notebooks/
│   ├── 01_riot_api_basics.ipynb       # Riot API exploration
│   ├── 02_dataset_collection.ipynb    # collection pipeline
│   ├── 03_model_training.ipynb        # features, leakage, XGBoost, SHAP
│   └── 04_llm_game_plan.ipynb         # game plan generation
├── scripts/collect_dataset.py   # long-running, time-bounded collection
├── tests/                       # pytest tests (no network)
└── docs/                        # technical log, Power BI guide, figures
```

## Limitations

- The rankings reflect **correlations** learned on EUW solo queue, not causal effects. Some lane indicators (`maxLevelLeadLaneOpponent`) are still partly consequences of a lane going well.
- The LLM supplements the data with its general knowledge of the game, so the final plan is not 100% traceable to the statistics.
- A documented next step (see the log): rebuild the features from the Timeline API (snapshots at 10, 15 and 20 min) rather than from Riot's `challenges` aggregates.

## License

[MIT](LICENSE) © 2026 Ahmed Mimouni.

---

**Ahmed Mimouni** · [ahmedmimouni.fr](https://ahmedmimouni.fr) · [LinkedIn](https://www.linkedin.com/in/ahmed-mimouni-10b4413a2/) · [GitHub](https://github.com/mimouniahmed)
