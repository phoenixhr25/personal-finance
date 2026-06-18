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
        try:
            st.session_state["_cfg"] = _json.load(uploaded)
            st.success("配置已加载")
        except Exception:
            st.error("JSON 解析失败，请检查文件格式")

    _cfg = st.session_state.get("_cfg", {})
    _g   = _cfg.get("global", {})
    _p   = _cfg.get("pension", {})
    _h   = _cfg.get("hpf", {})
    _ins = _cfg.get("insurance", [])
    _sn  = _cfg.get("snapshots", {})

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

    pension_auto = st.toggle("按城职保公式自动推算月领金额", value=bool(_p.get("auto", False)))

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
            st.caption(f"参考社平工资：¥{city_avg_wage:,.0f}/月（可在城市栏选「其他」手动修改）")

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

    # 基金
    st.subheader("④ 基金")
    fund_text = st.text_area(
        "基金列表（每行：代码,份额,成本净值,买入年-月-日）",
        value=_cfg.get("funds", "000001,10000,1.50,2023-01-01\n110022,5000,2.10,2023-06-01"),
        height=120,
    )

    st.divider()

    # A股
    st.subheader("⑤ A股/ETF")
    stock_text = st.text_area(
        "持仓列表（每行：代码,股数,成本价,买入年-月-日）",
        value=_cfg.get("stocks", "600036,100,35.00,2023-01-01\n000001,200,12.50,2023-06-01"),
        height=100,
    )

    st.divider()

    # 存款
    st.subheader("⑥ 银行存款")
    dep_text = st.text_area(
        "存款列表（每行：银行名,类型,余额,年化利率）",
        value=_cfg.get("deposits", "工商银行,活期,50000,0.002\n招商银行,定期,50000,0.020"),
        height=100,
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
        "funds":    fund_text,
        "stocks":   stock_text,
        "deposits": dep_text,
        "snapshots": {
            "b1_ph": b1_ph, "b1_ins": b1_ins, "b1_inv": b1_inv, "b1_csh": b1_csh,
            "b2_ph": b2_ph, "b2_ins": b2_ins, "b2_inv": b2_inv, "b2_csh": b2_csh,
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

PALETTE      = ["#3B82F6", "#10B981", "#F59E0B", "#EF4444",
                "#8B5CF6", "#06B6D4", "#F97316", "#84CC16"]
MORANDI_PIE  = ["#B5C4B1", "#D4B8A5", "#A8B8C8", "#C4B0B8",
                "#B8C4A8", "#C8B8A0", "#A8B8C0", "#C0B0C0"]

with chart_col:
    layer_mv  = df.groupby("layer")["market_value"].sum()
    short_labels = [l.split(" ", 1)[-1] for l in layer_mv.index]  # 去掉①②序号
    colors = MORANDI_PIE[:len(layer_mv)]

    fig, ax = plt.subplots(figsize=(5, 4.5), facecolor="#FAFAFA")
    wedges, texts, autotexts = ax.pie(
        layer_mv.values,
        labels=short_labels,
        autopct="%1.1f%%",
        startangle=90,
        colors=colors,
        wedgeprops={"linewidth": 2, "edgecolor": "white"},
        pctdistance=0.78,
    )
    for t in texts:
        t.set_fontsize(9)
    for at in autotexts:
        at.set_fontsize(8)
        at.set_color("#4A4A4A")
        at.set_fontweight("bold")
    ax.set_title("当前资产结构", fontsize=12, fontweight="bold", pad=12)
    fig.tight_layout()
    st.pyplot(fig)
    plt.close()

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

    labels = [str(date_base_1), str(date_base_2), "当前", f"{date_retire.year}推算"]
    values = [sum(snap_b1.values()), sum(snap_b2.values()),
              sum(snap_now.values()), sum(snap_ret.values())]
    bar_colors = ["#94A3B8", "#64748B", "#3B82F6", "#10B981"]

    fig2, ax2 = plt.subplots(figsize=(5, 4.5), facecolor="#FAFAFA")
    ax2.set_facecolor("#F8FAFC")
    bars = ax2.bar(labels, values, color=bar_colors, width=0.55,
                   linewidth=0, zorder=3)
    ax2.yaxis.grid(True, color="#E2E8F0", linewidth=0.8, zorder=0)
    ax2.set_axisbelow(True)

    for bar, val in zip(bars, values):
        ax2.text(bar.get_x() + bar.get_width() / 2,
                 bar.get_height() + max(values) * 0.015,
                 f"¥{val:,.0f}",
                 ha="center", va="bottom", fontsize=7.5, fontweight="bold")

    ax2.set_title("四期总资产对比", fontsize=12, fontweight="bold", pad=12)
    ax2.set_ylabel("元", fontsize=9)
    ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"¥{x/1e4:,.0f}万"))
    ax2.tick_params(axis="x", labelsize=8.5)
    ax2.tick_params(axis="y", labelsize=8)
    for spine in ["top", "right"]:
        ax2.spines[spine].set_visible(False)
    ax2.spines["left"].set_color("#CBD5E1")
    ax2.spines["bottom"].set_color("#CBD5E1")
    fig2.tight_layout()
    st.pyplot(fig2)
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
st.caption("数据仅用于个人财务规划参考，行情来自新浪财经 & 天天基金，存在延迟。")
