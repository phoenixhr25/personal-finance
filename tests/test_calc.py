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
    # 「推算总资产」2026-10-16 起各层按各自利率推算（引擎核对 #7），不再与基线相同；
    # 其余数字都不变。新值用公式显式核对，见 test_projection_uses_each_layers_own_rate。
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


# ── 审阅发现的回归 ───────────────────────────────────────────────────────
def test_blank_contrib_end_and_blank_retire_date_do_not_crash():
    """缴费到留空时默认取停止工作日期；再清空停止工作日期，不能 TypeError。"""
    cfg = demo_cfg()
    cfg["pension"].pop("contrib_end")
    cfg["global"].pop("date_retire")
    p = calc.compute_plan(cfg, TODAY)
    assert p.error is None
    assert p.assets_ready and not p.pension_ready and not p.retire_ready
    miss = [i for i in p.missing if i.path == ("global", "date_retire")]
    assert miss and "缴费" in miss[0].message           # 说明为什么需要它
    assert p.pension["npv"] == 0 and not p.npv_complete


def test_retire_date_is_only_a_pension_prerequisite_when_contrib_end_is_blank():
    cfg = demo_cfg()
    cfg["global"].pop("date_retire")
    p = calc.compute_plan(cfg, TODAY)                    # 示例里填了缴费到
    assert p.pension_ready and not p.retire_ready


def test_contrib_end_missing_everywhere_is_defended_in_calc():
    cfg = demo_cfg()
    cfg["pension"].pop("contrib_end")
    cfg["global"].pop("date_retire")
    # 即使绕过缺失项判断，缴费月数也按 0 处理，不会崩溃
    import calc as c
    plan = c.compute_plan(cfg, TODAY)
    assert plan.error is None


def test_unknown_city_is_a_located_missing_item_not_a_keyerror():
    cfg = demo_cfg()
    cfg["pension"]["city"] = "苏州"
    p = calc.compute_plan(cfg, TODAY)
    assert p.error is None and not p.pension_ready
    miss = [i for i in p.missing if i.path == ("pension", "city")]
    assert miss and "苏州" in miss[0].message and "其他" in miss[0].message


def test_city_presets_match_config_validation_list():
    from config_io import CITY_NAMES
    assert set(calc.CITY_BASES) == set(CITY_NAMES)


def test_import_warns_about_unknown_city():
    raw = wrap_export(calc.cfg_for_export(demo_cfg()))
    raw["pension"]["city"] = "苏州"
    clean, warnings = validate_config(raw)
    assert any("苏州" in w and "其他" in w for w in warnings)
    assert clean["pension"]["city"] == "苏州"           # 不替用户改，由界面提示改选


def test_failed_plan_keeps_issues_and_reports_error():
    cfg = demo_cfg()
    cfg["sim"]["monthly_expense"] = None
    p = calc.failed_plan(cfg, ValueError("boom"), TODAY)
    assert p.error == "ValueError: boom" and not p.retire_ready
    assert any(i.path == ("sim", "monthly_expense") for i in p.missing)


def test_single_field_extremes_never_crash_the_calc():
    """配置层允许的每个字段取极值、清空，以及日期两两组合，测算都不应抛异常。"""
    from config_io import _INS_SPEC, _SPEC
    import itertools
    base = demo_cfg()
    bad = []

    def run(label, cfg):
        try:
            calc.compute_plan(cfg, TODAY)
        except Exception as e:                          # noqa: BLE001
            bad.append((label, repr(e)))

    for sec, spec in _SPEC.items():
        for key, sp in spec.items():
            kind = sp[0]
            if kind in ("f", "i"):
                cands = [sp[1], sp[2], (sp[1] + sp[2]) / 2]
            elif kind == "d":
                cands = ["1940-01-01", "2026-10-11", "2100-12-31"]
            elif kind == "b":
                cands = [True, False]
            elif kind == "s":
                cands = ["苏州", ""]
            else:
                continue
            for c in cands:
                if key == "retire_age" and c not in (50, 55, 60):
                    continue
                cfg = copy.deepcopy(base)
                cfg[sec][key] = c
                run(f"{sec}.{key}={c!r}", cfg)
    for key, sp in _INS_SPEC.items():
        if sp[0] in ("f", "i"):
            for c in (sp[1], sp[2]):
                cfg = copy.deepcopy(base)
                cfg["insurance"][0][key] = c
                run(f"insurance.{key}={c!r}", cfg)
    for sec in ("global", "pension", "hpf", "snapshots", "sim"):
        for key in list(base[sec]):
            cfg = copy.deepcopy(base)
            cfg[sec][key] = None
            run(f"{sec}.{key}=None", cfg)
    for k1, k2 in itertools.combinations(["date_retire", "date_pension_start", "date_life_end"], 2):
        for v1, v2 in itertools.product(("1940-01-01", "2100-12-31"), repeat=2):
            cfg = copy.deepcopy(base)
            cfg["global"][k1], cfg["global"][k2] = v1, v2
            run(f"{k1}={v1},{k2}={v2}", cfg)
    assert bad == []


# ── 引擎核对 #7：退休推算按各层利率 ───────────────────────────────────────
def test_projection_uses_each_layers_own_rate(plan):
    y = plan.years_to_retire
    cfg = demo_cfg()
    acct, hpf = cfg["pension"]["account"], cfg["hpf"]["balance"]
    pen_rate = plan.assumptions["account_rate"][0]
    expected_pen = acct * (1 + pen_rate) ** y + hpf * 1.025 ** y
    assert plan.snap_ret["pension_hpf"] == pytest.approx(expected_pen)
    dep = plan.dep_list
    rate = sum(d["balance"] * d["rate"] for d in dep) / sum(d["balance"] for d in dep)
    assert plan.snap_ret["cash"] == pytest.approx(plan.snap_now["cash"] * (1 + rate) ** y)
    assert plan.snap_ret["investment"] == pytest.approx(
        plan.snap_now["investment"] * (1 + plan.assumptions["proj_invest_rate"][0]) ** y)


def test_projection_depends_on_account_rate_not_a_fixed_55_percent():
    lo, hi = demo_cfg(), demo_cfg()
    lo["pension"]["rate"], hi["pension"]["rate"] = 0.015, 0.055
    a = calc.compute_plan(lo, TODAY).snap_ret["pension_hpf"]
    b = calc.compute_plan(hi, TODAY).snap_ret["pension_hpf"]
    assert b > a


def test_projection_without_deposits_has_zero_cash_rate():
    cfg = demo_cfg()
    cfg["deposits"] = ""
    p = calc.compute_plan(cfg, TODAY)
    assert p.snap_ret["cash"] == 0


# ── 引擎核对 #8：赤字不再被清零 ───────────────────────────────────────────
def deficit_cfg():
    cfg = demo_cfg()
    cfg["sim"].update({"monthly_income": 0.0, "monthly_expense": 60000.0})
    return cfg


def test_uncovered_deficit_is_kept_as_negative_cash_and_reported():
    p = calc.compute_plan(deficit_cfg(), TODAY)
    h = p.headline
    assert h["uncovered"] > 0 and h["uncovered_from"] is not None
    assert h["liquid_real"] < 0                       # 流动资产被赤字拉成负数
    # 没有被清零：把赤字加回去，等于不亏的资产
    assert h["nominal"] < p.snap_ret["pension_hpf"] + p.snap_ret["insurance"]


def test_no_uncovered_deficit_in_the_demo():
    p = calc.compute_plan(demo_cfg(), TODAY)
    assert all(s["uncovered"] == 0 for s in p.scenarios if s.get("available"))
    assert all(s["uncovered"] == 0 for s in p.stress)


def test_stress_also_reports_uncovered_deficit():
    p = calc.compute_plan(deficit_cfg(), TODAY)
    assert any(s["uncovered"] > 0 for s in p.stress)


# ── 取不到行情：按成本价计，列内标注 ─────────────────────────────────────────
def test_rows_marked_when_price_falls_back_to_cost():
    cfg = demo_cfg()
    cfg["stocks"] = "600036,100,35.0,2023-06-01\n510300,200,4.0,2023-06-01,4.5"   # 第二行有手填当前价
    p = calc.compute_plan(cfg, TODAY, fund_lookup=lambda c: {}, stock_lookup=lambda c: {})
    marked = [r["category"] for r in p.rows if "按成本价计" in r["category"]]
    assert len(marked) == 1 and "600036" in marked[0]
    assert p.price_failed == ["600036"]


def test_rows_not_marked_when_prices_available():
    p = calc.compute_plan(demo_cfg(), TODAY)
    assert not any("按成本价计" in r["category"] for r in p.rows)


# ── 快速估算模式 ─────────────────────────────────────────────────────────
def quick_cfg_from(full_plan):
    """用完整示例的数字拼一份快速估算配置：三个合计数 + 手填月领（取完整示例推算出的月领）。"""
    cfg = demo_cfg()
    snap = full_plan.snap_now
    q = calc.empty_cfg()
    q["mode"] = "quick"
    q["global"] = {"date_retire": cfg["global"]["date_retire"]}
    q["pension"] = {"birth": cfg["pension"]["birth"], "retire_age": cfg["pension"]["retire_age"],
                    "monthly": full_plan.pension_real}
    q["sim"] = {k: cfg["sim"][k] for k in ("retire_expense_mo", "monthly_income", "monthly_expense")}
    q["quick"] = {"investment": snap["investment"], "cash": snap["cash"],
                  "locked": snap["pension_hpf"] + snap["insurance"]}
    return q


def test_quick_mode_asks_for_nine_items_and_computes_nothing_until_filled():
    q = calc.empty_cfg()
    q["mode"] = "quick"
    p = calc.compute_plan(q, TODAY)
    assert p.quick and len(p.missing) == 9 and not p.assets_ready
    assert calc.required_progress(q) == {calc.GROUP_QUICK: (0, 9), "_all": (0, 9)}
    assert calc.groups_for(q) == (calc.GROUP_QUICK,)
    assert all(i.group == calc.GROUP_QUICK for i in p.missing)


def test_quick_mode_uses_the_same_target_as_the_full_mode(plan):
    q = quick_cfg_from(plan)
    p = calc.compute_plan(q, TODAY)
    assert p.quick and p.retire_ready and not p.missing
    assert p.target["total"] == pytest.approx(plan.target["total"])        # 同一把尺子
    assert p.target["bridge_months"] == plan.target["bridge_months"]
    # 简化只影响资产增长：公积金、储蓄险并入个人账户后统一按记账利率，结果比完整填写保守
    assert p.headline["real"] < plan.headline["real"]
    assert p.headline["real"] > plan.headline["real"] * 0.9


def test_quick_mode_unfilled_vs_zero_totals():
    q = quick_cfg_from(calc.compute_plan(demo_cfg(), TODAY))
    q["quick"]["cash"] = None
    p = calc.compute_plan(q, TODAY)
    assert [i.path for i in p.missing] == [("quick", "cash")] and not p.assets_ready
    q["quick"]["cash"] = 0.0                       # 明确填 0
    assert calc.compute_plan(q, TODAY).retire_ready


def test_quick_mode_does_not_invent_a_pension():
    q = quick_cfg_from(calc.compute_plan(demo_cfg(), TODAY))
    q["pension"]["monthly"] = None
    p = calc.compute_plan(q, TODAY)
    assert not p.pension_ready and any(i.path == ("pension", "monthly") for i in p.missing)


def test_quick_mode_date_prerequisites_are_located():
    q = quick_cfg_from(calc.compute_plan(demo_cfg(), TODAY))
    q["pension"].pop("birth")
    miss = calc.compute_plan(q, TODAY).missing
    assert [i.path for i in miss] == [("global", "date_pension_start")]
    q["global"]["date_pension_start"] = "2045-03-01"     # 没有出生年月时手填
    assert calc.compute_plan(q, TODAY).retire_ready


def test_effective_cfg_makes_explicit_simplifications():
    q = quick_cfg_from(calc.compute_plan(demo_cfg(), TODAY))
    eff = calc.effective_cfg(q)
    assert eff["pension"]["auto"] is False and eff["insurance"] == [] and eff["stocks"] == ""
    assert eff["hpf"]["balance"] == 0.0
    assert eff["funds_dca"].startswith(calc.QUICK_FUND_LABEL)
    assert eff["deposits"].startswith(calc.QUICK_CASH_LABEL)
    assert calc.effective_cfg(demo_cfg()) is not None and calc.effective_cfg(demo_cfg())["mode"] is None


def test_quick_to_full_carries_what_it_can_and_asks_for_the_rest():
    q = quick_cfg_from(calc.compute_plan(demo_cfg(), TODAY))
    full = calc.quick_to_full(q)
    assert full["mode"] == "full"
    assert calc.QUICK_FUND_LABEL in full["funds_dca"] and calc.QUICK_CASH_LABEL in full["deposits"]
    assert full["pension"]["auto"] is False and full["pension"]["monthly"] == q["pension"]["monthly"]
    miss = {i.path for i in calc.compute_plan(full, TODAY).missing}
    # 社保、公积金、保险需要拆开填；不替用户拆
    assert ("pension", "account") in miss and ("hpf", "balance") in miss and ("insurance",) in miss
    assert q["mode"] == "quick"                    # 原配置不被修改


def test_mode_survives_export_import_and_v2_files_still_load():
    q = quick_cfg_from(calc.compute_plan(demo_cfg(), TODAY))
    raw = json.loads(json.dumps(wrap_export(calc.cfg_for_export(q))))
    assert raw["schema_version"] == 3 and raw["mode"] == "quick"
    clean, _ = validate_config(raw)
    back = calc.cfg_from_clean(clean)
    assert back["mode"] == "quick" and back["quick"] == q["quick"]
    v2 = wrap_export(calc.cfg_for_export(demo_cfg()))
    v2["schema_version"] = 2
    v2.pop("mode"); v2.pop("quick")
    assert calc.cfg_from_clean(validate_config(v2)[0])["mode"] is None


def test_invalid_mode_is_rejected():
    from config_io import ConfigError
    raw = wrap_export(calc.cfg_for_export(demo_cfg()))
    raw["mode"] = "turbo"
    with pytest.raises(ConfigError):
        validate_config(raw)
