from goai_data.rulepack import (
    ACTION_CONTROL_TYPES,
    AGENT_CANDIDATE_ACTIONS,
    canonicalize_action,
    parse_action_parameters,
)


def test_historical_action_parameter_parsing() -> None:
    assert canonicalize_action("Buy_Material", "historical") == "material_order"
    parameters, status = parse_action_parameters(
        "Buy_Material", "订购原料 R1:2 R2:3 R4:1", "historical"
    )
    assert status == "complete"
    assert parameters == {"materials": {"R1": 2, "R2": 3, "R4": 1}}

    parameters, status = parse_action_parameters(
        "Long_Loan", "申请:4年 400W的长期贷款", "historical"
    )
    assert status == "complete"
    assert parameters == {"term": 4, "term_unit": "year", "principal_wan": 400}


def test_test_scenario_pattern_mapping() -> None:
    assert canonicalize_action("按订单交货(0q)", "test") == "order_delivery"
    parameters, status = parse_action_parameters("贴现34q(面值)", None, "test")
    assert status == "partial"
    assert parameters == {"receivable_terms": [3, 4]}


def test_decision_and_settlement_are_distinct() -> None:
    assert ACTION_CONTROL_TYPES["material_order"] == "direct_decision"
    assert ACTION_CONTROL_TYPES["material_receipt_payment"] == "committed_settlement"
    assert ACTION_CONTROL_TYPES["tax_payment"] == "automatic_settlement"
    assert ACTION_CONTROL_TYPES["order_award"] == "external_outcome"
    assert "order_award" not in AGENT_CANDIDATE_ACTIONS
    assert "capital_injection" not in AGENT_CANDIDATE_ACTIONS
    assert "emergency_material_purchase" in AGENT_CANDIDATE_ACTIONS
