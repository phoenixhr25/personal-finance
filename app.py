"""
个人资产收益整合表 — Streamlit Web App
运行：streamlit run app.py
"""

import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib
from datetime import date, datetime

from finance_engine import (
    compute_pension, compute_hpf, compute_insurance,
    compute_funds, compute_stocks, compute_deposits,
    build_rows, weighted_avg_return, retirement_projection,
    eaa, cagr,
)
from market_api import fetch_fund_prices, fetch_stock_prices

# ── 字体 ──────────────────────────────────────────────────────────────────
for font in ["PingFang SC", "PingFang HK", "Heiti TC", "STHeiti", "SimHei", "DejaVu Sans"]:
    if font in [f.name for f in matplotlib.font_manager.fontManager.ttflist]:
        matplotlib.rcParams["font.family"] = font
        break
matplotlib.rcParams["axes.unicode_minus"] = False

st.set_page_config(page_title="个人资产收益整合表", page_icon="📊", layout="wide")

# ═══════════════════════════════════════════════════════
# 侧边栏：参数输入
# ═══════════════════════════════════════════════════════
with st.sidebar:
    st.title("📋 参数设置")
    st.caption("填完后点击「运行计算」")

    # 全局
    st.subheader("全局参数")
    discount_rate    = st.number_input("折现率", value=0.03, step=0.005, format="%.3f")
    proj_invest_rate = st.number_input("退休推算投资年化", value=0.05, step=0.01, format="%.2f",
                                       help="保守3-4%，中性5-6%，激进7-8%")
    date_retire   = st.date_input("预计退休日期", value=date(2040, 1, 1))
    date_life_end = st.date_input("预期寿命终止日", value=date(2080, 1, 1))
    date_base_1   = st.date_input("基期起始", value=date(2020, 1, 1))
    date_base_2   = st.date_input("对比节点", value=date(2023, 1, 1))

    st.divider()

    # 养老
    st.subheader("① 养老保险")
    pension_account = st.number_input("个人账户余额", value=100_000.0, step=1000.0)
    pension_monthly = st.number_input("预计月领金额", value=3_000.0, step=100.0)
    pension_rate    = st.number_input("账户年化利率", value=0.055, step=0.001, format="%.3f")

    st.divider()

    # 公积金
    st.subheader("② 住房公积金")
    hpf_balance = st.number_input("当前余额", value=80_000.0, step=1000.0, key="hpf_bal")
    hpf_years   = st.number_input("预计几年后动用", value=10.0, step=1.0)

    st.divider()

    # 储蓄险（固定3张，可扩展）
    st.subheader("③ 储蓄险")
    ins_count = st.number_input("保单数量", value=1, min_value=0, max_value=5, step=1)
    ins_inputs = []
    for i in range(int(ins_count)):
        with st.expander(f"保单 {i+1}", expanded=(i == 0)):
            ins_inputs.append({
                "name":              st.text_input("保单名称", value=f"储蓄险{i+1}", key=f"ins_name_{i}"),
                "cash_value":        st.number_input("现金价值", value=50_000.0, key=f"ins_cv_{i}"),
                "cost_basis":        st.number_input("已缴保费", value=50_000.0, key=f"ins_cost_{i}"),
                "annual_premium":    st.number_input("年缴保费", value=0.0, key=f"ins_prem_{i}"),
                "premium_years_left":st.number_input("还需缴年", value=0, key=f"ins_left_{i}"),
                "maturity_value":    st.number_input("满期金额", value=50_000.0, key=f"ins_mat_{i}"),
                "years_to_maturity": st.number_input("距满期年", value=0, key=f"ins_yrs_{i}"),
                "policy_irr":        st.number_input("保单 IRR", value=0.030, format="%.3f", key=f"ins_irr_{i}"),
            })

    st.divider()

    # 基金
    st.subheader("④ 基金")
    fund_text = st.text_area(
        "基金列表（每行：代码,份额,成本净值,买入年-月-日）",
        value="000001,10000,1.50,2023-01-01\n110022,5000,2.10,2023-06-01",
        height=120,
    )

    st.divider()

    # A股
    st.subheader("⑤ A股/ETF")
    stock_text = st.text_area(
        "持仓列表（每行：代码,股数,成本价,买入年-月-日）",
        value="600036,100,35.00,2023-01-01\n000001,200,12.50,2023-06-01",
        height=100,
    )

    st.divider()

    # 存款
    st.subheader("⑥ 银行存款")
    dep_text = st.text_area(
        "存款列表（每行：银行名,类型,余额,年化利率）",
        value="工商银行,活期,50000,0.002\n招商银行,定期,50000,0.020",
        height=100,
    )

    st.divider()

    # 历史快照
    st.subheader("历史快照（估算即可）")
    col1, col2 = st.columns(2)
    with col1:
        st.caption("基期起始")
        b1_ph  = st.number_input("养老+公积金", value=50_000.0, key="b1ph")
        b1_ins = st.number_input("储蓄险",      value=10_000.0, key="b1ins")
        b1_inv = st.number_input("投资",         value=30_000.0, key="b1inv")
        b1_csh = st.number_input("现金",         value=50_000.0, key="b1csh")
    with col2:
        st.caption("对比节点")
        b2_ph  = st.number_input("养老+公积金", value=120_000.0, key="b2ph")
        b2_ins = st.number_input("储蓄险",      value=30_000.0, key="b2ins")
        b2_inv = st.number_input("投资",         value=100_000.0, key="b2inv")
        b2_csh = st.number_input("现金",         value=100_000.0, key="b2csh")

    run = st.button("🚀 运行计算", type="primary", use_container_width=True)

# ═══════════════════════════════════════════════════════
# 主界面
# ═══════════════════════════════════════════════════════
st.title("📊 个人资产收益整合表")
st.caption("管理会计利润表结构 · 按流动性分层（低 → 高）")

if not run:
    st.info("← 在左侧填写参数后，点击「运行计算」")
    st.stop()

today = date.today()

# ── 解析文本输入 ──────────────────────────────────────
def parse_funds(text):
    result = []
    for line in text.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4:
            continue
        try:
            result.append({
                "code": parts[0], "shares": float(parts[1]),
                "cost_nav": float(parts[2]),
                "buy_date": datetime.strptime(parts[3], "%Y-%m-%d").date(),
                "manual_nav": None,
            })
        except Exception:
            pass
    return result

def parse_stocks(text):
    result = []
    for line in text.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4:
            continue
        try:
            result.append({
                "code": parts[0], "shares": int(parts[1]),
                "cost_price": float(parts[2]),
                "buy_date": datetime.strptime(parts[3], "%Y-%m-%d").date(),
                "manual_price": None,
            })
        except Exception:
            pass
    return result

def parse_deposits(text):
    result = []
    for line in text.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4:
            continue
        try:
            result.append({
                "bank": parts[0], "type": parts[1],
                "balance": float(parts[2]), "rate": float(parts[3]),
                "term_years": 0,
            })
        except Exception:
            pass
    return result

fund_input_raw  = parse_funds(fund_text)
stock_input_raw = parse_stocks(stock_text)
dep_input_raw   = parse_deposits(dep_text)

# ── 拉取行情 ──────────────────────────────────────────
with st.spinner("正在拉取实时行情…"):
    fund_input  = fetch_fund_prices(fund_input_raw)
    stock_input = fetch_stock_prices(stock_input_raw)

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
    display["市值"]  = display["市值"].map("¥{:,.0f}".format)
    display["成本"]  = display["成本"].map("¥{:,.0f}".format)
    display["浮盈"]  = display["浮盈"].map("¥{:+,.0f}".format)
    display["年化收益率"] = display["年化收益率"].map("{:.1%}".format)
    display["NPV"]  = display["NPV"].map("¥{:,.0f}".format)
    st.dataframe(display, use_container_width=True, hide_index=True)

st.divider()

# ── 图表 ──────────────────────────────────────────────
st.subheader("资产结构 & 四期对比")
chart_col, proj_col = st.columns([1, 1])

# 饼图
with chart_col:
    layer_mv = df.groupby("layer")["market_value"].sum()
    fig, ax = plt.subplots(figsize=(5, 4))
    ax.pie(layer_mv.values, labels=layer_mv.index, autopct="%1.1f%%", startangle=90)
    ax.set_title("当前资产结构")
    st.pyplot(fig)
    plt.close()

# 四期柱状图
with proj_col:
    snap_now = {
        "pension_hpf": pension["personal_account"] + hpf["balance"],
        "insurance":   sum(i["cash_value"] for i in ins_list),
        "investment":  sum(f["market_value"] for f in fund_list) + sum(s["market_value"] for s in stock_list),
        "cash":        sum(d["balance"] for d in dep_list),
    }
    snap_b1 = {"pension_hpf": b1_ph, "insurance": b1_ins, "investment": b1_inv, "cash": b1_csh}
    snap_b2 = {"pension_hpf": b2_ph, "insurance": b2_ins, "investment": b2_inv, "cash": b2_csh}

    y_to_retire = (date_retire - today).days / 365.25
    snap_ret = retirement_projection(snap_now, proj_invest_rate, ins_inputs, y_to_retire)

    totals = {
        str(date_base_1): sum(snap_b1.values()),
        str(date_base_2): sum(snap_b2.values()),
        "当前":           sum(snap_now.values()),
        f"{date_retire.year}推算": sum(snap_ret.values()),
    }
    fig2, ax2 = plt.subplots(figsize=(5, 4))
    bars = ax2.bar(totals.keys(), totals.values(), color=["#4C72B0","#DD8452","#55A868","#C44E52"])
    ax2.bar_label(bars, fmt="¥%.0f", padding=3, fontsize=8)
    ax2.set_title("四期总资产对比")
    ax2.set_ylabel("元")
    ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"¥{x/1e4:.0f}万"))
    st.pyplot(fig2)
    plt.close()

st.divider()

# ── 退休推算说明 ──────────────────────────────────────
st.subheader("退休推算")
r1, r2, r3 = st.columns(3)
retire_total = sum(snap_ret.values())
now_total    = sum(snap_now.values())
r1.metric("2036 推算总资产", f"¥{retire_total:,.0f}")
r2.metric("增量", f"¥{retire_total - now_total:+,.0f}")
r3.metric("推算用投资年化", f"{proj_invest_rate:.1%}", help="在左侧「退休推算投资年化」修改")
st.caption(f"⚠️ 加权历史年化 {w_return:.2%} 含历史浮盈，不可直接用于预测。此处使用手动设定的 {proj_invest_rate:.1%}。")
st.caption("⚠️ 推算不含未来工资转入，为「停止工作后纯靠现有资产增值」的保守估算。")

st.divider()
st.caption("数据仅用于个人财务规划参考，行情来自新浪财经 & 天天基金，存在延迟。")
