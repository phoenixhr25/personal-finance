"""计算引擎：NPV / 年化 / EAA / CAGR"""
from datetime import date
import numpy as np


def pv_annuity(pmt, rate_annual, n_months, delay_months=0):
    r = rate_annual / 12
    if r == 0:
        pv = pmt * n_months
    else:
        pv = pmt * (1 - (1 + r) ** (-n_months)) / r
    return pv / (1 + r) ** delay_months


def pv_lump(fv, rate_annual, years):
    if years <= 0:
        return fv
    return fv / (1 + rate_annual) ** years


def eaa(npv, rate, years):
    if years <= 0:
        return npv
    if rate == 0:
        return npv / years
    pvifa = (1 - (1 + rate) ** (-years)) / rate
    return npv / pvifa


MIN_ANNUALIZE_YEARS = 1 / 12


def annualized_return(mv, cost, years):
    if years <= 0 or cost <= 0:
        return 0.0
    if years < MIN_ANNUALIZE_YEARS:
        return mv / cost - 1   # 持有不足一个月：年化会被放大到失真，退化为总收益率
    return (mv / cost) ** (1 / years) - 1


def cagr(v0, v1, years):
    if years <= 0 or v0 <= 0:
        return 0.0
    return (v1 / v0) ** (1 / years) - 1


# 个人账户养老金计发月数（国发〔2005〕38 号附件），键为退休时的满周岁年龄
ANNUITY_MONTHS = {
    40: 233, 41: 230, 42: 226, 43: 223, 44: 220, 45: 216, 46: 212, 47: 208,
    48: 204, 49: 199, 50: 195, 51: 190, 52: 185, 53: 180, 54: 175, 55: 170,
    56: 164, 57: 158, 58: 152, 59: 145, 60: 139, 61: 132, 62: 125, 63: 117,
    64: 109, 65: 101, 66: 93, 67: 84, 68: 75, 69: 65, 70: 56,
}
DISTRIBUTION_MONTHS = {a: ANNUITY_MONTHS[a] for a in (50, 55, 60, 65)}


def annuity_months(age_years):
    """计发月数。非整岁按满周岁取值（全国尚无统一的按月口径，取整最保守）"""
    return ANNUITY_MONTHS[min(70, max(40, int(age_years)))]


# 渐进式延迟退休（2025-01-01 起）：原法定年龄 -> (每几个月延迟 1 个月, 最多延迟月数)
DELAY_RULES = {60: (4, 36), 55: (4, 36), 50: (2, 60)}
REFORM_START = date(2025, 1, 1)


def statutory_retirement(birth, orig_age):
    """按出生年月和原法定退休年龄推算改革后的法定退休年龄（月）和退休年月（当月 1 日）"""
    step, cap = DELAY_RULES[orig_age]
    orig_idx = birth.year * 12 + birth.month - 1 + orig_age * 12
    m = orig_idx - (REFORM_START.year * 12 + REFORM_START.month - 1)
    delay = 0 if m < 0 else min(m // step + 1, cap)
    idx = orig_idx + delay
    return orig_age * 12 + delay, date(idx // 12, idx % 12 + 1, 1)


def auto_monthly_pension(personal_account, account_rate, years_to_retire,
                          city_avg_wage, wage_growth_rate,
                          contribution_years, contribution_index,
                          retire_age=60, contrib_months=0, base_growth_years=None):
    """按城镇职工基本养老保险公式推算领取当年的名义月领金额

    retire_age：领金时年龄（可为小数），按满周岁查计发月数。
    contrib_months：今后还会缴费的月数，每月按 计发基数 × 缴费指数 × 8% 记入个人账户。
    base_growth_years：计发基数从基准年增长到领金年的年数，缺省等于 years_to_retire。
    """
    if base_growth_years is None:
        base_growth_years = years_to_retire
    n = max(int(round(years_to_retire * 12)), 0)
    r_mo = (1 + account_rate) ** (1 / 12) - 1
    account_at_retire = personal_account * (1 + account_rate) ** years_to_retire
    for m in range(min(contrib_months, n)):
        deposit = city_avg_wage * (1 + wage_growth_rate) ** (m / 12) * contribution_index * 0.08
        account_at_retire += deposit * (1 + r_mo) ** (n - m - 1)
    wage_at_retire = city_avg_wage * (1 + wage_growth_rate) ** base_growth_years
    basic   = wage_at_retire * (1 + contribution_index) / 2 * contribution_years * 0.01
    personal_part = account_at_retire / annuity_months(retire_age)
    return basic + personal_part


def months_between(d1, d2):
    """d1 到 d2 的整日历月数（不足一个月的零头舍去），d2 早于 d1 时为 0"""
    m = (d2.year - d1.year) * 12 + (d2.month - d1.month)
    if d2.day < d1.day:
        m -= 1
    return max(m, 0)


def compute_pension(params, discount_rate, date_pension_start, date_life_end, today):
    """date_pension_start 是开始领养老金的日期（不是退休日，过渡期没有养老金）"""
    start     = max(date_pension_start, today)
    delay_m   = months_between(today, start)
    receive_m = months_between(start, date_life_end)
    npv = pv_annuity(params["monthly_pension"], discount_rate, receive_m, delay_months=delay_m)
    return {**params, "npv": npv, "annualized_return": params["account_annual_return"],
            "delay_m": delay_m, "receive_m": receive_m}


def compute_hpf(params, discount_rate):
    fv = params["balance"] * (1 + params["annual_rate"]) ** params["expected_use_years"]
    npv = pv_lump(fv, discount_rate, params["expected_use_years"])
    return {**params, "future_value": fv, "npv": npv, "annualized_return": params["annual_rate"],
            "cost_basis": params["balance"], "market_value": params["balance"]}


def compute_insurance(ins_list, discount_rate):
    result = []
    for ins in ins_list:
        pv_mat = pv_lump(ins["maturity_value"], discount_rate, ins["years_to_maturity"])
        pv_prem = 0.0
        n = ins["premium_years_left"]
        if n > 0:
            if discount_rate == 0:
                pv_prem = ins["annual_premium"] * n
            else:
                pvifa = (1 - (1 + discount_rate) ** (-n)) / discount_rate
                pv_prem = ins["annual_premium"] * pvifa
        # 持有到期只拿满期金，现金价值是退保才拿的钱，两者不能相加
        result.append({**ins, "pv_maturity": pv_mat, "pv_premiums": pv_prem,
                       "npv": pv_mat - pv_prem,
                       "annualized_return": ins["policy_irr"],
                       "market_value": ins["cash_value"], "cost_basis": ins["cost_basis"]})
    return result


def compute_funds(fund_list, today):
    result = []
    for f in fund_list:
        nav  = float(f.get("current_nav") or f["cost_nav"])
        shares = float(f["shares"])
        mv   = nav * shares
        cost = float(f["cost_nav"]) * shares
        ret_pct = (mv - cost) / cost if cost else 0
        if f.get("buy_date"):
            hold = max((today - f["buy_date"]).days / 365.25, 0.001)
            ann  = annualized_return(mv, cost, hold)
        else:
            hold = 0.0
            ann  = ret_pct   # 无买入日期：年化退化为总收益率
        result.append({**f, "nav": nav, "market_value": mv, "cost_basis": cost,
                       "total_return": mv - cost, "return_pct": ret_pct,
                       "annualized_return": ann, "holding_years": hold, "npv": mv})
    return result


def compute_stocks(stock_list, today):
    result = []
    for s in stock_list:
        price  = float(s.get("current_price") or s["cost_price"])
        shares = float(s["shares"])
        hold  = max((today - s["buy_date"]).days / 365.25, 0.001)
        mv    = price * shares
        cost  = float(s["cost_price"]) * shares
        result.append({**s, "current_price": price, "market_value": mv, "cost_basis": cost,
                       "total_return": mv - cost,
                       "return_pct": (mv - cost) / cost if cost else 0,
                       "annualized_return": annualized_return(mv, cost, hold),
                       "holding_years": hold, "npv": mv})
    return result


def compute_deposits(dep_list, discount_rate):
    result = []
    for d in dep_list:
        t  = d["term_years"]
        if t == 0:
            result.append({**d, "future_value": d["balance"],
                           "npv": d["balance"],
                           "annualized_return": d["rate"],
                           "cost_basis": d["balance"], "market_value": d["balance"]})
        else:
            fv = d["balance"] * (1 + d["rate"]) ** t
            result.append({**d, "future_value": fv,
                           "npv": pv_lump(fv, discount_rate, t),
                           "annualized_return": d["rate"],
                           "cost_basis": d["balance"], "market_value": d["balance"]})
    return result


def build_rows(pension, hpf, ins_list, fund_list, stock_list, dep_list):
    rows = []
    rows.append({"layer": "① 社会保障层", "category": "养老保险",
                 "market_value": pension["personal_account"], "cost_basis": pension["cost_basis"],
                 "npv": pension["npv"], "annual_return": pension["annualized_return"]})
    rows.append({"layer": "① 社会保障层", "category": "住房公积金",
                 "market_value": hpf["balance"], "cost_basis": hpf["cost_basis"],
                 "npv": hpf["npv"], "annual_return": hpf["annualized_return"]})
    for ins in ins_list:
        rows.append({"layer": "② 保险保障层", "category": f"储蓄险·{ins['name']}",
                     "market_value": ins["cash_value"], "cost_basis": ins["cost_basis"],
                     "npv": ins["npv"], "annual_return": ins["annualized_return"]})
    for f in fund_list:
        prefix = "定投" if not f.get("buy_date") else "基金"
        rows.append({"layer": "③ 投资层", "category": f"{prefix}·{f.get('name', f['code'])}",
                     "market_value": f["market_value"], "cost_basis": f["cost_basis"],
                     "npv": f["npv"], "annual_return": f["annualized_return"]})
    for s in stock_list:
        rows.append({"layer": "③ 投资层", "category": f"精确·{s.get('name', s['code'])}",
                     "market_value": s["market_value"], "cost_basis": s["cost_basis"],
                     "npv": s["npv"], "annual_return": s["annualized_return"]})
    for d in dep_list:
        rows.append({"layer": "④ 现金等价物层", "category": f"存款·{d['bank']}",
                     "market_value": d["balance"], "cost_basis": d["cost_basis"],
                     "npv": d["npv"], "annual_return": d["annualized_return"]})
    return rows


def weighted_avg_return(rows):
    total_cost = sum(r["cost_basis"] for r in rows)
    if total_cost == 0:
        return 0.0
    return sum(r["cost_basis"] / total_cost * r["annual_return"] for r in rows)


def retirement_projection(snap_now, proj_invest_rate, ins_list, y_to_retire):
    ins_irr = sum(i["policy_irr"] for i in ins_list) / max(len(ins_list), 1)
    return {
        "pension_hpf": snap_now["pension_hpf"] * (1 + 0.055) ** y_to_retire,
        "insurance":   snap_now["insurance"]   * (1 + ins_irr) ** y_to_retire,
        "investment":  snap_now["investment"]  * (1 + proj_invest_rate) ** y_to_retire,
        "cash":        snap_now["cash"]        * (1 + 0.025) ** y_to_retire,
    }


# ── V2 情景模拟 & 压力测试 ─────────────────────────────────────────────────

def _sim_params(pension, hpf, ins_list, fund_list, stock_list, dep_list,
                monthly_income, monthly_expense, retire_expense_mo,
                proj_invest_rate, today, date_retire, inflation=0.0):
    """inflation：把退休时的名义资产折回今日购买力，与按今天物价填写的支出、目标比较"""
    ins_irr = sum(i["policy_irr"] for i in ins_list) / max(len(ins_list), 1)
    years = max((date_retire - today).days / 365.25, 0)
    return dict(
        deflator      = (1 + inflation) ** years,
        cash          = sum(d["balance"]       for d in dep_list),
        investment    = sum(f["market_value"]  for f in fund_list)
                      + sum(s["market_value"]  for s in stock_list),
        pension_bal   = pension["personal_account"],
        pension_rate  = pension["account_annual_return"],
        monthly_pension = pension.get("monthly_pension_real", pension["monthly_pension"]),
        hpf_bal       = hpf["balance"],
        hpf_rate      = hpf["annual_rate"],
        ins_val       = sum(i["cash_value"]    for i in ins_list),
        ins_irr       = ins_irr,
        monthly_income    = monthly_income,
        monthly_expense   = monthly_expense,
        retire_expense_mo = retire_expense_mo,
        proj_rate     = proj_invest_rate,
        today         = today,
        date_retire   = date_retire,
    )


def run_scenario(name, income_schedule, p):
    from dateutil.relativedelta import relativedelta as _rd
    cash        = p["cash"]
    investment  = p["investment"]
    pension_bal = p["pension_bal"]
    hpf_bal     = p["hpf_bal"]
    ins_val     = p["ins_val"]

    r_p   = (1 + p["pension_rate"]) ** (1/12) - 1
    r_h   = (1 + p["hpf_rate"])     ** (1/12) - 1
    r_inv = (1 + p["proj_rate"])     ** (1/12) - 1
    r_ins = (1 + p["ins_irr"])       ** (1/12) - 1

    cash_depl = None
    cur = p["today"]
    while cur < p["date_retire"]:
        income = p["monthly_income"]
        for (fd, td, inc) in income_schedule:
            if fd <= cur < td:
                income = inc
                break
        pension_bal *= (1 + r_p)
        hpf_bal     *= (1 + r_h)
        investment  *= (1 + r_inv)
        ins_val     *= (1 + r_ins)
        cash += income - p["monthly_expense"]
        if cash < 0:
            if cash_depl is None:
                cash_depl = cur
            sell = min(-cash, investment)
            investment = max(investment - sell, 0)
            cash = 0
        cur += _rd(months=1)

    total    = pension_bal + hpf_bal + ins_val + investment + cash
    inv_cash = investment + cash
    defl     = p.get("deflator", 1.0)
    target   = p["retire_expense_mo"] * 12 / 0.04
    return dict(name=name, cash_depl=cash_depl,
                pension_2036=pension_bal, hpf_2036=hpf_bal,
                ins_2036=ins_val, invest_2036=investment,
                cash_2036=cash, total_2036=total,
                inv_cash=inv_cash,
                total_real=total / defl, inv_cash_real=inv_cash / defl,
                gap=max(0.0, target - total / defl))


def run_stress(label, p, investment_shock=1.0, inflation=0.0,
               proj_rate=None, pension_mult=1.0):
    from dateutil.relativedelta import relativedelta as _rd
    if proj_rate is None:
        proj_rate = p["proj_rate"]

    cash        = p["cash"]
    investment  = p["investment"] * investment_shock
    pension_bal = p["pension_bal"]
    hpf_bal     = p["hpf_bal"]
    ins_val     = p["ins_val"]

    r_p   = (1 + p["pension_rate"]) ** (1/12) - 1
    r_h   = (1 + p["hpf_rate"])     ** (1/12) - 1
    r_inv = (1 + proj_rate)          ** (1/12) - 1
    r_ins = (1 + p["ins_irr"])       ** (1/12) - 1

    cash_depl = None
    cur = p["today"]
    month_n = 0
    while cur < p["date_retire"]:
        expense = p["monthly_expense"] * (1 + inflation) ** (month_n / 12)
        pension_bal *= (1 + r_p)
        hpf_bal     *= (1 + r_h)
        investment  *= (1 + r_inv)
        ins_val     *= (1 + r_ins)
        cash += p["monthly_income"] - expense
        if cash < 0:
            if cash_depl is None:
                cash_depl = cur
            sell = min(-cash, investment)
            investment = max(investment - sell, 0)
            cash = 0
        cur += _rd(months=1)
        month_n += 1

    total    = pension_bal + hpf_bal + ins_val + investment + cash
    inv_cash = investment + cash
    defl     = p.get("deflator", 1.0)
    inv_real = inv_cash / defl
    eff_pension = p["monthly_pension"] * pension_mult
    gap_mo      = max(0.0, p["retire_expense_mo"] - eff_pension)
    target_adj  = gap_mo * 12 / 0.04
    return dict(label=label, total_2036=total, inv_cash=inv_cash,
                total_real=total / defl, inv_cash_real=inv_real,
                cash_depl=cash_depl,
                target_adj=target_adj,
                gap_adj=max(0.0, target_adj - inv_real),
                coverage=inv_real / target_adj if target_adj > 0 else float("inf"))
