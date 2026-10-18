"""概览：先看懂退休测算结果。

结论 → 目标构成 → 过渡期 → 养老期 → 关键假设 → 入口；计算依据放在可展开的区块。
所有数字来自 state.plan()，与「情景」页是同一份结果。
"""
import streamlit as st

import state
from views import common as C


def render(nav):
    st.title("概览")
    st.markdown('<div class="pf-lead">按你现在的假设，停止工作后的资产够不够。</div>',
                unsafe_allow_html=True)
    plan = state.plan()
    C.source_banner()
    C.mode_banner(plan)

    if C.plan_error(plan):
        return
    if not state.has_data():
        _empty_state(nav)
        return
    if not plan.retire_ready:
        _missing(plan, nav)
        return
    _conclusion(plan, nav)


# ── 首次打开 ─────────────────────────────────────────────────────────────
def _empty_state(nav):
    st.write("把社保、公积金、保险、基金、股票和存款放进同一张表，按流动性分层折算，"
             "再回答一个问题：停止工作之后，资产能不能覆盖目标。")
    c1, c2, c3 = st.columns(3)
    with c1.container(border=True):
        st.markdown("**体验虚构示例**")
        st.caption("用一个虚构人物的数据，看一遍完整结果。")
        st.button("载入示例", key="start_demo", on_click=state.load_demo, use_container_width=True)
    with c2.container(border=True):
        st.markdown("**导入配置**")
        st.caption("之前导出的 JSON 配置文件。")
        st.file_uploader("导入配置", type=["json"], key="up_main", label_visibility="collapsed")
    with c3.container(border=True):
        st.markdown("**填写我的数据**")
        st.caption("没有配置文件也可以。快速估算只填 9 项合计数，约 3 分钟，得到粗略结论；"
                   "完整填写逐项录入，更准确。随时可以切换。")
        st.button("快速估算", key="start_quick", type="primary", use_container_width=True,
                  on_click=state.start_quick)
        if st.button("完整填写", key="start_fill", use_container_width=True):
            st.switch_page(nav.data)
    st.caption("数据只在本次使用期间经过服务器内存，不写入文件或数据库。"
               f"[隐私说明]({C.PRIVACY_URL})。完整使用说明在「数据与假设」页底部。")


# ── 必填项缺失 ───────────────────────────────────────────────────────────
def _missing(plan, nav):
    miss = plan.missing
    st.subheader("还差几项信息，才能给出测算")
    st.write(f"必填项还缺 **{len(miss)}** 项。没填的项不会用默认值顶替，"
             "以免得出一个看起来属于你、其实不是你的结论。")
    for group in dict.fromkeys(i.group for i in miss):
        st.markdown(f"**{group}**")
        C.issue_lines([i for i in miss if i.group == group])
    if nav is not None:
        c1, c2 = st.columns(2)
        if c1.button("继续填写", key="continue_fill", type="primary", use_container_width=True):
            st.switch_page(nav.data)
        if plan.assets_ready:
            c2.page_link(nav.assets, label="先看已填写的资产", use_container_width=True)
    st.caption("填 0 和不填是两回事：确实没有的项请明确填 0，或勾选「暂无」。")


# ── 结论 ─────────────────────────────────────────────────────────────────
def _conclusion(plan, nav):
    head, t = plan.headline, plan.target

    # 日期
    note = ""
    if plan.pension_age_months is not None:
        a = plan.pension_age_months
        note = f"（按延迟退休规则推算，法定退休年龄 {a // 12} 岁 {a % 12} 个月）"
    elif plan.pension_start_note:
        note = f"（{plan.pension_start_note}）"
    st.markdown(f"计划 **{C.ym(plan.date_retire)}** 停止工作，"
                f"**{C.ym(plan.pension_start)}** 开始领取养老金{note}。")

    if plan.date_retire <= plan.today:
        st.info("计划停止工作的日期已过。资产不再向后推算，直接用今天的资产与目标比较。")

    # 结论
    with st.container(border=True):
        rough = "粗估：" if plan.quick else ""
        if t["total"] <= 0:
            st.markdown(f"### {rough}按当前假设，两阶段目标为 ¥0")
            st.write(f"退休时资产（今日购买力）{C.wan(head['real'])}。目标为 0，不计算余量比例。")
        elif head["meets"]:
            st.markdown(f"### {rough}按当前假设，测算资产 :green[高于] 目标 {C.wan(head['margin'])}")
            st.write(f"资产超过目标的 {C.pct(head['margin_pct'])}（余量 ÷ 目标）。")
        else:
            st.markdown(f"### {rough}按当前假设，测算资产 :orange[低于] 目标 {C.wan(-head['margin'])}")
            st.write(f"缺口相当于目标的 {C.pct(-head['margin_pct'])}。")
        st.caption("口径：「继续工作」情景下，到计划停止工作日的资产与两阶段目标比较，"
                   "均为今日购买力。余量比例表示资产超出目标的幅度，不是成功概率，"
                   "也不构成对退休安全的保证。")

    # 资产 vs 目标
    c1, c2, c3 = st.columns(3)
    c1.metric("退休时资产", C.wan(head["real"]), help=f"{C.yuan(head['real'])}（今日购买力）")
    c2.metric("两阶段目标", C.wan(t["total"]), help=f"{C.yuan(t['total'])}（过渡期消耗 + 养老期补充）")
    c3.metric("余量" if head["meets"] else "缺口", C.wan(abs(head["margin"])),
              help=C.yuan(abs(head["margin"])))
    st.caption("三项均为今日购买力：未来的名义金额已按通胀率折回今天，"
               "与按今天物价填写的退休支出可以直接比较。")

    # 过渡期
    st.markdown("#### 过渡期：停止工作到开始领养老金")
    with st.container(border=True):
        if t["bridge_months"] == 0:
            st.write("领取养老金的时间不晚于停止工作的时间，没有过渡期。")
        else:
            a, b, c = st.columns(3)
            a.metric("过渡期", f"{t['bridge_months']} 个月",
                     help=f"{C.ym(plan.date_retire)} → {C.ym(plan.pension_start)}")
            b.metric("所需资金", C.wan(t["bridge_cost"]), help=C.yuan(t["bridge_cost"]))
            c.metric("退休时流动资产", C.wan(head["liquid_real"]),
                     help=f"基金 + 股票 + 存款，今日购买力 {C.yuan(head['liquid_real'])}")
            if head["liquid_ok"]:
                st.write(":green[流动资产可以覆盖过渡期所需资金。]")
            else:
                st.warning(f"流动资产不足以覆盖过渡期，差 {C.wan(head['liquid_short'])}。"
                           "不足的部分可能需要动用保险或公积金。")

    # 养老期
    st.markdown("#### 养老期：开始领养老金之后")
    with st.container(border=True):
        a, b, c = st.columns(3)
        a.metric("养老金月领", C.yuan(t["pension_real"]), help="今日购买力")
        b.metric("退休月支出", C.yuan(plan.retire_expense), help="按今天的物价")
        c.metric("每月缺口", C.yuan(t["gap_mo"]))
        if t["gap_mo"] > 0:
            st.write(f"每月缺口需要资产补充，按 4% 法则折算为 {C.wan(t['phase2'])}。")
        else:
            st.write(":green[养老金覆盖退休月支出，养老期不需要靠资产补充。]")

    # 其他情景（已有计算）
    if head["uncovered"]:
        st.error(f"按「继续工作」推算，到停止工作前存款和投资全部用完后仍有 {C.yuan(head['uncovered'])} "
                 "的赤字，已作为负现金计入退休资产。请先检查每月收入和支出。")
    others = [s for s in plan.scenarios[1:] if s.get("available") and not s["meets"]]
    if others:
        txt = "；".join(f"「{s['name']}」低于目标 {C.wan(-s['margin'])}" for s in others)
        st.warning(f"其他情景：{txt}。")
    if plan.price_failed:
        st.warning(f"{len(plan.price_failed)} 个持仓没有取到行情（{', '.join(plan.price_failed)}），"
                   "已按成本价计算。可在持仓里填写当前价或当前市值。")
    for p in plan.problems:
        st.caption(f":orange[{p.group} · {p.label}：{p.message}]")

    # 关键假设
    st.markdown("#### 关键假设")
    A = plan.assumptions
    st.markdown(
        f"- **通胀率** {C.pct(A['inflation'][0])}{C.default_tag(A['inflation'][1])}："
        "把未来金额折成今日购买力\n"
        f"- **退休前投资年化** {C.pct(A['proj_invest_rate'][0])}"
        f"{C.default_tag(A['proj_invest_rate'][1])}：只用于推算到停止工作日的资产\n"
        f"- **养老金** {_pension_text(plan)}")

    # 入口
    st.divider()
    cols = st.columns(4)
    if nav is not None:
        cols[0].page_link(nav.assets, label="查看资产", use_container_width=True)
        cols[1].page_link(nav.scenarios, label="比较情景", use_container_width=True)
        cols[2].page_link(nav.data, label="修改数据", use_container_width=True)
    show = cols[3].toggle("查看计算依据", key="ov_basis")

    # 辅助摘要
    m1, m2 = st.columns(2)
    m1.metric("当前总资产", C.wan(plan.total_mv), help=C.yuan(plan.total_mv))
    m2.metric("可投资资产", C.wan(plan.investable_now),
              help=f"基金 + 股票 + 存款 {C.yuan(plan.investable_now)}")
    st.caption("总资产含养老保险个人账户、公积金和保险现金价值，其中不少不能随时取出。")

    if show:
        _basis(plan)


def _pension_text(plan):
    d = plan.pension_detail
    if plan.pension_mode == "manual":
        return f"手动填写，每月 {C.yuan(plan.pension_real)}（按今天的购买力）"
    rate, r_def = plan.assumptions["account_rate"]
    growth, g_def = plan.assumptions["wage_growth"]
    return (f"按城职保公式推算（{d['city']}计发基数 {C.yuan(d['base'])}，"
            f"缴费 {d['contrib_years']} 年，缴费指数 {d['contrib_index']}；"
            f"记账利率 {C.pct(rate)}{C.default_tag(r_def)}，"
            f"计发基数增速 {C.pct(growth)}{C.default_tag(g_def)}）")


# ── 计算依据 ─────────────────────────────────────────────────────────────
def _basis(plan):
    A, t, head, d = plan.assumptions, plan.target, plan.headline, plan.pension_detail
    with st.container(border=True):
        st.markdown("##### 计算依据")
        st.markdown("**1. 退休时资产折成今日购买力**")
        st.write(f"{plan.date_retire.year} 年名义资产 {C.yuan(head['nominal'])} ÷ 折算系数 "
                 f"{plan.deflator:.3f}（通胀 {C.pct(A['inflation'][0])}，距停止工作 "
                 f"{plan.years_to_retire:.1f} 年）= {C.yuan(head['real'])}")
        st.markdown("**2. 两阶段目标**")
        st.write(f"过渡期消耗 = 退休月支出 × 过渡期月数 = {C.yuan(plan.retire_expense)} × "
                 f"{t['bridge_months']} = {C.yuan(t['bridge_cost'])}（不计利息）")
        st.write(f"养老期补充 = max(0, 退休月支出 − 养老金月领) × 12 ÷ 4% = "
                 f"{C.yuan(t['gap_mo'])} × 12 ÷ 4% = {C.yuan(t['phase2'])}")
        st.write(f"目标 = {C.yuan(t['bridge_cost'])} + {C.yuan(t['phase2'])} = {C.yuan(t['total'])}")
        st.markdown("**3. 养老金月领**")
        if plan.pension_mode == "auto":
            n_dist = d["annuity_months"]
            st.write(
                f"基础养老金 = 领金时计发基数 × (1 + 缴费指数) ÷ 2 × 缴费年限 × 1%；"
                f"个人账户养老金 = 领金时账户余额 ÷ 计发月数（{n_dist}）。")
            st.write(
                f"计发基数 {C.yuan(d['base'])}（2025 年），按 {C.pct(A['wage_growth'][0])} 增长 "
                f"{d['growth_years']} 年；账户按 {C.pct(A['account_rate'][0])} 记账利率增长，"
                f"并计入到 {d['contrib_end']} 的 {d['contrib_months']} 个月缴费。")
            st.write(f"{plan.pension_start.year} 年名义月领 {C.yuan(plan.pension_nominal)}，"
                     f"折今日购买力 {C.yuan(plan.pension_real)}。")
        else:
            st.write(f"手动填写 {C.yuan(plan.pension_real)}/月，按今天的购买力处理。")
        st.markdown("**4. 折现率**")
        st.write(f"折现率 {C.pct(A['discount_rate'][0])}{C.default_tag(A['discount_rate'][1])}"
                 "只用于「资产」页的 NPV，不影响上面的目标比较。")
        st.caption("未扣养老金的传统 4% 参考值和各冲击的明细，见「情景」页的「方法对照」。")
