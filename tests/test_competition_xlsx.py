import json
from pathlib import Path

import pytest
from openpyxl import load_workbook

from goai_data.competition_xlsx import ENTERPRISE_SHEETS, SimulatedCompetitionXlsxImporter, export_competition_xlsx
from goai_data.full_sandbox import FullCompetitionArena, FullFinancialDynamics, SeededHeuristicPolicy, generate_global_orders, generate_simulated_rule_pack


DATASET_ROOT = Path("/home/undefined/Disk/datasets/goai/processed/v2/matches")


def load_base(match_id: str) -> dict:
    match_dir = DATASET_ROOT / match_id
    path = match_dir / "rules_inferred_v2.json"
    if not path.exists():
        path = match_dir / "rules.json"
    return json.loads(path.read_text(encoding="utf-8"))


def run_small_match(base_match: str, seed: int = 100) -> tuple[dict, list[dict], FullCompetitionArena]:
    rules = generate_simulated_rule_pack(load_base(base_match), seed=seed, match_id=f"SIM_{base_match}", team_count=2, source_match_id=base_match)
    orders = generate_global_orders(rules, seed=seed + 1, orders_per_year=2)
    dynamics = FullFinancialDynamics(rules)
    arena = FullCompetitionArena(dynamics, rules["participants"]["team_ids"], orders)
    policies = {team_id: SeededHeuristicPolicy(team_id, seed) for team_id in arena.agent_ids}
    observations = arena.reset(seed=seed)
    while not arena.terminated:
        result = arena.step({team_id: policies[team_id].act(observations[team_id]) for team_id in arena.agent_ids})
        observations = result.observations
    return rules, orders, arena


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_every_normalized_match_can_be_used_as_a_random_generator_template() -> None:
    match_ids = sorted(path.name for path in DATASET_ROOT.iterdir() if path.is_dir())
    assert set(match_ids) >= {"AB", "AG", "CA", "CB", "CD", "CE", "EA", "EB", "EC", "EF", "LX_XA", "OP", "ZY", "ZZ"}
    for index, match_id in enumerate(match_ids):
        rules = generate_simulated_rule_pack(load_base(match_id), seed=200 + index, match_id=f"SIM_{match_id}", team_count=3, source_match_id=match_id)
        orders = generate_global_orders(rules, seed=300 + index, orders_per_year=1)
        state = FullFinancialDynamics(rules).initial_state(rules["participants"]["team_ids"][0], orders=orders)
        assert rules["generation"]["source_match_id"] == match_id
        assert rules["parent_rule_pack_id"] == load_base(match_id).get("rule_pack_id")
        assert rules["provenance"] == "simulated"
        assert len(orders) == 4
        assert abs(state.balance_gap_wan) <= 1e-6


@pytest.mark.parametrize("base_match", ["AB", "AG", "LX_XA"])
def test_competition_xlsx_round_trip_uses_visible_competition_tables(tmp_path: Path, base_match: str) -> None:
    rules, orders, arena = run_small_match(base_match)
    bundle = tmp_path / "bundle"
    manifest = export_competition_xlsx(bundle, rules=rules, orders=orders, arena=arena)
    assert manifest["team_count"] == 2
    assert manifest["order_count"] == len(orders)
    assert manifest["provenance"] == "simulated"

    for relative in manifest["files"]["enterprise"]:
        workbook = load_workbook(bundle / relative, data_only=True)
        assert tuple(name for name in workbook.sheetnames if not name.startswith("_")) == ENTERPRISE_SHEETS
        assert workbook["现金流量表"]["C3"].value == "动作"
        assert workbook["订单信息"]["B3"].value == "订单编号"
        assert workbook["三张报表"]["B2"].value == "年度"

    imported_dir = tmp_path / "imported"
    imported = SimulatedCompetitionXlsxImporter(bundle, imported_dir).import_bundle()
    teams = read_jsonl(imported_dir / "teams.jsonl")
    imported_orders = read_jsonl(imported_dir / "global_orders.jsonl")
    events = read_jsonl(imported_dir / "events.jsonl")
    reports = read_jsonl(imported_dir / "reports.jsonl")
    assert imported["counts"]["teams"] == len(arena.states)
    assert len(imported_orders) == len(orders)
    # 与真实“初始元年 + 第1年至第5年”六列布局一致。
    assert len(reports) == len(arena.states) * 6 * (len(range(3, 14)) + len(range(16, 27)) + len(range(30, 51)))
    assert all(row["provenance"] == "simulated" for row in teams + imported_orders + events + reports)

    final_cash = {team_id: state.cash_wan for team_id, state in arena.states.items()}
    imported_cash = {row["team_id"]: row["export_cash_wan"] for row in teams}
    assert imported_cash == pytest.approx(final_cash)
    by_team = {team_id: [] for team_id in final_cash}
    for event in events:
        by_team[event["team_id"]].append(event)
    for team_id, rows in by_team.items():
        rows.sort(key=lambda row: row["sequence_in_source"])
        assert rows[-1]["balance_wan"] == pytest.approx(final_cash[team_id])
        for previous, current in zip(rows, rows[1:]):
            assert previous["balance_wan"] + current["amount_wan"] == pytest.approx(current["balance_wan"])
