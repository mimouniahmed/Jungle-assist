from types import SimpleNamespace

import pandas as pd
import pytest

from lol_assistant.game_plan import (
    build_game_plan_prompt,
    composition_fact_ranking,
    generate_game_plan,
)

TEAM = ["Jayce", "Sylas", "Yone", "Yunara", "Lulu"]
ENEMY = ["Darius", "Lee Sin", "Ahri", "Jinx", "Thresh"]


@pytest.fixture
def artifacts():
    global_importance = pd.Series(
        {"firstTurretKilledTime": 0.6, "voidMonsterKill": 0.5, "visionScoreAdvantageLaneOpponent": 0.1,
         "champion": 0.2, "role": 0.05},
        name="mean_abs_shap",
    )
    rows = []
    for champ in TEAM + ENEMY:
        for feat in global_importance.index:
            rows.append({"champion": champ, "feature": feat, "mean_abs_interaction": 0.01})
    interactions = pd.DataFrame(rows)
    # Lulu depends heavily on vision: enough to push that fact to the top
    interactions.loc[
        (interactions.champion == "Lulu") & (interactions.feature == "visionScoreAdvantageLaneOpponent"),
        "mean_abs_interaction",
    ] = 0.9
    return global_importance, interactions


def test_ranking_uses_max_champion_not_sum(artifacts):
    ranking = composition_fact_ranking(TEAM, *artifacts)
    top = ranking.iloc[0]
    assert top.feature == "visionScoreAdvantageLaneOpponent"
    assert top.key_champion == "Lulu"
    assert top.team_importance == pytest.approx(0.1 + 0.9)


def test_ranking_excludes_non_fact_columns(artifacts):
    ranking = composition_fact_ranking(TEAM, *artifacts)
    assert not {"champion", "role"} & set(ranking.feature)


def test_wrong_team_size_is_rejected(artifacts):
    with pytest.raises(ValueError, match="exactement 5"):
        composition_fact_ranking(TEAM[:4], *artifacts)


def test_typo_suggests_closest_champion(artifacts):
    with pytest.raises(ValueError, match="Lulu"):
        composition_fact_ranking(TEAM[:4] + ["Lullu"], *artifacts)


def test_prompt_mentions_both_teams_and_key_champion(artifacts):
    your_ranking = composition_fact_ranking(TEAM, *artifacts)
    enemy_ranking = composition_fact_ranking(ENEMY, *artifacts)
    prompt = build_game_plan_prompt(TEAM, ENEMY, your_ranking, enemy_ranking)
    assert "Jayce" in prompt and "Thresh" in prompt
    assert "surtout via Lulu" in prompt


def test_generate_game_plan_with_fake_client(tmp_path, artifacts):
    global_importance, interactions = artifacts
    global_importance.rename_axis("feature").reset_index().to_csv(tmp_path / "global_shap_importance.csv", index=False)
    interactions.to_csv(tmp_path / "champion_feature_interactions.csv", index=False)

    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text="Plan de jeu")])

    fake_client = SimpleNamespace(messages=SimpleNamespace(create=create))
    text, your_ranking, _ = generate_game_plan(TEAM, ENEMY, client=fake_client, data_dir=tmp_path)

    assert text == "Plan de jeu"
    assert your_ranking.iloc[0].key_champion == "Lulu"
    assert "Jayce" in calls[0]["messages"][0]["content"]
