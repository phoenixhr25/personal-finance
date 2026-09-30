"""finance_engine 的数学核对。

所有输入都是虚构数据。
- 普通测试：与独立手算或闭式解对照，应当通过。
- xfail(strict=True)：已确认的引擎缺陷（见 local-docs 的引擎核对记录）。
  修复后测试会"意外通过"并报错，提醒把标记去掉。
"""
from datetime import date

import pytest

import finance_engine as fe

TODAY = date(2026, 9, 30)


# ---------- 数学基本件 ----------

def test_pv_annuity_matches_loop():
    pmt, rate, n, delay = 1000.0, 0.03, 120, 12
    r = rate / 12
    # 逐笔折现：第 k 笔（k=1..n）在第 delay+k 个月末
    looped = sum(pmt / (1 + r) ** (delay + k) for k in range(1, n + 1))
    assert fe.pv_annuity(pmt, rate, n, delay) == pytest.approx(looped)


def test_pv_annuity_zero_rate_is_sum():
    assert fe.pv_annuity(500, 0.0, 24) == 12000
    assert fe.pv_annuity(500, 0.0, 24, delay_months=6) == 12000


def test_pv_lump():
    assert fe.pv_lump(1000, 0.05, 0) == 1000
    assert fe.pv_lump(1102.5, 0.05, 2) == pytest.approx(1000)


def test_annualized_and_cagr_roundtrip():
    assert fe.annualized_return(1210, 1000, 2) == pytest.approx(0.10)
    assert fe.cagr(1000, 1210, 2) == pytest.approx(0.10)
    assert fe.annualized_return(1000, 0, 2) == 0.0
    assert fe.cagr(0, 100, 2) == 0.0
    assert fe.cagr(1000, 1100, 0) == 0.0


def test_eaa_inverse_of_annuity_factor():
    npv, rate, years = 10000.0, 0.04, 10
    pvifa = (1 - (1 + rate) ** -years) / rate
    assert fe.eaa(npv, rate, years) * pvifa == pytest.approx(npv)


def test_eaa_zero_rate():
    assert fe.eaa(1000, 0.0, 10) == pytest.approx(100)


# ---------- 养老金公式 ----------

def test_distribution_months_official_values():
    assert fe.DISTRIBUTION_MONTHS == {50: 195, 55: 170, 60: 139, 65: 101}


def test_auto_pension_hand_worked():
    # 零增长、零利息：只剩公式本身
    # 基础 = 10000 × (1+1.0)/2 × 30 × 1% = 3000；个人账户 139000/139 = 1000
    got = fe.auto_monthly_pension(139000, 0.0, 0, 10000, 0.0, 30, 1.0, retire_age=60)
    assert got == pytest.approx(4000)


def test_auto_pension_retire_age_changes_divisor():
    a = fe.auto_monthly_pension(100000, 0, 0, 0, 0, 0, 1.0, retire_age=50)
    b = fe.auto_monthly_pension(100000, 0, 0, 0, 0, 0, 1.0, retire_age=65)
    assert a == pytest.approx(100000 / 195)
    assert b == pytest.approx(100000 / 101)


def test_auto_pension_growth_compounds():
    got = fe.auto_monthly_pension(0, 0, 10, 10000, 0.05, 15, 1.0, retire_age=60)
    assert got == pytest.approx(10000 * 1.05 ** 10 * 15 * 0.01 * 1.0)


# ---------- compute_pension ----------

PENSION = {"monthly_pension": 10000.0, "account_annual_return": 0.03}


def test_compute_pension_matches_pv_annuity():
    d_ret, d_end = date(2040, 1, 1), date(2080, 1, 1)
    res = fe.compute_pension(PENSION, 0.03, d_ret, d_end, TODAY)
    assert res["npv"] == pytest.approx(
        fe.pv_annuity(10000, 0.03, res["receive_m"], res["delay_m"]))


def test_compute_pension_calendar_months():
    res = fe.compute_pension(PENSION, 0.03, date(2040, 1, 1), date(2080, 1, 1), TODAY)
    assert res["receive_m"] == 480


def test_months_between_day_boundary():
    assert fe.months_between(date(2026, 9, 30), date(2026, 10, 29)) == 0
    assert fe.months_between(date(2026, 9, 30), date(2026, 10, 30)) == 1
    assert fe.months_between(date(2030, 1, 1), date(2026, 1, 1)) == 0


def test_compute_pension_counts_from_pension_start():
    # 核对 #1：传入领金日，退休到领金之间的过渡期不计养老金
    d_start, d_end = date(2043, 1, 1), date(2080, 1, 1)
    res = fe.compute_pension(PENSION, 0.03, d_start, d_end, TODAY)
    assert res["receive_m"] == 444
    assert res["delay_m"] == fe.months_between(TODAY, d_start)


def test_compute_pension_already_receiving():
    # 领金日已过：从今天起算剩余月数，不做负折现
    res = fe.compute_pension(PENSION, 0.03, date(2020, 1, 1), date(2030, 9, 30), TODAY)
    assert res["delay_m"] == 0
    assert res["receive_m"] == 48


# ---------- 公积金 ----------

def test_hpf_growth_and_discount():
    p = {"balance": 100000.0, "annual_rate": 0.025, "expected_use_years": 10}
    res = fe.compute_hpf(p, 0.025)
    assert res["future_value"] == pytest.approx(100000 * 1.025 ** 10)
    assert res["npv"] == pytest.approx(100000)  # 增长率等于折现率


# ---------- 保险 ----------

INS = {"cash_value": 40000.0, "cost_basis": 30000.0, "annual_premium": 5000.0,
       "premium_years_left": 3, "maturity_value": 60000.0, "years_to_maturity": 5,
       "policy_irr": 0.03}


def test_insurance_premium_pv_positive_rate():
    res = fe.compute_insurance([INS], 0.03)[0]
    pvifa = (1 - 1.03 ** -3) / 0.03
    assert res["pv_premiums"] == pytest.approx(5000 * pvifa)
    assert res["pv_maturity"] == pytest.approx(60000 / 1.03 ** 5)


def test_insurance_npv_excludes_cash_value():
    # 核对 #2：满期金已包含现金价值，NPV = 满期金现值 − 剩余缴费现值
    res = fe.compute_insurance([INS], 0.03)[0]
    assert res["npv"] == pytest.approx(res["pv_maturity"] - res["pv_premiums"])
    assert res["market_value"] == 40000  # 市值列仍显示现金价值


def test_insurance_premium_zero_rate():
    res = fe.compute_insurance([INS], 0.0)[0]
    assert res["pv_premiums"] == pytest.approx(15000)


# ---------- 基金 / 股票 ----------

def test_funds_basic_return():
    f = [{"cost_nav": 1.0, "current_nav": 1.21, "shares": 1000, "buy_date": date(2024, 9, 30)}]
    res = fe.compute_funds(f, TODAY)[0]
    assert res["market_value"] == pytest.approx(1210)
    assert res["cost_basis"] == pytest.approx(1000)
    assert res["return_pct"] == pytest.approx(0.21)
    years = (TODAY - date(2024, 9, 30)).days / 365.25
    assert res["annualized_return"] == pytest.approx(1.21 ** (1 / years) - 1)


def test_funds_without_buy_date_uses_total_return():
    f = [{"cost_nav": 1.0, "current_nav": 1.1, "shares": 100}]
    res = fe.compute_funds(f, TODAY)[0]
    assert res["annualized_return"] == pytest.approx(0.10)


def test_funds_nav_falls_back_to_cost():
    f = [{"cost_nav": 2.0, "current_nav": None, "shares": 50}]
    res = fe.compute_funds(f, TODAY)[0]
    assert res["market_value"] == pytest.approx(100)
    assert res["total_return"] == 0


def test_stocks_basic_return():
    s = [{"cost_price": 10.0, "current_price": 12.0, "shares": 100, "buy_date": date(2025, 9, 30)}]
    res = fe.compute_stocks(s, TODAY)[0]
    assert res["total_return"] == pytest.approx(200)
    assert res["return_pct"] == pytest.approx(0.2)


def test_short_holding_annualization_bounded():
    s = [{"cost_price": 10.0, "current_price": 10.1, "shares": 100, "buy_date": TODAY}]
    res = fe.compute_stocks(s, TODAY)[0]
    assert abs(res["annualized_return"]) < 10  # 即 1000%
    assert res["annualized_return"] == pytest.approx(0.01)


def test_short_holding_fund_uses_total_return():
    f = [{"cost_nav": 1.0, "current_nav": 1.01, "shares": 100, "buy_date": date(2026, 9, 20)}]
    res = fe.compute_funds(f, TODAY)[0]
    assert res["annualized_return"] == pytest.approx(0.01)
