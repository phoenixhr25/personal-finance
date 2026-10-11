"""共享测算：与改版前的基线逐项对账，并检查目标口径统一、缺失项、边界情况。

基线 tests/fixtures/baseline_before_redesign.json 来自改版前（commit 2588a07）的页面，
输入是 examples/demo_config.json（虚构数据），日期固定为基线当天。
"""
import copy
import json
import os
from datetime import date

import pytest

import calc
from config_io import validate_config, wrap_export
from test_config_io import sample_export

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE = json.load(open(os.path.join(ROOT, "tests", "fixtures", "baseline_before_redesign.json"),
                          encoding="utf-8"))
TODAY = date.fromisoformat(BASELINE["today"])


def demo_cfg():
    clean, _ = validate_config(json.load(open(os.path.join(ROOT, "examples", "demo_config.json"),
                                              encoding="utf-8")))
    return calc.cfg_from_clean(clean)


def money(x):
    return f"¥{x:,.0f}"


@pytest.fixture(scope="module")
def plan():
    return calc.compute_plan(demo_cfg(), today=TODAY)


def metric(label):
    return next(m["value"] for m in BASELINE["metrics"] if m["label"] == label)


# ── 与改版前逐项对账 ─────────────────────────────────────────────────────
def test_overview_metrics_unchanged(plan):
    assert money(plan.total_mv) == metric("当前总资产")
    assert money(plan.total_npv) == metric("NPV")
    assert money(plan.eaa_month) == metric("等值月均")
    assert money(sum(plan.snap_ret.values())) == metric("2037 推算总资产")
    assert f"{plan.w_return:.2%}" == metric("加权年化")


def test_pension_and_target_unchanged(plan):
    t = plan.target
    assert money(plan.pension_real) == metric("养老金月领（今日购买力）")
    assert money(t["phase2"]) == metric("调整后4%目标") == metric("养老期补充目标")
    assert money(t["bridge_cost"]) == metric("过渡期消耗")
    assert f"{t['bridge_months']} 个月" == metric("过渡期")


def test_scenario_table_unchanged(plan):
    old = BASELINE["dataframes"][4]["rows"]            # 情景 | 现金耗尽 | 名义 | 今日购买力 | 退休缺口
    for s, row in zip(plan.scenarios, old):
        assert money(s["nominal"]) == row[2]
        assert money(s["real"]) == row[3]
        # 旧「退休缺口」是相对未扣养老金 4% 参考值的缺口，现在放在「方法对照」
        old_gap = max(0.0, plan.ref4 - s["real"])
        assert ("无" if old_gap == 0 else money(old_gap)) == row[4]
        assert ("不耗尽" if s["cash_depl"] is None else str(s["cash_depl"])[:7]) == row[1]


def test_pension_view_unchanged(plan):
    old = BASELINE["dataframes"][5]["rows"]
    for s, row in zip(plan.scenarios, old):
        assert money(s["liquid_real"]) == row[1]
        assert f"{s['liquid_real'] / plan.target['phase2']:.1f}x" == row[3]


def test_stress_table_unchanged(plan):
    old = BASELINE["dataframes"][6]["rows"]
    for s, row in zip(plan.stress, old):
        assert money(s["real"]) == row[1]
        assert money(s["liquid_real"]) == row[3]
        cov = "∞" if s["old_coverage"] == float("inf") else f"{s['old_coverage']:.1f}x"
        assert cov == row[4]


def test_asset_rows_unchanged(plan):
    old_mv = [r[1] for d in BASELINE["dataframes"][:4] for r in d["rows"]]
    assert [money(r["market_value"]) for r in plan.rows] == old_mv


# ── 目标口径统一 ─────────────────────────────────────────────────────────
def test_every_scenario_uses_the_same_target(plan):
    totals = {s["target"] for s in plan.scenarios if s.get("available")}
    assert totals == {plan.target["total"]}
    assert plan.stress[0]["target"] == plan.target["total"]
    assert plan.stress[0]["margin"] == pytest.approx(plan.headline["margin"])


def test_pension_shock_recomputes_target(plan):
    shock = next(s for s in plan.stress if s["label"] == "养老金打七折")
    base = plan.target
    gap = max(0.0, plan.retire_expense - plan.pension_real * 0.7)
    assert shock["target"] == pytest.approx(base["bridge_cost"] + gap * 12 / 0.04)
    assert shock["target"] > base["total"]          # 养老金变少，目标变高
    assert shock["real"] == pytest.approx(plan.headline["real"])   # 资产不受影响


def test_ref4_is_not_called_a_gap(plan):
    assert plan.ref4 == pytest.approx(plan.retire_expense * 300)
    assert "ref4_diff" in plan.scenarios[0]
    assert "gap" not in plan.scenarios[0]


# ── 必填项：未填写 ≠ 填 0 ───────────────────────────────────────────────
def test_empty_config_reports_missing_and_computes_nothing():
    p = calc.compute_plan(calc.empty_cfg(), today=TODAY)
    assert not p.assets_ready and not p.retire_ready
    assert p.scenarios == [] and p.target is None
    labels = " ".join(i.label for i in p.missing)
    for must in ("计划停止工作日期", "个人账户余额", "公积金余额", "保单数量", "每月税后收入"):
        assert must in labels


def test_unfilled_vs_explicit_zero():
    cfg = demo_cfg()
    cfg["sim"]["monthly_expense"] = None
    assert any(i.path == ("sim", "monthly_expense") for i in calc.compute_plan(cfg, TODAY).missing)
    cfg["sim"]["monthly_expense"] = 0.0
    assert not any(i.path == ("sim", "monthly_expense") for i in calc.compute_plan(cfg, TODAY).missing)


def test_holdings_unfilled_vs_none_declared():
    cfg = demo_cfg()
    cfg["deposits"] = None
    assert any(i.path == ("deposits",) for i in calc.compute_plan(cfg, TODAY).missing)
    cfg["deposits"] = ""        # 勾选「暂无」
    p = calc.compute_plan(cfg, TODAY)
    assert not any(i.path == ("deposits",) for i in p.missing)
    assert p.snap_now["cash"] == 0


def test_insurance_none_vs_zero_policies():
    cfg = demo_cfg()
    cfg["insurance"] = None
    assert any(i.path == ("insurance",) for i in calc.compute_plan(cfg, TODAY).missing)
    cfg["insurance"] = []
    assert calc.compute_plan(cfg, TODAY).retire_ready


def test_policy_field_missing_is_located():
    cfg = demo_cfg()
    cfg["insurance"][0]["maturity_value"] = None
    miss = calc.compute_plan(cfg, TODAY).missing
    assert [i.path for i in miss] == [("insurance", 0, "maturity_value")]
    assert "保单 1" in miss[0].label


def test_no_default_standing_in_for_user_facts():
    cfg = calc.empty_cfg()
    cfg["global"]["date_retire"] = "2037-01-01"
    p = calc.compute_plan(cfg, TODAY)
    assert p.assets_ready is False and p.headline is None


def test_assumptions_marked_default_when_blank():
    cfg = demo_cfg()
    cfg["global"].pop("inflation")
    p = calc.compute_plan(cfg, TODAY)
    assert p.assumptions["inflation"] == (0.025, True)
    assert p.assumptions["discount_rate"][1] is False      # 示例里填了


# ── 边界情况 ─────────────────────────────────────────────────────────────
def edit(**changes):
    cfg = demo_cfg()
    for path, v in changes.items():
        sec, key = path.split("__")
        cfg[sec][key] = v
    return calc.compute_plan(cfg, TODAY)


def test_zero_target_has_no_percentage():
    p = edit(sim__retire_expense_mo=0.0)
    assert p.target["total"] == 0
    assert p.headline["margin_pct"] is None
    assert all(s["margin_pct"] is None for s in p.stress)


def test_zero_inflation_means_deflator_one():
    p = edit(global__inflation=0.0)
    assert p.deflator == 1.0
    assert p.headline["real"] == pytest.approx(p.headline["nominal"])


def test_retire_date_already_passed():
    p = edit(global__date_retire="2020-01-01")
    assert p.retire_ready and p.deflator == 1.0
    assert p.headline["real"] == pytest.approx(p.snap_now["pension_hpf"] + p.snap_now["insurance"]
                                               + p.snap_now["investment"] + p.snap_now["cash"])


def test_empty_holdings_do_not_crash():
    cfg = demo_cfg()
    cfg["funds_dca"] = cfg["stocks"] = cfg["deposits"] = ""
    cfg["insurance"] = []
    p = calc.compute_plan(cfg, TODAY)
    assert p.retire_ready and p.investable_now == 0
    assert p.total_mv == p.snap_now["pension_hpf"]


def test_pension_before_stop_working_has_no_bridge():
    cfg = demo_cfg()
    cfg["pension"].pop("birth")
    cfg["global"]["date_pension_start"] = "2030-01-01"
    p = calc.compute_plan(cfg, TODAY)
    assert p.target["bridge_months"] == 0 and p.headline["liquid_ok"] is None


def test_semi_income_blank_skips_that_scenario_only():
    cfg = demo_cfg()
    cfg["sim"].pop("semi_income")
    p = calc.compute_plan(cfg, TODAY)
    assert p.retire_ready
    assert [s["available"] for s in p.scenarios] == [True, True, False]


def test_manual_pension_mode():
    p = edit(pension__auto=False, pension__monthly=5000.0)
    assert p.pension_mode == "manual" and p.pension_real == 5000.0


# ── 持仓文本 ─────────────────────────────────────────────────────────────
def test_parse_reports_bad_lines_with_numbers():
    items, bad = calc.parse_stocks("600036,100,35,2023-01-01\n坏行\n000001,x,1,2023-01-01\n"
                                   "000002，10，5，2023-13-01")
    assert len(items) == 1
    assert [n for n, _, _ in bad] == [2, 3, 4]


def test_parse_chinese_comma_and_blank_lines():
    items, bad = calc.parse_fund_dca("270023，3250.58，17111.57，20139.62\n\n")
    assert len(items) == 1 and not bad
    assert items[0]["manual_nav"] == pytest.approx(20139.62 / 3250.58)


def test_bad_lines_surface_as_nonblocking_problems():
    cfg = demo_cfg()
    cfg["stocks"] = "坏行"
    p = calc.compute_plan(cfg, TODAY)
    assert p.retire_ready and len(p.problems) == 1


# ── 配置往返与旧配置 ─────────────────────────────────────────────────────
def test_export_import_roundtrip_keeps_unfilled_as_unfilled():
    cfg = demo_cfg()
    cfg["sim"]["monthly_expense"] = None
    cfg["deposits"] = None
    cfg["insurance"] = None
    out = json.loads(json.dumps(wrap_export(calc.cfg_for_export(cfg)), ensure_ascii=False))
    clean, _ = validate_config(out)
    back = calc.cfg_from_clean(clean)

    def strip(c):       # None 与"没有这个键"都表示未填写
        return {k: ({a: b for a, b in v.items() if b is not None} if isinstance(v, dict) else v)
                for k, v in c.items()}
    assert strip(back) == strip(cfg)
    assert back["insurance"] is None and back["deposits"] is None
    assert [i.path for i in calc.compute_plan(back, TODAY).missing] == \
           [i.path for i in calc.compute_plan(cfg, TODAY).missing]


def test_roundtrip_complete_config_gives_same_results(plan):
    out = json.loads(json.dumps(wrap_export(calc.cfg_for_export(demo_cfg()))))
    clean, _ = validate_config(out)
    again = calc.compute_plan(calc.cfg_from_clean(clean), today=TODAY)
    assert again.total_npv == plan.total_npv
    assert again.headline["real"] == plan.headline["real"]


def test_legacy_config_without_version_still_loads():
    legacy = sample_export()                  # 旧格式：无 format / schema_version
    clean, notes = validate_config(legacy)
    assert any("旧版" in n for n in notes)
    p = calc.compute_plan(calc.cfg_from_clean(clean), today=TODAY)
    assert p.assets_ready


def test_legacy_retire_age_65_migrates():
    legacy = {"format": "personal-finance-config", "schema_version": 1, **sample_export()}
    legacy["pension"]["retire_age"] = 65
    clean, notes = validate_config(legacy)
    assert clean["pension"]["retire_age"] == 60 and any("65" in n for n in notes)


# ── 必填项进度 ───────────────────────────────────────────────────────────
def test_required_progress_counts_filled_and_total():
    full = calc.required_progress(demo_cfg())
    done, total = full["_all"]
    assert done == total and total > 0
    assert all(f == t for g, (f, t) in full.items() if g != "_all")
    empty = calc.required_progress(calc.empty_cfg())
    assert empty["_all"][0] == 0 and empty["_all"][1] > 0


def test_progress_and_missing_list_agree():
    cfg = demo_cfg()
    cfg["sim"]["monthly_expense"] = None
    cfg["deposits"] = None
    done, total = calc.required_progress(cfg)["_all"]
    assert total - done == len(calc.compute_plan(cfg, TODAY).missing) == 2


def test_policy_fields_add_to_total():
    cfg = demo_cfg()
    base = calc.required_progress(cfg)["_all"][1]
    cfg["insurance"] = cfg["insurance"] + [{}]
    assert calc.required_progress(cfg)["_all"][1] == base + len(calc.INS_FIELDS)
