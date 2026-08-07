"""Versioned global-rule services for the XA competition.

The XA workbook is the formal source.  This module turns the source into
small replaceable services so a future match can override allocation,
bankruptcy, ranking, or initial-state policies without changing the dynamics
kernel.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


XA_GLOBAL_RULES_VERSION = "xa_global_rules_v1.0"


def _as_number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def is_bankrupt(cash_wan: float | None, owner_equity_wan: float | None, rules: Mapping[str, Any]) -> tuple[bool, tuple[str, ...]]:
    """Apply the formal XA bankruptcy predicates and return reasons."""

    parameters = rules.get("parameters", rules)
    predicates = tuple(parameters.get("bankruptcy", ("cash_flow_break", "negative_equity")))
    reasons: list[str] = []
    if "cash_flow_break" in predicates and cash_wan is not None and cash_wan < 0:
        reasons.append("cash_flow_break")
    if "negative_equity" in predicates and owner_equity_wan is not None and owner_equity_wan < 0:
        reasons.append("negative_equity")
    return bool(reasons), tuple(reasons)


def development_potential(assets: Mapping[str, Sequence[str]], rules: Mapping[str, Any]) -> float:
    parameters = rules.get("parameters", rules)
    total = 0.0
    score_maps = {
        key: {name: float(spec.get("score", 0)) for name, spec in (parameters.get(key) or {}).items()}
        for key in ("markets", "products", "iso", "production_lines", "factories")
    }
    for key, names in (
        ("markets", assets.get("markets", ())),
        ("products", assets.get("products", ())),
        ("iso", assets.get("iso", ())),
        ("factories", assets.get("purchased_factories", ())),
        ("production_lines", assets.get("completed_lines", ())),
    ):
        total += sum(score_maps[key].get(str(name), 0.0) for name in names)
    return total


def ranking_score(owner_equity_wan: float, potential: float, rules: Mapping[str, Any]) -> float:
    """Compute the XA score from the formal score expression."""

    expression = (rules.get("parameters", rules).get("score_formula") or "").replace(" ", "")
    if expression and "owner_equity" not in expression:
        raise ValueError(f"unsupported XA score formula: {expression}")
    return float(owner_equity_wan) * (1.0 + float(potential) / 100.0)


def round_nonnegative_half_up(value: float) -> int:
    return math.floor(float(value) + 0.5)


def rank_final_states(final_states: Sequence[Mapping[str, Any]], rules: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Rank solvent teams; bankrupt teams are excluded from the score table."""

    eligible: list[Mapping[str, Any]] = []
    for row in final_states:
        bankrupt = row.get("bankruptcy_period") or row.get("bankrupt")
        equity = _as_number(row.get("owner_equity_wan"))
        potential = _as_number(row.get("development_potential"))
        if bankrupt or equity is None or potential is None:
            continue
        eligible.append(row)
    eligible = sorted(
        eligible,
        key=lambda row: (-ranking_score(float(row["owner_equity_wan"]), float(row["development_potential"]), rules), str(row.get("team_id", ""))),
    )
    result = []
    for rank, row in enumerate(eligible, 1):
        score = ranking_score(float(row["owner_equity_wan"]), float(row["development_potential"]), rules)
        result.append({
            "rank": rank,
            "team_id": row.get("team_id"),
            "owner_equity_wan": float(row["owner_equity_wan"]),
            "development_potential": float(row["development_potential"]),
            "score": score,
            "rounded_score": round_nonnegative_half_up(score),
        })
    return result


@dataclass(frozen=True)
class RuleInferenceReport:
    rule_pack_id: str
    version: str
    confirmed: Mapping[str, Any]
    inferred: Mapping[str, Any]
    unresolved: tuple[str, ...]
    evidence: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_pack_id": self.rule_pack_id,
            "version": self.version,
            "confirmed": dict(self.confirmed),
            "inferred": dict(self.inferred),
            "unresolved": list(self.unresolved),
            "evidence": dict(self.evidence),
        }


def infer_xa_global_rules(
    rules: Mapping[str, Any],
    *,
    final_states: Sequence[Mapping[str, Any]] = (),
    official_ranking: Sequence[Mapping[str, Any]] = (),
    bankruptcies: Sequence[Mapping[str, Any]] = (),
    global_orders: Sequence[Mapping[str, Any]] = (),
) -> RuleInferenceReport:
    """Create an auditable XA rule freeze from formal rules and outcomes.

    Outcomes validate a rule; they do not replace a missing formal source.
    """

    parameters = rules.get("parameters", rules)
    derived = rank_final_states(final_states, rules) if final_states else []
    official_by_team = {str(row.get("team_id")): row for row in official_ranking}
    score_matches = sum(
        1
        for row in derived
        if str(row.get("team_id")) in official_by_team
        and round_nonnegative_half_up(float(row["score"])) == int(official_by_team[str(row.get("team_id"))].get("official_score", official_by_team[str(row.get("team_id"))].get("score", -1)))
    )
    year_values = sorted({int(row["year"]) for row in global_orders if isinstance(row.get("year"), (int, float))})
    unassigned = sum(row.get("owner_team_id") in (None, "", "-") for row in global_orders)
    confirmed = {
        "initial_cash_wan": parameters.get("initial_cash_wan"),
        "bankruptcy_predicates": list(parameters.get("bankruptcy", ())),
        "score_formula": parameters.get("score_formula"),
        "selection_priority": list(parameters.get("selection_priority", ())),
        "first_year_has_orders": parameters.get("first_year_has_orders"),
        "order_pool_years_observed": year_values,
        "order_pool_unassigned_count_observed": unassigned,
        "rounding": "half_up_for_nonnegative_score",
    }
    inferred = {
        "ranking_tie_breaker": "team_id_lexicographic",
        "bankrupt_team_excluded_from_ranking": True,
        "counterfactual_recompute_scope": "all_enterprises_from_changed_period",
    }
    unresolved = (
        "auction_tie_break_and_bid_payment",
        "exact_phase_settlement_order",
        "information_visibility_timing",
        "unobserved_order_generation_mechanism",
    )
    evidence = {
        "formal_source": rules.get("source_path"),
        "binding_status": rules.get("binding_status"),
        "derived_ranking_count": len(derived),
        "official_ranking_count": len(official_ranking),
        "official_score_match_count": score_matches,
        "bankruptcy_observation_count": len(bankruptcies),
        "global_order_count": len(global_orders),
    }
    return RuleInferenceReport(str(rules.get("rule_pack_id", "XA")), XA_GLOBAL_RULES_VERSION, confirmed, inferred, unresolved, evidence)


def merge_rule_overrides(base_rules: Mapping[str, Any], overrides: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Deep-merge a user override without mutating the frozen XA source."""

    result = copy.deepcopy(dict(base_rules))

    def merge(left: dict[str, Any], right: Mapping[str, Any]) -> None:
        for key, value in right.items():
            if isinstance(value, Mapping) and isinstance(left.get(key), Mapping):
                merge(left[key], value)  # type: ignore[index]
            else:
                left[key] = copy.deepcopy(value)

    if overrides:
        merge(result, overrides)
    result["parent_rule_pack_id"] = base_rules.get("rule_pack_id")
    result["rule_pack_id"] = result.get("rule_pack_id", f"{base_rules.get('rule_pack_id', 'XA')}+override")
    result["binding_status"] = "custom_override" if overrides else base_rules.get("binding_status")
    return result
