"""
个人资产收益整合表 — Streamlit Web App
运行：streamlit run app.py
"""

import json as _json
import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib
from datetime import date, datetime

from finance_engine import (
    compute_pension, compute_hpf, compute_insurance,
    compute_funds, compute_stocks, compute_deposits,
    build_rows, weighted_avg_return, retirement_projection,
    eaa, cagr, auto_monthly_pension,
    _sim_params, run_scenario, run_stress,
)
from market_api import fetch_fund_prices, fetch_stock_prices

# ── 字体 ──────────────────────────────────────────────────────────────────
import os, glob as _glob

def _setup_font():
    fm = matplotlib.font_manager
    try:
        fm._load_fontmanager(try_read_cache=False)
    except Exception:
        try:
            fm._rebuild()
        except Exception:
            pass

    known = [f.name for f in fm.fontManager.ttflist]
    for name in ["PingFang SC", "PingFang HK", "Heiti TC", "STHeiti", "SimHei",
                 "Noto Sans CJK SC", "Noto Sans SC", "WenQuanYi Micro Hei"]:
        if name in known:
            matplotlib.rcParams["font.family"] = name
            return

    patterns = [
        "/usr/share/fonts/**/*CJK*",
        "/usr/share/fonts/**/*Noto*SC*",
        "/usr/share/fonts/**/*WenQuanYi*",
    ]
    for pat in patterns:
        hits = _glob.glob(pat, recursive=True)
        if hits:
            fm.fontManager.addfont(hits[0])
            prop = fm.FontProperties(fname=hits[0])
            matplotlib.rcParams["font.family"] = prop.get_name()
            return

_setup_font()
matplotlib.rcParams["axes.unicode_minus"] = False

st.set_page_config(page_title="个人资产收益整合表", page_icon="📊", layout="wide")

# ── 日期辅助 ──────────────────────────────────────────────────────────────
def _d(s, default):
    try:
        return date.fromisoformat(s) if s else default
    except Exception:
        return default

# ═══════════════════════════════════════════════════════
# 侧边栏：参数输入
# ═══════════════════════════════════════════════════════
with st.sidebar:
    st.title("📋 参数设置")

    # ── 导入配置 ──────────────────────────────────────
    st.subheader("💾 配置文件")
    uploaded = st.file_uploader("导入 JSON 配置", type=["json"], label_visibility="collapsed")
    if uploaded is not None:
        if st.session_state.get("_upload_id") != uploaded.file_id:
            try:
                _loaded = _json.load(uploaded)
                st.session_state["_cfg"]       = _loaded
                st.session_state["_upload_id"] = uploaded.file_id
                _lh  = _loaded.get("hpf", {})
                _lsn = _loaded.get("snapshots", {})
                _lin = _loaded.get("insurance", [])
                st.session_state["hpf_bal"]  = float(_lh.get("balance", 80_000))
                st.session_state["b1ph"]  = float(_lsn.get("b1_ph",  50_000))
                st.session_state["b1ins"] = float(_lsn.get("b1_ins", 10_000))
                st.session_state["b1inv"] = float(_lsn.get("b1_inv", 30_000))
                st.session_state["b1csh"] = float(_lsn.get("b1_csh", 50_000))
                st.session_state["b2ph"]  = float(_lsn.get("b2_ph",  120_000))
                st.session_state["b2ins"] = float(_lsn.get("b2_ins",  30_000))
                st.session_state["b2inv"] = float(_lsn.get("b2_inv", 100_000))
                st.session_state["b2csh"] = float(_lsn.get("b2_csh", 100_000))
                for i, ins in enumerate(_lin):
                    st.session_state[f"ins_name_{i}"] = ins.get("name", f"储蓄险{i+1}")
                    st.session_state[f"ins_cv_{i}"]   = float(ins.get("cash_value", 50_000))
                    st.session_state[f"ins_cost_{i}"] = float(ins.get("cost_basis", 50_000))
                    st.session_state[f"ins_prem_{i}"] = float(ins.get("annual_premium", 0))
                    st.session_state[f"ins_left_{i}"] = int(ins.get("premium_years_left", 0))
                    st.session_state[f"ins_mat_{i}"]  = float(ins.get("maturity_value", 50_000))
                    st.session_state[f"ins_yrs_{i}"]  = int(ins.get("years_to_maturity", 0))
                    st.session_state[f"ins_irr_{i}"]  = float(ins.get("policy_irr", 0.030))
                st.session_state["fund_dca_text"] = _loaded.get("funds_dca", _loaded.get("funds", ""))
                st.session_state["stock_text"]    = _loaded.get("stocks", "")
                st.session_state["dep_text"]      = _loaded.get("deposits", "")
                st.success("配置已加载")
            except Exception as e:
                st.error(f"JSON 解析失败：{e}")

    _cfg = st.session_state.get("_cfg", {})
    _g   = _cfg.get("global", {})
    _p   = _cfg.get("pension", {})
    _h   = _cfg.get("hpf", {})
    _ins = _cfg.get("insurance", [])
    _sn  = _cfg.get("snapshots", {})
    _sm  = _cfg.get("sim", {})

    st.divider()

    # 全局
    st.subheader("全局参数")
    discount_rate    = st.number_input("折现率", value=float(_g.get("discount_rate", 0.03)), step=0.005, format="%.3f")
    proj_invest_rate = st.number_input("退休推算投资年化", value=float(_g.get("proj_invest_rate", 0.05)),
                                       step=0.01, format="%.2f", help="保守3-4%，中性5-6%，激进7-8%")
    date_retire   = st.date_input("预计退休日期",    value=_d(_g.get("date_retire"),   date(2040, 1, 1)))
    date_life_end = st.date_input("预期寿命终止日",  value=_d(_g.get("date_life_end"), date(2080, 1, 1)))
    date_base_1   = st.date_input("基期起始",        value=_d(_g.get("date_base_1"),   date(2020, 1, 1)))
    date_base_2   = st.date_input("对比节点",        value=_d(_g.get("date_base_2"),   date(2023, 1, 1)))

    st.divider()

    # 养老
    st.subheader("① 养老保险")
    pension_account = st.number_input("个人账户余额", value=float(_p.get("account", 100_000)), step=1000.0)
    pension_rate    = st.number_input("账户年化利率", value=float(_p.get("rate", 0.055)), step=0.001, format="%.3f")

    pension_auto = st.toggle("按城职保公式自动推算月领金额", value=bool(_p.get("auto", True)))

    if pension_auto:
        CITY_WAGES = {
            "深圳": 12500, "北京": 14000, "上海": 13500,
            "广州": 10500, "杭州": 10500, "成都": 8500,
            "武汉": 8500,  "南京": 9500,  "其他（手动输入）": 0,
        }
        city_choice = st.selectbox("所在城市", list(CITY_WAGES.keys()),
                                   index=list(CITY_WAGES.keys()).index(_p.get("city", "深圳"))
                                         if _p.get("city") in CITY_WAGES else 0)
        if city_choice == "其他（手动输入）":
            city_avg_wage = st.number_input("城市月社平工资（元）", value=float(_p.get("city_wage", 8000)), step=100.0)
        else:
            city_avg_wage = float(CITY_WAGES[city_choice])
            st.caption(f"参考社平工资：¥{city_avg_wage:,.0f}/月（非私营单位均薪，数据可能已过时，建议自查当地社保局官网后选「其他」手动输入）")

        wage_growth   = st.number_input("社平工资年增长率", value=float(_p.get("wage_growth", 0.04)), step=0.005, format="%.3f")
        contrib_years = st.number_input("预计缴费年限（年）", value=int(_p.get("contrib_years", 20)), step=1)
        contrib_index = st.number_input("缴费指数", value=float(_p.get("contrib_index", 1.0)), step=0.05, format="%.2f",
                                        help="缴费基数 / 社平工资，一般在 0.6～3 之间，按社平工资缴纳填 1.0")
        retire_age    = st.selectbox("退休年龄", [50, 55, 60, 65],
                                     index=[50,55,60,65].index(int(_p.get("retire_age", 60))))
        y_to_retire_pension = (date_retire - date.today()).days / 365.25
        pension_monthly = auto_monthly_pension(
            pension_account, pension_rate, y_to_retire_pension,
            city_avg_wage, wage_growth, contrib_years, contrib_index, retire_age,
        )
        st.info(f"推算月领金额：**¥{pension_monthly:,.0f}**（退休时，含基础养老金+个人账户养老金）")
    else:
        pension_monthly = st.number_input("预计月领金额（手动填写）", value=float(_p.get("monthly", 3_000)), step=100.0)
        city_choice = city_avg_wage = wage_growth = contrib_years = contrib_index = retire_age = None

    st.divider()

    # 公积金
    st.subheader("② 住房公积金")
    hpf_balance = st.number_input("当前余额",       value=float(_h.get("balance", 80_000)), step=1000.0, key="hpf_bal")
    hpf_years   = st.number_input("预计几年后动用", value=float(_h.get("years", 10)), step=1.0)

    st.divider()

    # 储蓄险
    st.subheader("③ 储蓄险")
    ins_default_count = len(_ins) if _ins else 1
    ins_count = st.number_input("保单数量", value=ins_default_count, min_value=0, max_value=5, step=1)
    ins_inputs = []
    for i in range(int(ins_count)):
        saved = _ins[i] if i < len(_ins) else {}
        with st.expander(f"保单 {i+1}", expanded=(i == 0)):
            ins_inputs.append({
                "name":               st.text_input("保单名称",  value=saved.get("name", f"储蓄险{i+1}"), key=f"ins_name_{i}"),
                "cash_value":         st.number_input("现金价值", value=float(saved.get("cash_value", 50_000)), key=f"ins_cv_{i}"),
                "cost_basis":         st.number_input("已缴保费", value=float(saved.get("cost_basis", 50_000)), key=f"ins_cost_{i}"),
                "annual_premium":     st.number_input("年缴保费", value=float(saved.get("annual_premium", 0)), key=f"ins_prem_{i}"),
                "premium_years_left": st.number_input("还需缴年", value=int(saved.get("premium_years_left", 0)), key=f"ins_left_{i}"),
                "maturity_value":     st.number_input("满期金额", value=float(saved.get("maturity_value", 50_000)), key=f"ins_mat_{i}"),
                "years_to_maturity":  st.number_input("距满期年", value=int(saved.get("years_to_maturity", 0)), key=f"ins_yrs_{i}"),
                "policy_irr":         st.number_input("保单 IRR", value=float(saved.get("policy_irr", 0.030)), format="%.3f", key=f"ins_irr_{i}"),
            })

    st.divider()

    # 基金 A类（定投）
    st.subheader("④ 基金")
    st.markdown("**A 类 · 定投基金**")
    st.caption("格式：代码, 份额, 持有成本(¥总额), 当前市值(¥总额) · 支持中文逗号 · 直接从理财App抄数字")
    fund_dca_text = st.text_area(
        "定投基金",
        value=_cfg.get("funds_dca", _cfg.get("funds", "")),
        height=100,
        label_visibility="collapsed",
        key="fund_dca_text",
    )

    # 基金 B类（单笔）并入精确持仓
    st.markdown("**B 类 · 单笔买入 / ETF / A股**")
    st.caption("格式：代码, 股数/份额, 成本价, 买入日期[, 当前价]")
    stock_text = st.text_area(
        "单笔持仓",
        value=_cfg.get("stocks", "600036,100,35.00,2023-01-01\n000001,200,12.50,2023-06-01"),
        height=120,
        label_visibility="collapsed",
        help="基金、ETF、A股统一格式。第5列当前价可选，填入后跳过 API 拉取。",
        key="stock_text",
    )

    st.divider()

    # 存款
    st.subheader("⑤ 银行存款")
    dep_text = st.text_area(
        "存款列表（每行：银行名,类型,余额[,年化利率]）",
        value=_cfg.get("deposits", "工商银行,活期,50000,0.002\n招商银行,定期,50000,0.020"),
        height=100,
        key="dep_text",
    )

    st.divider()

    # 历史快照
    st.subheader("历史快照（估算即可）")
    col1, col2 = st.columns(2)
    with col1:
        st.caption("基期起始")
        b1_ph  = st.number_input("养老+公积金", value=float(_sn.get("b1_ph",  50_000)), key="b1ph")
        b1_ins = st.number_input("储蓄险",      value=float(_sn.get("b1_ins", 10_000)), key="b1ins")
        b1_inv = st.number_input("投资",         value=float(_sn.get("b1_inv", 30_000)), key="b1inv")
        b1_csh = st.number_input("现金",         value=float(_sn.get("b1_csh", 50_000)), key="b1csh")
    with col2:
        st.caption("对比节点")
        b2_ph  = st.number_input("养老+公积金", value=float(_sn.get("b2_ph",  120_000)), key="b2ph")
        b2_ins = st.number_input("储蓄险",      value=float(_sn.get("b2_ins",  30_000)), key="b2ins")
        b2_inv = st.number_input("投资",         value=float(_sn.get("b2_inv", 100_000)), key="b2inv")
        b2_csh = st.number_input("现金",         value=float(_sn.get("b2_csh", 100_000)), key="b2csh")

    st.divider()

    # ── 情景模拟参数 ───────────────────────────────────
    st.subheader("情景模拟参数")
    monthly_income         = st.number_input("月税后收入（元）",     value=float(_sm.get("monthly_income",    19_000)), step=500.0)
    monthly_expense        = st.number_input("月总支出（元）",       value=float(_sm.get("monthly_expense",   11_000)), step=500.0)
    retire_expense_mo      = st.number_input("退休月支出（元）",     value=float(_sm.get("retire_expense_mo",  8_000)), step=500.0)
    semi_income            = st.number_input("半退休月收入（元）",   value=float(_sm.get("semi_income",       10_000)), step=500.0)
    income_interrupt_months = st.number_input("收入中断月数",        value=int(_sm.get("income_interrupt_months", 12)),  step=1, min_value=1)

    st.divider()

    # ── 目标资产配置 ───────────────────────────────────
    st.subheader("目标资产配置（%）")
    st.caption("设定各层目标比例，合计建议 100%")
    target_ph_pct  = st.number_input("社保层目标 %",  value=int(_sm.get("target_ph",  30)), min_value=0, max_value=100, step=5)
    target_ins_pct = st.number_input("保险层目标 %",  value=int(_sm.get("target_ins", 15)), min_value=0, max_value=100, step=5)
    target_inv_pct = st.number_input("投资层目标 %",  value=int(_sm.get("target_inv", 40)), min_value=0, max_value=100, step=5)
    target_csh_pct = st.number_input("现金层目标 %",  value=int(_sm.get("target_csh", 15)), min_value=0, max_value=100, step=5)

    st.divider()

    # ── 导出配置 ──────────────────────────────────────
    export_data = {
        "global": {
            "discount_rate": discount_rate, "proj_invest_rate": proj_invest_rate,
            "date_retire": str(date_retire), "date_life_end": str(date_life_end),
            "date_base_1": str(date_base_1), "date_base_2": str(date_base_2),
        },
        "pension": {
            "account": pension_account, "monthly": pension_monthly, "rate": pension_rate,
            "auto": pension_auto, "city": city_choice, "city_wage": city_avg_wage,
            "wage_growth": wage_growth, "contrib_years": contrib_years,
            "contrib_index": contrib_index, "retire_age": retire_age,
        },
        "hpf":      {"balance": hpf_balance, "years": hpf_years},
        "insurance": ins_inputs,
        "funds_dca": fund_dca_text,
        "stocks":    stock_text,
        "deposits": dep_text,
        "snapshots": {
            "b1_ph": b1_ph, "b1_ins": b1_ins, "b1_inv": b1_inv, "b1_csh": b1_csh,
            "b2_ph": b2_ph, "b2_ins": b2_ins, "b2_inv": b2_inv, "b2_csh": b2_csh,
        },
        "sim": {
            "monthly_income": monthly_income, "monthly_expense": monthly_expense,
            "retire_expense_mo": retire_expense_mo, "semi_income": semi_income,
            "income_interrupt_months": income_interrupt_months,
            "target_ph": target_ph_pct, "target_ins": target_ins_pct,
            "target_inv": target_inv_pct, "target_csh": target_csh_pct,
        },
    }
    st.download_button(
        "💾 导出配置",
        data=_json.dumps(export_data, ensure_ascii=False, indent=2),
        file_name="finance_config.json",
        mime="application/json",
        use_container_width=True,
    )

    run = st.button("🚀 运行计算", type="primary", use_container_width=True)

# ═══════════════════════════════════════════════════════
# 主界面
# ═══════════════════════════════════════════════════════
st.title("📊 个人资产收益整合表")
st.caption("管理会计利润表结构 · 按流动性分层（低 → 高）")

with st.expander("📖 使用说明"):
    try:
        _guide_path = os.path.join(os.path.dirname(__file__), "USER_GUIDE.md")
        with open(_guide_path, encoding="utf-8") as _f:
            st.markdown(_f.read())
    except Exception:
        st.caption("使用说明文件未找到，请参考 GitHub 仓库中的 USER_GUIDE.md")

if not run:
    st.info("← 在左侧填写参数后，点击「运行计算」")
    st.stop()

today = date.today()

# ── 解析文本输入 ──────────────────────────────────────
def parse_fund_dca(text):
    """A类定投基金：代码, 份额, 持有成本(总额¥), 当前市值(总额¥)
    内部自动换算为每单位净值，中文逗号兼容。"""
    result = []
    for line in text.strip().splitlines():
        line = line.replace("，", ",")
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4:
            continue
        try:
            code        = parts[0]
            shares      = float(parts[1])
            total_cost  = float(parts[2])
            total_value = float(parts[3])
            if shares <= 0:
                continue
            result.append({
                "code":       code,
                "shares":     shares,
                "cost_nav":   total_cost  / shares,
                "manual_nav": total_value / shares,
                "buy_date":   None,
            })
        except Exception:
            pass
    return result


def parse_funds(text):
    """B类单笔基金（已并入精确持仓，保留备用）"""
    result = []
    for line in text.strip().splitlines():
        line = line.replace("，", ",")
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3:
            continue
        try:
            code      = parts[0]
            shares    = float(parts[1])
            cost_nav  = float(parts[2])
            buy_date  = None
            manual_nav = None
            if len(parts) >= 4:
                try:
                    buy_date = datetime.strptime(parts[3], "%Y-%m-%d").date()
                except ValueError:
                    manual_nav = float(parts[3]) if parts[3] else None
            if len(parts) >= 5:
                manual_nav = float(parts[4]) if parts[4] else None
            result.append({
                "code": code, "shares": shares, "cost_nav": cost_nav,
                "buy_date": buy_date, "manual_nav": manual_nav,
            })
        except Exception:
            pass
    return result

def parse_stocks(text):
    result = []
    for line in text.strip().splitlines():
        line = line.replace("，", ",")
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4:
            continue
        try:
            result.append({
                "code": parts[0], "shares": float(parts[1]),
                "cost_price": float(parts[2]),
                "buy_date": datetime.strptime(parts[3], "%Y-%m-%d").date(),
                "manual_price": float(parts[4]) if len(parts) > 4 and parts[4] else None,
            })
        except Exception:
            pass
    return result

def parse_deposits(text):
    result = []
    for line in text.strip().splitlines():
        line = line.replace("，", ",")
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3:
            continue
        try:
            result.append({
                "bank": parts[0], "type": parts[1],
                "balance": float(parts[2]),
                "rate": float(parts[3]) if len(parts) > 3 and parts[3] else 0.0,
                "term_years": 0,
            })
        except Exception:
            pass
    return result

fund_input_raw  = parse_fund_dca(fund_dca_text)   # A类：定投，总金额格式
stock_input_raw = parse_stocks(stock_text)      # B类：单笔基金/ETF/A股，有买入日期
dep_input_raw   = parse_deposits(dep_text)
st.caption(f"🔍 DEP DEBUG | 行数={len(dep_input_raw)} | raw={repr(dep_text[:60])}")

# ── 拉取行情 ──────────────────────────────────────────
with st.spinner("正在拉取实时行情…"):
    fund_input  = fetch_fund_prices(fund_input_raw)
    stock_input = fetch_stock_prices(stock_input_raw)

_price_ok    = [f.get("name", f["code"]) for f in fund_input  if f.get("current_nav")]
_price_ok   += [s.get("name", s["code"]) for s in stock_input if s.get("current_price")]
_price_fail  = [f.get("code") for f in fund_input  if not f.get("current_nav")]
_price_fail += [s.get("code") for s in stock_input if not s.get("current_price")]
if _price_fail:
    st.warning(
        f"{len(_price_fail)} 个资产未获取到行情（{', '.join(_price_fail)}），"
        "使用成本价代替，年化收益率显示 0%。\n\n"
        "解决：从支付宝/招商等 App 查当前净值，在左侧基金列表填入当前净值：\n"
        "定投格式（无日期）→ `018128, 份额, 成本净值, 当前净值`\n"
        "精确格式（有日期）→ `018128, 份额, 成本净值, 买入日期, 当前净值`"
    )
elif _price_ok:
    st.caption(f"✅ 行情已获取：{', '.join(_price_ok)}")

# ── 计算 ──────────────────────────────────────────────
pension_params = {
    "personal_account": pension_account, "cost_basis": pension_account,
    "monthly_pension": pension_monthly,  "account_annual_return": pension_rate,
}
hpf_params = {
    "balance": hpf_balance, "cost_basis": hpf_balance,
    "annual_rate": 0.025, "expected_use_years": hpf_years, "note": "",
}

pension  = compute_pension(pension_params, discount_rate, date_retire, date_life_end, today)
hpf      = compute_hpf(hpf_params, discount_rate)
ins_list = compute_insurance(ins_inputs, discount_rate)
fund_list   = compute_funds(fund_input, today)
stock_list  = compute_stocks(stock_input, today)
dep_list    = compute_deposits(dep_input_raw, discount_rate)

rows = build_rows(pension, hpf, ins_list, fund_list, stock_list, dep_list)
w_return = weighted_avg_return(rows)
total_mv   = sum(r["market_value"] for r in rows)
total_cost = sum(r["cost_basis"] for r in rows)
total_npv  = sum(r["npv"] for r in rows)
horizon    = (date_life_end - today).days / 365.25
eaa_val    = eaa(total_npv, discount_rate, horizon)

# ── KPI 卡片 ──────────────────────────────────────────
st.subheader("总览")
k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("当前总资产", f"¥{total_mv:,.0f}")
k2.metric("浮盈", f"¥{total_mv - total_cost:+,.0f}")
k3.metric("加权年化", f"{w_return:.2%}", help="诊断用，不可直接用于预测")
k4.metric("NPV", f"¥{total_npv:,.0f}")
k5.metric("等值月均", f"¥{eaa_val/12:,.0f}")

st.divider()

# ── 整合报表 ──────────────────────────────────────────
st.subheader("个人资产收益整合表")

df = pd.DataFrame(rows)
df["浮盈"]    = df["market_value"] - df["cost_basis"]
df["return%"] = df["浮盈"] / df["cost_basis"]

for layer in df["layer"].unique():
    sub = df[df["layer"] == layer].copy()
    st.markdown(f"**{layer}**")
    display = sub[["category","market_value","cost_basis","浮盈","annual_return","npv"]].copy()
    display.columns = ["资产","市值","成本","浮盈","年化收益率","NPV"]

    _mv   = sub["market_value"].sum()
    _cost = sub["cost_basis"].sum()
    _npv  = sub["npv"].sum()
    _gain = _mv - _cost
    _wav  = sum(sub["cost_basis"] / _cost * sub["annual_return"]) if _cost else 0

    display["市值"]       = display["市值"].map("¥{:,.0f}".format)
    display["成本"]       = display["成本"].map("¥{:,.0f}".format)
    display["浮盈"]       = display["浮盈"].map("¥{:+,.0f}".format)
    display["年化收益率"] = display["年化收益率"].map("{:.1%}".format)
    display["NPV"]        = display["NPV"].map("¥{:,.0f}".format)
    st.dataframe(display, use_container_width=True, hide_index=True)
    st.caption(
        f"小计 ｜ 市值 ¥{_mv:,.0f} ｜ 成本 ¥{_cost:,.0f} ｜"
        f" 浮盈 ¥{_gain:+,.0f} ｜ 加权年化 {_wav:.1%} ｜ NPV ¥{_npv:,.0f}"
    )

st.divider()

# ── 图表数据准备 ───────────────────────────────────────
snap_now = {
    "pension_hpf": pension["personal_account"] + hpf["balance"],
    "insurance":   sum(i["cash_value"] for i in ins_list),
    "investment":  sum(f["market_value"] for f in fund_list) + sum(s["market_value"] for s in stock_list),
    "cash":        sum(d["balance"] for d in dep_list),
}
snap_b1  = {"pension_hpf": b1_ph, "insurance": b1_ins, "investment": b1_inv, "cash": b1_csh}
snap_b2  = {"pension_hpf": b2_ph, "insurance": b2_ins, "investment": b2_inv, "cash": b2_csh}
y_to_retire = (date_retire - today).days / 365.25
snap_ret = retirement_projection(snap_now, proj_invest_rate, ins_inputs, y_to_retire)

# ── 图表 ──────────────────────────────────────────────
from matplotlib.ticker import FuncFormatter as _FF

st.subheader("资产结构 & 四期对比")

matplotlib.rcParams.update({
    "figure.facecolor": "#F7F8FA",
    "axes.facecolor":   "#F7F8FA",
    "axes.titleweight": "bold",
    "axes.titlesize":   13,
    "font.size":        10,
    "axes.unicode_minus": False,
})

layer_mv     = df.groupby("layer")["market_value"].sum()
layer_names  = list(layer_mv.index)
layer_vals   = list(layer_mv.values)
dates_str    = [str(date_base_1), str(date_base_2), "当前", f"{date_retire.year}推算"]
bar_vals     = [sum(snap_b1.values()), sum(snap_b2.values()),
                sum(snap_now.values()), sum(snap_ret.values())]

fig, axes = plt.subplots(1, 2, figsize=(13, 5.5),
                          gridspec_kw={"width_ratios": [1, 1.25]},
                          facecolor="#F7F8FA")
fig.suptitle("个人资产概览", fontsize=18, fontweight="bold", color="#172B4D", y=1.02)

# 左图：环形图
PIE_COLORS = ["#264653", "#2A9D8F", "#E9C46A", "#E76F51", "#8AB17D", "#7B8FA1"]
wedges, _, autotexts = axes[0].pie(
    layer_vals,
    startangle=90,
    counterclock=False,
    colors=PIE_COLORS[:len(layer_vals)],
    autopct=lambda pct: f"{pct:.1f}%" if pct >= 3 else "",
    pctdistance=0.78,
    wedgeprops={"width": 0.38, "edgecolor": "#F7F8FA", "linewidth": 3},
)
for at in autotexts:
    at.set_color("white"); at.set_fontsize(9); at.set_fontweight("bold")

axes[0].text(0,  0.08, "总资产",           ha="center", color="#6B778C", fontsize=10)
axes[0].text(0, -0.09, f"¥{total_mv:,.0f}", ha="center", color="#172B4D", fontsize=14, fontweight="bold")
axes[0].set_title(f"资产配置 · {today}", pad=14, color="#172B4D")
axes[0].legend(
    wedges,
    [f"{n}  ¥{v:,.0f}" for n, v in zip(layer_names, layer_vals)],
    loc="lower center", bbox_to_anchor=(0.5, -0.22),
    ncol=2, frameon=False, fontsize=9,
)

# 右图：柱状图
_bar_colors = ["#B8C8D8"] * len(bar_vals)
_bar_colors[-1] = "#2A9D8F"
bars = axes[1].bar(dates_str, bar_vals, width=0.56, color=_bar_colors, edgecolor="none")
max_val = max(bar_vals)
axes[1].set_ylim(0, max_val * 1.18)

for i, (bar, val) in enumerate(zip(bars, bar_vals)):
    cx = bar.get_x() + bar.get_width() / 2
    axes[1].text(cx, val + max_val * 0.025,
                 f"¥{val:,.0f}", ha="center", va="bottom",
                 fontsize=9, fontweight="bold", color="#172B4D")
    if i > 0 and bar_vals[i - 1]:
        pct = (val - bar_vals[i - 1]) / bar_vals[i - 1] * 100
        axes[1].text(cx, val * 0.92,
                     f"{'+'if pct>=0 else ''}{pct:.1f}%",
                     ha="center", va="top", fontsize=8, fontweight="bold",
                     color="white" if i == len(bar_vals) - 1 else "#44546A")

axes[1].set_title("总资产变化趋势", pad=14, color="#172B4D")
axes[1].set_ylabel("资产金额", fontsize=9)
axes[1].yaxis.set_major_formatter(_FF(lambda x, _: f"¥{x/1e4:,.0f}万"))
axes[1].grid(axis="y", color="#DDE2E8", linewidth=0.8, alpha=0.8)
axes[1].set_axisbelow(True)
axes[1].tick_params(axis="both", length=0, colors="#5E6C84", labelsize=8.5)

for ax in axes:
    for spine in ax.spines.values():
        spine.set_visible(False)

fig.tight_layout()
st.pyplot(fig)
plt.close()

st.divider()

# ── 退休推算 ──────────────────────────────────────────
st.subheader("退休推算")
r1, r2, r3 = st.columns(3)
retire_total = sum(snap_ret.values())
now_total    = sum(snap_now.values())
r1.metric(f"{date_retire.year} 推算总资产", f"¥{retire_total:,.0f}")
r2.metric("增量", f"¥{retire_total - now_total:+,.0f}")
r3.metric("推算用投资年化", f"{proj_invest_rate:.1%}", help="在左侧「退休推算投资年化」修改")
st.caption(f"⚠️ 加权历史年化 {w_return:.2%} 含历史浮盈，不可直接用于预测。此处使用手动设定的 {proj_invest_rate:.1%}。")
st.caption("⚠️ 推算不含未来工资转入，为「停止工作后纯靠现有资产增值」的保守估算。")

st.divider()

# ── V2 情景模拟 ────────────────────────────────────────
st.subheader("情景模拟")

from dateutil.relativedelta import relativedelta as _rdelta

_sp = _sim_params(
    pension, hpf, ins_list, fund_list, stock_list, dep_list,
    monthly_income, monthly_expense, retire_expense_mo,
    proj_invest_rate, today, date_retire,
)
_interrupt_end = today + _rdelta(months=int(income_interrupt_months))
_scenarios = [
    ("① 继续工作",                          []),
    (f"② 收入中断{int(income_interrupt_months)}个月", [(today, _interrupt_end, 0)]),
    ("③ 半退休至退休",                      [(today, date_retire, semi_income)]),
]
_results = [run_scenario(name, sched, _sp) for name, sched in _scenarios]

_target = retire_expense_mo * 12 / 0.04

import pandas as pd
_sc_df = pd.DataFrame([{
    "情景":         r["name"],
    "现金耗尽":     "不耗尽" if r["cash_depl"] is None else str(r["cash_depl"])[:7],
    f"{date_retire.year}总资产": f"¥{r['total_2036']:,.0f}",
    "退休缺口":     "无" if r["gap"] == 0 else f"¥{r['gap']:,.0f}",
} for r in _results])
st.dataframe(_sc_df, hide_index=True, use_container_width=True)
st.caption(f"4% 法则退休目标：¥{_target:,.0f}（月支出 ¥{retire_expense_mo:,}）")

# ── 养老金调整视角 ─────────────────────────────────────
st.subheader("养老金调整视角")
_pension_mo  = pension["monthly_pension"]
_gap_mo      = max(0.0, retire_expense_mo - _pension_mo)
_target_adj  = _gap_mo * 12 / 0.04

c1, c2, c3, c4 = st.columns(4)
c1.metric("养老金月领（推算）", f"¥{_pension_mo:,.0f}")
c2.metric("退休月支出",        f"¥{retire_expense_mo:,}")
c3.metric("需投资组合覆盖",     f"¥{_gap_mo:,.0f}/月")
c4.metric("调整后4%目标",      f"¥{_target_adj:,.0f}" if _target_adj > 0 else "¥0（盈余）")

_investable = [r["invest_2036"] + r["cash_2036"] for r in _results]
_adj_df = pd.DataFrame([{
    "情景":         r["name"],
    "可投资资产":   f"¥{iv:,.0f}",
    "vs调整目标":   f"+¥{iv-_target_adj:,.0f}" if _target_adj > 0 else "无上限",
    "覆盖倍数":     f"{iv/_target_adj:.1f}x" if _target_adj > 0 else "∞",
} for r, iv in zip(_results, _investable)])
st.dataframe(_adj_df, hide_index=True, use_container_width=True)
if _gap_mo == 0:
    st.success(f"养老金 ¥{_pension_mo:,.0f}/月 已超过退休支出，投资组合为纯额外缓冲。")
else:
    st.info(f"养老金覆盖退休支出的 {_pension_mo/retire_expense_mo:.0%}，缺口 ¥{_gap_mo:,.0f}/月需投资组合补足。")

# ── 压力测试 ──────────────────────────────────────────
st.subheader("压力测试")
st.caption("以「继续工作」为基准，施加单一或组合冲击")

_baseline = _results[0]["total_2036"]
_stress_cases = [
    ("基准（继续工作）",     dict()),
    ("市场跌 20%",          dict(investment_shock=0.8)),
    ("市场跌 40%",          dict(investment_shock=0.6)),
    ("通胀 3%",             dict(inflation=0.03)),
    ("养老金打七折",         dict(pension_mult=0.7)),
    ("投资收益 1%",          dict(proj_rate=0.01)),
    ("组合冲击(跌20%+7折)", dict(investment_shock=0.8, pension_mult=0.7)),
]
_stress_results = [run_stress(lbl, _sp, **kw) for lbl, kw in _stress_cases]

_st_df = pd.DataFrame([{
    "情景":       t["label"],
    "2036总资产": f"¥{t['total_2036']:,.0f}",
    "vs基准":     "—" if abs(t["total_2036"] - _baseline) < 1 else f"{t['total_2036']-_baseline:+,.0f}",
    "可投资资产": f"¥{t['inv_cash']:,.0f}",
    "覆盖倍数":   "∞" if t["coverage"] == float("inf") else f"{t['coverage']:.1f}x",
} for t in _stress_results])
st.dataframe(_st_df, hide_index=True, use_container_width=True)

st.divider()

# ── V3 投资建议 ────────────────────────────────────────────────────────────
st.subheader("💡 投资建议")

_layer_vals = {
    "社保层": snap_now["pension_hpf"],
    "保险层": snap_now["insurance"],
    "投资层": snap_now["investment"],
    "现金层": snap_now["cash"],
}
_total_now  = sum(_layer_vals.values())
_layer_pcts = {k: v / _total_now if _total_now else 0 for k, v in _layer_vals.items()}

# A. 持仓结构诊断
st.markdown("**A. 持仓结构诊断**")
_diags = []

if _layer_pcts["投资层"] < 0.20:
    _diags.append(("warning", "投资层比例偏低",
                   f"当前占 {_layer_pcts['投资层']:.1%}，建议提升至 20% 以上以增强长期增值能力"))

if _layer_pcts["现金层"] > 0.30:
    _diags.append(("warning", "现金沉淀过多",
                   f"当前占 {_layer_pcts['现金层']:.1%}，超过 30% 的部分建议转入投资层"))

_inv_assets = fund_list + stock_list
_inv_total  = _layer_vals["投资层"]
if _inv_total > 0 and _inv_assets:
    _max_asset = max(_inv_assets, key=lambda x: x["market_value"])
    _max_pct   = _max_asset["market_value"] / _inv_total
    if _max_pct > 0.50:
        _aname = _max_asset.get("name", _max_asset.get("code", ""))
        _diags.append(("error", "集中度风险",
                       f"{_aname} 占投资层 {_max_pct:.1%}，建议将单一资产控制在 50% 以内"))

_non_liquid_pct = (_layer_vals["社保层"] + _layer_vals["保险层"]) / _total_now if _total_now else 0
if _non_liquid_pct > 0.60:
    _diags.append(("warning", "整体流动性偏低",
                   f"社保+保险非流动性资产占 {_non_liquid_pct:.1%}，超过 60%，短期流动性有限"))

if not _diags:
    st.success("✅ 持仓结构无明显问题")
else:
    for _lvl, _title, _msg in _diags:
        if _lvl == "error":
            st.error(f"**{_title}**：{_msg}")
        else:
            st.warning(f"**{_title}**：{_msg}")

# B. 目标配置偏差表
st.markdown("**B. 目标配置偏差表**")
_target_pcts = {
    "社保层": target_ph_pct  / 100,
    "保险层": target_ins_pct / 100,
    "投资层": target_inv_pct / 100,
    "现金层": target_csh_pct / 100,
}
_target_sum  = sum(_target_pcts.values())
_alloc_rows  = []
for _lname, _cur_val in _layer_vals.items():
    _cur_pct = _layer_pcts[_lname]
    _tgt_pct = _target_pcts[_lname]
    _dev     = _cur_pct - _tgt_pct
    _adj     = (_tgt_pct - _cur_pct) * _total_now
    _alloc_rows.append({
        "层级":               _lname,
        "当前":               f"{_cur_pct:.1%}",
        "目标":               f"{_tgt_pct:.1%}",
        "偏差":               f"{_dev:+.1%}",
        "调仓金额（正=增配/负=减配）": f"¥{_adj:+,.0f}",
    })
st.dataframe(pd.DataFrame(_alloc_rows), hide_index=True, use_container_width=True)
if abs(_target_sum - 1.0) > 0.01:
    st.warning(f"目标配置合计 {_target_sum:.0%}，请在左侧调整至 100%")
else:
    st.caption("调仓金额正数 = 需增配，负数 = 需减配")

st.divider()

# ── V3 退休建议 ────────────────────────────────────────────────────────────
st.subheader("🎯 退休建议")

_retire_target  = retire_expense_mo * 12 / 0.04
_months_to_ret  = max(int((date_retire - today).days / 30), 1)
_r_mo           = (1 + proj_invest_rate) ** (1 / 12) - 1

# A. 情景结果文字判断
st.markdown("**A. 情景结果判断**")
st.caption(
    f"4% 法则目标 = 退休月支出 ¥{retire_expense_mo:,} × 12 ÷ 4% = **¥{_retire_target:,.0f}**　｜　"
    f"⚠️ 此目标未扣除养老金月领，偏保守；扣除后的调整目标见下方「养老金调整视角」"
)
for _r in _results:
    _gap    = _r["gap"]
    _total  = _r["total_2036"]
    _cash_d = _r["cash_depl"]
    with st.expander(_r["name"], expanded=True):
        if _gap == 0:
            _margin = _total - _retire_target
            st.success(f"✅ 财务达标 — 退休总资产 ¥{_total:,.0f}，超出目标 ¥{_margin:,.0f}（安全边际 {_margin / _retire_target:.1%}）")
            st.caption(f"计算：¥{_total:,.0f}（推算资产）− ¥{_retire_target:,.0f}（目标）= +¥{_margin:,.0f}")
        else:
            st.error(f"❌ 退休缺口 ¥{_gap:,.0f} — 退休总资产 ¥{_total:,.0f}，低于 4% 法则目标 ¥{_retire_target:,.0f}")
            st.caption(f"计算：¥{_retire_target:,.0f}（目标）− ¥{_total:,.0f}（推算资产）= 缺口 ¥{_gap:,.0f}")
        if _cash_d is not None:
            _cash_now  = sum(d["balance"] for d in dep_list)
            _inv_now   = sum(f["market_value"] for f in fund_list) + sum(s["market_value"] for s in stock_list)
            _liquid    = _cash_now + _inv_now
            _liq_mo    = int(_liquid / monthly_expense) if monthly_expense else 0
            st.warning(
                f"⚠️ 该情景下存款（¥{_cash_now:,.0f}）会先用完，之后从基金/股票变现继续支付生活费。\n\n"
                f"可动用资产合计（存款 + 基金/股票）= **¥{_liquid:,.0f}**，"
                f"零收入下约可支撑 **{_liq_mo} 个月**。"
            )
        else:
            st.caption("存款始终为正，无需提前变现投资")

_semi_r = _results[2]
if _semi_r["gap"] > 0:
    _extra_mo_semi = _semi_r["gap"] / max(_months_to_ret, 1)   # 简化线性：缺口÷月数
    _required_semi = semi_income + _extra_mo_semi
    if _required_semi > monthly_income * 1.5:
        st.warning(f"💡 半退休建议：窗口期仅 {_months_to_ret} 个月，需将半退休月收入提高至 ¥{_required_semi:,.0f}，"
                   "超出正常收入范围，不具备操作性。建议考虑延迟退休日期。")
    else:
        st.info(f"💡 半退休建议：将半退休月收入从 ¥{semi_income:,.0f} 提高至约 ¥{_required_semi:,.0f}，可消除退休缺口")

# B. 达标路径推算
st.markdown("**B. 达标路径推算**")
_cont_r   = _results[0]
_gap_cont = _cont_r["gap"]

if _gap_cont == 0:
    _margin_cont = _cont_r["total_2036"] - _retire_target
    st.success(f"✅ 继续工作情景已达标，安全边际 ¥{_margin_cont:,.0f}（{_margin_cont / _retire_target:.1%}）")
    st.caption("当前财务路径充裕，无需额外储蓄或推迟退休。")
else:
    st.warning(f"⚠️ 继续工作情景存在缺口 ¥{_gap_cont:,.0f}，以下两条路径可补足：")
    _col_a, _col_b = st.columns(2)

    # 路径一：月额外储蓄（复利终值公式逆推）
    _extra_mo = (
        _gap_cont * _r_mo / ((1 + _r_mo) ** _months_to_ret - 1)
        if _r_mo > 0 else _gap_cont / _months_to_ret
    )
    with _col_a:
        if _extra_mo > monthly_income:
            st.metric("月额外储蓄法", "不可行")
            st.caption(f"需每月额外储蓄 ¥{_extra_mo:,.0f}，超过月收入 ¥{monthly_income:,.0f}，"
                       f"窗口期 {_months_to_ret} 个月内无法实现")
        else:
            st.metric("月额外储蓄法", f"¥{_extra_mo:,.0f}/月")
            st.caption(f"从现在起每月额外存入并以 {proj_invest_rate:.1%} 年化增值，至 {date_retire.year} 年可补足缺口")

    # 路径二：推迟退休（简化线性估算）
    _monthly_savings = monthly_income - monthly_expense
    with _col_b:
        if _monthly_savings > 0 and _r_mo > 0:
            _inv_cash_now   = snap_now["investment"] + snap_now["cash"]
            _monthly_growth = _inv_cash_now * _r_mo + _monthly_savings
            _extra_months   = int(_gap_cont / _monthly_growth) if _monthly_growth > 0 else 9999
            _extra_years    = _extra_months / 12
            if _extra_years < 20:
                st.metric("推迟退休法", f"推迟约 {_extra_years:.1f} 年")
                st.caption(f"按现有月储蓄 ¥{_monthly_savings:,.0f} 和投资增长，预计最早 {date_retire.year + int(_extra_years) + 1} 年退休")
            else:
                st.metric("推迟退休法", "不适用")
                st.caption("缺口过大，推迟退休单独无法解决，建议优先提高月储蓄")
        else:
            st.metric("推迟退休法", "不适用")
            st.caption("月支出 ≥ 月收入，推迟退休无额外储蓄效果")

st.divider()
st.caption("数据仅用于个人财务规划参考，行情来自新浪财经 & 天天基金，存在延迟。")
