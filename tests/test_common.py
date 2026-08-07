from goai_data.common import parse_duration, parse_money_wan, parse_period


def test_parse_money_wan() -> None:
    assert parse_money_wan("-75W") == -75
    assert parse_money_wan("10W/年") == 10
    assert parse_money_wan(42.0) == 42
    assert parse_money_wan("") is None


def test_parse_period() -> None:
    assert parse_period("第5年4季") == (5, 4)
    assert parse_period("第2年") == (2, None)
    assert parse_period("Y3Q2") == (3, 2)
    assert parse_period("初始元年") == (0, 0)
    assert parse_period("-") == (None, None)


def test_parse_duration() -> None:
    assert parse_duration("3季") == (3, "quarter", False)
    assert parse_duration("4年") == (4, "year", False)
    assert parse_duration("-") == (0, None, True)
    assert parse_duration("") == (None, None, False)
