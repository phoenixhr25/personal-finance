"""config_io 的单元测试。运行：pip install pytest && python -m pytest"""
import copy
import math

import pytest

from config_io import (CONFIG_FORMAT, SCHEMA_VERSION, ConfigError, migrate,
                       validate_config, wrap_export)


def sample_export(auto=True):
    """与 app.py 导出结构一致的示例（虚构数据）。"""
    return {
        "global": {"discount_rate": 0.03, "proj_invest_rate": 0.05,
                   "date_retire": "2040-01-01", "date_pension_start": "2043-01-01",
                   "date_life_end": "2080-01-01", "date_base_1": "2020-01-01",
                   "date_base_2": "2023-01-01"},
        "pension": ({"account": 100000.0, "monthly": 5000.0, "rate": 0.055, "auto": True,
                     "city": "深圳", "city_wage": 12500.0, "wage_growth": 0.04,
                     "contrib_years": 20, "contrib_index": 1.0, "retire_age": 60}
                    if auto else
                    {"account": 100000.0, "monthly": 3000.0, "rate": 0.055, "auto": False,
                     "city": None, "city_wage": None, "wage_growth": None,
                     "contrib_years": None, "contrib_index": None, "retire_age": None}),
        "hpf": {"balance": 80000.0, "years": 10.0},
        "insurance": [{"name": "储蓄险1", "cash_value": 50000.0, "cost_basis": 50000.0,
                       "annual_premium": 0.0, "premium_years_left": 0,
                       "maturity_value": 50000.0, "years_to_maturity": 5, "policy_irr": 0.03}],
        "funds_dca": "000001, 100, 1000, 1100",
        "stocks": "600036,100,35.00,2023-01-01",
        "deposits": "某银行,活期,50000,0.002",
        "snapshots": {"b1_ph": 50000.0, "b1_ins": 10000.0, "b1_inv": 30000.0, "b1_csh": 50000.0,
                      "b2_ph": 120000.0, "b2_ins": 30000.0, "b2_inv": 100000.0, "b2_csh": 100000.0},
        "sim": {"monthly_income": 19000.0, "monthly_expense": 11000.0,
                "retire_expense_mo": 8000.0, "semi_income": 10000.0,
                "income_interrupt_months": 12, "target_ph": 30, "target_ins": 15,
                "target_inv": 40, "target_csh": 15},
    }


def test_current_export_roundtrip():
    clean, warns = validate_config(wrap_export(sample_export()))
    assert clean["global"]["discount_rate"] == 0.03
    assert clean["pension"]["retire_age"] == 60
    assert clean["insurance"][0]["years_to_maturity"] == 5
    assert clean["funds_dca"].startswith("000001")
    assert warns == []


def test_null_fields_are_dropped_not_kept():
    clean, _ = validate_config(wrap_export(sample_export(auto=False)))
    p = clean["pension"]
    assert p["auto"] is False and p["monthly"] == 3000.0
    for k in ("city", "city_wage", "wage_growth", "contrib_years", "contrib_index", "retire_age"):
        assert k not in p


def test_legacy_file_without_version_is_migrated():
    legacy = sample_export()
    legacy["funds"] = legacy.pop("funds_dca")
    clean, warns = validate_config(legacy)
    assert clean["funds_dca"].startswith("000001")
    assert "funds" not in clean
    assert any("旧版" in w for w in warns)


def test_migrate_keeps_existing_funds_dca_over_funds():
    data, _ = migrate({"funds": "旧", "funds_dca": "新"})
    assert data["funds_dca"] == "新" and "funds" not in data


def test_migrate_does_not_mutate_input():
    raw = {"funds": "x"}
    before = copy.deepcopy(raw)
    migrate(raw)
    assert raw == before


def test_future_version_rejected():
    with pytest.raises(ConfigError, match="更新版本"):
        validate_config({"format": CONFIG_FORMAT, "schema_version": SCHEMA_VERSION + 1})


@pytest.mark.parametrize("bad", ["1", 1.5, True, 0, -1])
def test_bad_schema_version_rejected(bad):
    with pytest.raises(ConfigError):
        validate_config({"schema_version": bad})


def test_wrong_format_rejected():
    with pytest.raises(ConfigError, match="不是本工具"):
        validate_config({"format": "something-else"})


@pytest.mark.parametrize("raw", [[], "x", 3, None])
def test_top_level_must_be_object(raw):
    with pytest.raises(ConfigError):
        validate_config(raw)


def test_out_of_range_and_type_errors_are_all_reported():
    cfg = wrap_export(sample_export())
    cfg["global"]["discount_rate"] = 5          # 超范围
    cfg["pension"]["rate"] = "0.05"             # 类型错
    cfg["hpf"]["balance"] = -1                  # 负数
    with pytest.raises(ConfigError) as e:
        validate_config(cfg)
    joined = "；".join(e.value.problems)
    assert "global.discount_rate" in joined
    assert "pension.rate" in joined
    assert "hpf.balance" in joined
    assert len(e.value.problems) == 3


@pytest.mark.parametrize("age", [58, 0, 70])
def test_retire_age_must_be_a_selectable_value(age):
    cfg = wrap_export(sample_export())
    cfg["pension"]["retire_age"] = age
    with pytest.raises(ConfigError):
        validate_config(cfg)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
def test_non_finite_numbers_rejected(bad):
    cfg = wrap_export(sample_export())
    cfg["pension"]["account"] = bad
    with pytest.raises(ConfigError):
        validate_config(cfg)
    assert not math.isfinite(bad)


def test_bool_is_not_a_number():
    cfg = wrap_export(sample_export())
    cfg["hpf"]["balance"] = True
    with pytest.raises(ConfigError):
        validate_config(cfg)


def test_integer_fields_reject_fractions_but_accept_integral_floats():
    cfg = wrap_export(sample_export())
    cfg["pension"]["contrib_years"] = 20.0
    clean, _ = validate_config(cfg)
    assert clean["pension"]["contrib_years"] == 20 and isinstance(clean["pension"]["contrib_years"], int)
    cfg["pension"]["contrib_years"] = 20.5
    with pytest.raises(ConfigError, match="整数"):
        validate_config(cfg)


def test_invalid_date_rejected():
    cfg = wrap_export(sample_export())
    cfg["global"]["date_retire"] = "2040-13-01"
    with pytest.raises(ConfigError, match="date_retire"):
        validate_config(cfg)


def test_date_order_only_warns():
    cfg = wrap_export(sample_export())
    cfg["global"]["date_retire"] = "2050-01-01"
    clean, warns = validate_config(cfg)
    assert clean["global"]["date_retire"] == "2050-01-01"
    assert any("日期顺序" in w for w in warns)


def test_too_many_policies_rejected():
    cfg = wrap_export(sample_export())
    cfg["insurance"] = cfg["insurance"] * 6
    with pytest.raises(ConfigError, match="最多"):
        validate_config(cfg)


def test_policy_field_errors_carry_index():
    cfg = wrap_export(sample_export())
    cfg["insurance"][0]["cash_value"] = -5
    with pytest.raises(ConfigError, match=r"insurance\[0\]\.cash_value"):
        validate_config(cfg)


def test_text_fields_must_be_short_strings():
    cfg = wrap_export(sample_export())
    cfg["stocks"] = 123
    with pytest.raises(ConfigError, match="stocks"):
        validate_config(cfg)
    cfg["stocks"] = "x" * 20_001
    with pytest.raises(ConfigError, match="过长"):
        validate_config(cfg)


def test_unknown_fields_are_ignored_with_warning():
    cfg = wrap_export(sample_export())
    cfg["surprise"] = 1
    cfg["global"]["extra"] = 2
    clean, warns = validate_config(cfg)
    assert "surprise" not in clean and "extra" not in clean["global"]
    assert any("surprise" in w for w in warns) and any("global.extra" in w for w in warns)


def test_partial_config_is_accepted():
    clean, _ = validate_config(wrap_export({"hpf": {"balance": 1000}}))
    assert clean == {"hpf": {"balance": 1000.0}}


def test_validate_does_not_mutate_input():
    cfg = wrap_export(sample_export())
    before = copy.deepcopy(cfg)
    validate_config(cfg)
    assert cfg == before


def test_wrap_export_puts_format_and_version_first():
    out = wrap_export({"hpf": {}})
    assert list(out)[:2] == ["format", "schema_version"]
    assert out["schema_version"] == SCHEMA_VERSION


# ── 输入框上下限与导入校验共用同一组范围 ─────────────────────────────────────

from config_io import _INS_SPEC, _SPEC, bounds  # noqa: E402


@pytest.mark.parametrize("section,key", [(s, k) for s, spec in _SPEC.items()
                                         for k, v in spec.items() if v[0] in ("f", "i")]
                         + [("insurance", k) for k, v in _INS_SPEC.items() if v[0] in ("f", "i")])
def test_bounds_match_validator(section, key):
    lo, hi = bounds(section, key)
    kind = (_INS_SPEC if section == "insurance" else _SPEC[section])[key][0]
    assert lo < hi
    assert type(lo) is type(hi) is (int if kind == "i" else float)


def test_discount_rate_upper_bound_blocks_overflow_inputs():
    lo, hi = bounds("global", "discount_rate")
    assert (lo, hi) == (0.0, 0.30)
    cfg = wrap_export(sample_export())
    cfg["global"]["discount_rate"] = 999
    with pytest.raises(ConfigError, match="discount_rate"):
        validate_config(cfg)


def test_v1_retire_age_65_migrates_to_60():
    cfg = sample_export()
    cfg["pension"]["retire_age"] = 65
    cfg = {"format": "personal-finance-config", "schema_version": 1, **cfg}
    clean, notes = validate_config(cfg)
    assert clean["pension"]["retire_age"] == 60
    assert any("65" in n for n in notes)


def test_v2_fields_roundtrip():
    cfg = wrap_export(sample_export())
    assert cfg["schema_version"] == 2
    cfg["global"]["inflation"] = 0.025
    cfg["pension"]["birth"] = "1984-07-01"
    cfg["pension"]["contrib_end"] = "2036-01-01"
    clean, _ = validate_config(cfg)
    assert clean["global"]["inflation"] == 0.025
    assert clean["pension"]["birth"] == "1984-07-01"


def test_v2_rejects_65_and_bad_inflation():
    cfg = wrap_export(sample_export())
    cfg["pension"]["retire_age"] = 65
    cfg["global"]["inflation"] = 0.5
    with pytest.raises(ConfigError) as e:
        validate_config(cfg)
    assert len(e.value.problems) == 2
