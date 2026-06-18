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
    if years <= 0 or rate == 0:
        return npv
    pvifa = (1 - (1 + rate) ** (-years)) / rate
    return npv / pvifa


def annualized_return(mv, cost, years):
    if years <= 0 or cost <= 0:
        return 0.0
    return (mv / cost) ** (1 / years) - 1


def cagr(v0, v1, years):
    if years <= 0 or v0 <= 0:
        return 0.0
    return (v1 / v0) ** (1 / years) - 1


DISTRIBUTION_MONTHS = {50: 195, 55: 170, 60: 139, 65: 101}

def auto_monthly_pension(personal_account, account_rate, years_to_retire,
                          city_avg_wage, wage_growth_rate,
                          contribution_years, contribution_index,
                          retire_age=60):
    """按城镇职工基本养老保险公式推算月领金额"""
    account_at_retire = personal_account * (1 + account_rate) ** years_to_retire
    wage_at_retire    = city_avg_wage * (1 + wage_growth_rate) ** years_to_retire
    basic   = wage_at_retire * (1 + contribution_index) / 2 * contribution_years * 0.01
    dist_m  = DISTRIBUTION_MONTHS.get(retire_age, 139)
    personal_part = account_at_retire / dist_m
    return basic + personal_part


def compute_pension(params, discount_rate, date_retire, date_life_end, today):
    delay_m   = (date_retire - today).days // 30
    receive_m = (date_life_end - date_retire).days // 30
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
        if ins["premium_years_left"] > 0 and discount_rate > 0:
            pvifa = (1 - (1 + discount_rate) ** (-ins["premium_years_left"])) / discount_rate
            pv_prem = ins["annual_premium"] * pvifa
        result.append({**ins, "pv_maturity": pv_mat, "pv_premiums": pv_prem,
                       "npv": ins["cash_value"] + pv_mat - pv_prem,
                       "annualized_return": ins["policy_irr"],
                       "market_value": ins["cash_value"], "cost_basis": ins["cost_basis"]})
    return result


def compute_funds(fund_list, today):
    result = []
    for f in fund_list:
        nav  = f.get("current_nav") or f["cost_nav"]
        hold = max((today - f["buy_date"]).days / 365.25, 0.001)
        mv   = nav * f["shares"]
        cost = f["cost_nav"] * f["shares"]
        result.append({**f, "nav": nav, "market_value": mv, "cost_basis": cost,
                       "total_return": mv - cost,
                       "return_pct": (mv - cost) / cost if cost else 0,
                       "annualized_return": annualized_return(mv, cost, hold),
                       "holding_years": hold, "npv": mv})
    return result


def compute_stocks(stock_list, today):
    result = []
    for s in stock_list:
        price = s.get("current_price") or s["cost_price"]
        hold  = max((today - s["buy_date"]).days / 365.25, 0.001)
        mv    = price * s["shares"]
        cost  = s["cost_price"] * s["shares"]
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
        fv = d["balance"] * (1 + d["rate"]) ** max(t, 1)
        result.append({**d, "future_value": fv,
                       "npv": pv_lump(fv, discount_rate, max(t, 0.001)),
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
        rows.append({"layer": "③ 投资层", "category": f"基金·{f.get('name', f['code'])}",
                     "market_value": f["market_value"], "cost_basis": f["cost_basis"],
                     "npv": f["npv"], "annual_return": f["annualized_return"]})
    for s in stock_list:
        rows.append({"layer": "③ 投资层", "category": f"A股·{s.get('name', s['code'])}",
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
