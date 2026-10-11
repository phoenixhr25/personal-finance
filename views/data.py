"""数据与假设：所有输入集中在这里，分四组，可以自由来回编辑。

没填写的项显示为空并提示；假设类参数留空时使用默认值，并在各页标明"默认"。
"""
import os

import streamlit as st

import calc
import state
from calc import CITY_BASES, GROUP_BASIC, GROUP_CASH, GROUP_HOLD, GROUP_SOCIAL, OTHER_CITY
from config_io import RETIRE_AGES
from views import common as C
from views import forms as F


GROUP_KEY = "w:data_group"
MODE_KEY = "w:hold_mode"
MODES = ("表格", "粘贴文本")


def _goto(group):
    st.session_state[GROUP_KEY] = group


def render(nav):
    st.title("数据与假设")
    plan = state.plan()
    C.source_banner()

    prog = calc.required_progress(state.cfg())
    done, total = prog["_all"]
    if total:
        st.progress(done / total, text=f"必填项 已填 {done} / {total}")
    st.caption("按下面四组依次填写，也可以随时跳到任意一组。输入框留空表示未填写，确实为零请填 0；"
               "留空的假设项使用默认值，并在各页标注「默认」。")

    group = st.radio("分组", calc.GROUPS, horizontal=True, key=GROUP_KEY, label_visibility="collapsed")
    cols = st.columns(len(calc.GROUPS))
    for col, g in zip(cols, calc.GROUPS):
        f, t = prog[g]
        mark = ":green[已完成]" if f == t else f":orange[缺 {t - f} 项]"
        col.caption(f"{'**' + g + '**' if g == group else g}　{mark}")

    st.divider()
    _group_status(plan, group)
    {GROUP_BASIC: _basic, GROUP_SOCIAL: _social, GROUP_HOLD: lambda: _holdings(plan),
     GROUP_CASH: _cash}[group]()

    # 上一组 / 下一组
    st.divider()
    i = calc.GROUPS.index(group)
    c1, c2 = st.columns(2)
    if i > 0:
        c1.button(f"← {calc.GROUPS[i - 1]}", key="grp_prev", on_click=_goto,
                  args=(calc.GROUPS[i - 1],), use_container_width=True)
    if i < len(calc.GROUPS) - 1:
        c2.button(f"{calc.GROUPS[i + 1]} →", key="grp_next", type="primary", on_click=_goto,
                  args=(calc.GROUPS[i + 1],), use_container_width=True)
    elif nav is not None:
        c2.page_link(nav.overview, label="查看测算结果", use_container_width=True)
    if done == total and total and nav is not None and i < len(calc.GROUPS) - 1:
        st.success("必填项已全部填写，可以到「概览」查看结果，也可以继续完善其他项。")
        st.page_link(nav.overview, label="查看测算结果")

    with st.expander("高级设置（可选）：历史快照、目标资产配置"):
        _advanced()
    with st.expander("使用说明（完整版）"):
        try:
            with open(os.path.join(os.path.dirname(os.path.dirname(__file__)), "USER_GUIDE.md"),
                      encoding="utf-8") as f:
                st.markdown(f.read())
        except OSError:
            st.caption("没有找到使用说明文件，请查看仓库里的 USER_GUIDE.md。")
    with st.expander("重新开始"):
        st.caption("清空页面上的全部数据。建议先在侧边栏导出当前配置。")
        st.button("清空当前数据", key="clear_all", on_click=state.clear_all)


def _group_status(plan, group):
    items = [i for i in plan.issues if i.group == group]
    miss = [i for i in items if i.level == "missing"]
    bad = [i for i in items if i.level == "invalid"]
    if not miss and not bad:
        if state.has_data():
            st.caption(":green[这一组的必填项已填写]")
        return
    if miss:
        st.warning("这一组还缺：" + "；".join(
            i.label + ("" if i.message == "未填写" else f"（{i.message}）") for i in miss))
    for i in bad:
        st.warning(f"{i.label}：{i.message}")


# ── 1 退休目标与基本信息 ─────────────────────────────────────────────────
def _basic():
    F.date_field(("global", "date_retire"), "计划停止工作日期", required=True,
                 help="你计划不再靠工资生活的日期，不一定等于法定退休日期。")
    F.number(("sim", "retire_expense_mo"), "退休后每月支出（元）", step=500.0, required=True,
             help="按今天的物价估算。未来的通胀由「通胀率」假设处理，不用在这里加。")
    st.markdown("**开始领取养老金的日期**")
    auto = state.get("pension", "auto", default=True)
    has_birth = state.get("pension", "birth") is not None
    F.date_field(("pension", "birth"), "出生年月", help="填写后按渐进式延迟退休规则推算领取日期，只看年月。")
    F.select(("pension", "retire_age"), "原法定退休年龄（改革前）", list(RETIRE_AGES),
             required=bool(auto) or has_birth,
             help="男职工 60；原 55 岁退休的女职工 55；原 50 岁退休的女职工 50。")
    start, age_m, how = calc.pension_start_info(state.cfg())
    derived = age_m is not None
    if derived:
        n = calc.annuity_months(age_m / 12)
        st.success(f"法定退休年龄 {age_m // 12} 岁 {age_m % 12} 个月，"
                   f"{start.year} 年 {start.month} 月开始领取，计发月数 {n}。")
    F.date_field(("global", "date_pension_start"), "开始领取养老金的日期（手填）",
                 required=not derived, disabled=derived,
                 help="没有出生年月时手填。填了出生年月和原法定年龄后，以推算结果为准。")


# ── 2 养老金、公积金、保险 ───────────────────────────────────────────────
def _social():
    st.markdown("**养老保险**")
    F.number(("pension", "account"), "个人账户余额（元）", step=1000.0, required=True,
             help="在社保 App 查询。")
    F.toggle(("pension", "auto"), "按城职保公式推算月领金额", default=True)
    if state.get("pension", "auto", default=True):
        F.select(("pension", "city"), "所在城市", list(CITY_BASES), required=True)
        city = state.get("pension", "city")
        if city == OTHER_CITY:
            F.number(("pension", "city_wage"), f"{calc.CITY_BASE_YEAR} 年计发基数（元/月）",
                     step=100.0, required=True, help="当地人社部门每年公布的「基本养老金计发基数」。")
        elif city:
            base, verified = CITY_BASES[city]
            st.caption(f"{calc.CITY_BASE_YEAR} 年计发基数：¥{base:,.0f}/月" +
                       ("（当地公布值）" if verified else "（参考值，未核实为计发基数，建议选「其他」手动输入）"))
        F.number(("pension", "contrib_years"), "预计缴费年限（年）", kind="int", required=True,
                 help="到领取时累计的缴费年限，含今后还会缴的年份。")
        F.number(("pension", "contrib_index"), "缴费指数", step=0.05, fmt="%.2f", required=True,
                 help="缴费基数 ÷ 社平工资，按社平基数缴纳填 1.0，一般在 0.6～3 之间。")
        F.date_field(("pension", "contrib_end"), "个人账户缴费到",
                     default_hint="计划停止工作日期",
                     help="今后还会缴社保到哪天。每月按 计发基数 × 缴费指数 × 8% 记入个人账户。")
    else:
        F.number(("pension", "monthly"), "预计养老金月领（元，按今天的购买力）", step=100.0, required=True,
                 help="从社保部门的测算或自己的估算得到。")

    st.markdown("**住房公积金**")
    F.number(("hpf", "balance"), "公积金余额（元）", step=1000.0, required=True)

    st.markdown("**储蓄险**")
    F.insurance_count("保单数量", help="没有储蓄险填 0。")
    pols = state.cfg().get("insurance") or []
    for i in range(len(pols)):
        with st.expander(f"保单 {i + 1}", expanded=(i == 0)):
            F.text_line(("insurance", i, "name"), "保单名称（可选）", placeholder=f"储蓄险{i + 1}")
            F.number(("insurance", i, "cash_value"), "现金价值（元）", step=1000.0, required=True,
                     help="现在退保能拿到的金额。")
            F.number(("insurance", i, "cost_basis"), "已缴保费（元）", step=1000.0, required=True)
            F.number(("insurance", i, "annual_premium"), "年缴保费（元）", step=1000.0, required=True,
                     help="已缴完填 0。")
            F.number(("insurance", i, "premium_years_left"), "还需缴年", kind="int", required=True)
            F.number(("insurance", i, "maturity_value"), "满期金额（元）", step=1000.0, required=True,
                     help="按已包含现金价值处理：持有到期只拿满期金，不再另加现金价值。")
            F.number(("insurance", i, "years_to_maturity"), "距满期年", kind="int", required=True)
            F.number(("insurance", i, "policy_irr"), "保单 IRR", step=0.005, fmt="%.3f", required=True,
                     help=F.RATE_HELP + "。只影响年化展示和退休推算，不知道可填 0.03 的估计值。")


# ── 3 基金、股票、存款 ───────────────────────────────────────────────────
HOLDINGS = (
    (("funds_dca",), "funds_dca", "定投基金（A 类）",
     "每行一只：代码、份额、持有成本（总额）、当前市值（总额）。不需要买入日期，不联网取行情。",
     "270023, 3250.58, 17111.57, 20139.62", calc.parse_fund_dca),
    (("stocks",), "stocks", "单笔买入 / ETF / A 股（B 类）",
     "每行一笔：代码、股数、成本价、买入日期；当前价可选，填了就不联网取行情。",
     "600036, 1500, 35.00, 2023-06-01, 40.00", calc.parse_stocks),
    (("deposits",), "deposits", "银行存款",
     "每行一笔：银行、类型（活期、定期等标签）、余额；年化利率可选，不填按 0。",
     "示例银行, 活期, 100000, 0.002", calc.parse_deposits),
)


def _holdings(plan):
    st.radio("录入方式", MODES, horizontal=True, key=MODE_KEY,
             on_change=F.drop_holding_widget_state,
             help="表格适合逐笔填写；从理财 App 里一次复制多行时，用「粘贴文本」更快。两种方式改的是同一份数据。")
    mode = st.session_state.get(MODE_KEY, MODES[0])
    st.caption("手机屏幕较窄时，表格要左右滑动，用「粘贴文本」更方便。")
    for path, kind, title, hint, example, parser in HOLDINGS:
        st.markdown(f"**{title}**")
        st.caption(hint)
        if mode == MODES[0]:
            F.holdings_table(path, kind)
        else:
            F.holdings(path, title, example=example)
        _count(kind, parser)


def _count(key, parser):
    txt = state.cfg().get(key)
    if txt:
        items, bad = parser(txt)
        st.caption(f"已识别 {len(items)} 笔" + (f"，{len(bad)} 行无法识别（已忽略）" if bad else ""))


# ── 4 收支与未来假设 ─────────────────────────────────────────────────────
def _cash():
    F.number(("sim", "monthly_income"), "每月税后收入（元）", step=500.0, required=True,
             help="用来推算停止工作前每月的结余。")
    F.number(("sim", "monthly_expense"), "每月总支出（元）", step=500.0, required=True,
             help="含房贷、生活等全部开销。按固定金额推算，不随通胀增长。")

    with st.expander("可选项与未来假设（都有默认值，可以先不改）"):
        F.number(("sim", "semi_income"), "半退休月收入（元，可选）", step=500.0,
                 help="不填则不计算「半退休」情景。")
        F.number(("sim", "income_interrupt_months"), "收入中断月数", kind="int",
                 default_hint="12", help="「收入中断」情景：从今天起收入为 0 的月数。")
        st.markdown("**未来假设**（留空使用默认值）")
        F.number(("global", "inflation"), "通胀率", step=0.005, fmt="%.3f", default_hint="2.5%",
                 help=F.RATE_HELP + "。把未来的名义金额折成今日购买力。"
                      "近两年实际 CPI 接近 0，十几年的跨度可以自己判断。")
        F.number(("global", "proj_invest_rate"), "退休前投资年化", step=0.01, fmt="%.3f",
                 default_hint="5.0%",
                 help=F.RATE_HELP + "。只用于推算到停止工作日的投资资产，不要用历史年化。")
        F.number(("global", "discount_rate"), "折现率", step=0.005, fmt="%.3f", default_hint="3.0%",
                 help=F.RATE_HELP + "。只用于「资产」页的 NPV，不影响退休目标比较。")
        F.number(("pension", "rate"), "个人账户记账利率", step=0.001, fmt="%.3f", default_hint="1.5%",
                 help=F.RATE_HELP + "。人社部每年 6 月公布：2023 年 3.97%、2024 年 2.62%、2025 年 1.5%。")
        F.number(("pension", "wage_growth"), "计发基数年增长率", step=0.005, fmt="%.3f",
                 default_hint="2.0%", help=F.RATE_HELP + "。深圳 2024→2025 涨约 1%，广东涨约 2%。")
        F.number(("hpf", "years"), "公积金预计几年后动用", step=1.0, default_hint="10 年",
                 help="只影响公积金的 NPV。")
        F.date_field(("global", "date_life_end"), "预期寿命终止日", default_hint="2080-01-01",
                     help="只影响 NPV 和等值月均的计算区间。")


# ── 高级 ─────────────────────────────────────────────────────────────────
def _advanced():
    st.markdown("**历史快照**（估算即可，只用于「资产」页的趋势图，不影响退休测算）")
    c1, c2 = st.columns(2)
    with c1:
        F.date_field(("global", "date_base_1"), "基期日期")
        for k, lbl in (("b1_ph", "养老 + 公积金"), ("b1_ins", "储蓄险"), ("b1_inv", "投资"), ("b1_csh", "现金")):
            F.number(("snapshots", k), lbl, step=1000.0)
    with c2:
        F.date_field(("global", "date_base_2"), "对比节点日期")
        for k, lbl in (("b2_ph", "养老 + 公积金"), ("b2_ins", "储蓄险"), ("b2_inv", "投资"), ("b2_csh", "现金")):
            F.number(("snapshots", k), lbl, step=1000.0)
    st.markdown("**目标资产配置（%）**（用于「资产」页的结构检查，合计建议 100%）")
    cols = st.columns(4)
    for col, (k, lbl) in zip(cols, (("target_ph", "社保层"), ("target_ins", "保险层"),
                                    ("target_inv", "投资层"), ("target_csh", "现金层"))):
        with col:
            F.number(("sim", k), lbl, kind="int", step=5)
