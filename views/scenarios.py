"""情景：继续工作 / 收入中断 / 半退休放在同一张表里，用与概览相同的两阶段目标比较。"""
import pandas as pd
import streamlit as st

import state
from views import common as C


def render(nav):
    st.title("情景")
    plan = state.plan()
    C.source_banner()
    C.mode_banner(plan)
    if C.plan_error(plan):
        return
    if not state.has_data():
        st.info("还没有数据。请先到「概览」载入示例，或到「数据与假设」填写。")
        return
    if not plan.retire_ready:
        st.subheader("情景比较需要先补全退休测算所需的信息")
        for group in dict.fromkeys(i.group for i in plan.missing):
            st.markdown(f"**{group}**")
            C.issue_lines([i for i in plan.missing if i.group == group])
        if nav is not None:
            st.page_link(nav.data, label="去「数据与假设」补全")
        return

    t = plan.target
    st.write(f"三种情景与「概览」使用同一个两阶段目标 **{C.wan(t['total'])}**"
             f"（过渡期 {C.wan(t['bridge_cost'])} + 养老期补充 {C.wan(t['phase2'])}），"
             "资产均折成今日购买力。")
    st.caption("三个情景是你设定的几种路径，不是概率样本，不能据此推算成功的可能性。")

    _comparison(plan)
    _notes(plan)
    _paths(plan)
    _stress(plan)
    _reference(plan)


def _cover(s):
    return "无过渡期" if s["liquid_ok"] is None else ("覆盖" if s["liquid_ok"] else "不足")


def _comparison(plan):
    st.subheader("情景比较")
    names = [s["name"] for s in plan.scenarios]
    ok = [s for s in plan.scenarios if s.get("available")]
    # 主表：短标签 + 万元，窄屏下会换行而不是横向滚动
    main = {"余量（+）/ 缺口（−）": [], "余量占目标": [], "退休资产": [], "两阶段目标": [],
            "过渡期流动资产": [], "存款耗尽": [], "未覆盖赤字": []}
    for s in plan.scenarios:
        if not s.get("available"):
            for k in main:
                main[k].append("未填半退休月收入" if k == "余量（+）/ 缺口（−）" else "—")
            continue
        main["余量（+）/ 缺口（−）"].append(C.wan(s["margin"], True))
        main["余量占目标"].append(C.pct(s["margin_pct"], signed=True) if s["margin_pct"] is not None else "—")
        main["退休资产"].append(C.wan(s["real"]))
        main["两阶段目标"].append(C.wan(s["target"]))
        main["过渡期流动资产"].append(f"{C.wan(s['liquid_real'])}，{_cover(s)}")
        main["存款耗尽"].append("不耗尽" if s["cash_depl"] is None else str(s["cash_depl"])[:7])
        main["未覆盖赤字"].append("无" if not s["uncovered"] else C.wan(-s["uncovered"]))
    st.table(pd.DataFrame(main, index=names).T)
    st.caption(f"资产均为今日购买力。折算系数 {plan.deflator:.3f}（通胀 "
               f"{C.pct(plan.assumptions['inflation'][0])}{C.default_tag(plan.assumptions['inflation'][1])}，"
               f"距停止工作 {plan.years_to_retire:.1f} 年）。余量占目标 = 余量 ÷ 目标，"
               "表示资产超出（或不足）目标的幅度。")

    with st.expander("查看准确金额"):
        rows = {k: [] for k in ("退休资产（名义）", "退休资产（今日购买力）", "两阶段目标",
                                "余量（+）/ 缺口（−）", "过渡期所需资金",
                                "退休时流动资产（今日购买力）", "能否覆盖过渡期")}
        for s in plan.scenarios:
            if not s.get("available"):
                for k in rows:
                    rows[k].append("—")
                continue
            rows["退休资产（名义）"].append(C.yuan(s["nominal"]))
            rows["退休资产（今日购买力）"].append(C.yuan(s["real"]))
            rows["两阶段目标"].append(C.yuan(s["target"]))
            rows["余量（+）/ 缺口（−）"].append(C.yuan(s["margin"], True))
            rows["过渡期所需资金"].append(C.yuan(plan.target["bridge_cost"]))
            rows["退休时流动资产（今日购买力）"].append(C.yuan(s["liquid_real"]))
            rows["能否覆盖过渡期"].append(
                "无过渡期" if s["liquid_ok"] is None
                else ("覆盖" if s["liquid_ok"] else f"不足，差 {C.yuan(s['liquid_short'])}"))
        st.dataframe(pd.DataFrame(rows, index=names).T, use_container_width=True)
    if not ok:
        st.warning("没有可比较的情景。")


def _notes(plan):
    for s in plan.scenarios:
        if s.get("available") and s["uncovered"]:
            st.error(f"「{s['name']}」：存款耗尽、基金股票也全部变现后，从 {str(s['uncovered_from'])[:7]} 起"
                     f"仍有 {C.yuan(s['uncovered'])} 的赤字无法覆盖，已作为负现金计入退休资产。")
    for s in plan.scenarios:
        if not s.get("available") or s["cash_depl"] is None:
            continue
        months = f"约可支撑 {s['liq_months']} 个月" if s["liq_months"] is not None else ""
        st.warning(f"「{s['name']}」：存款会在 {str(s['cash_depl'])[:7]} 先用完，之后需要从基金、股票变现支付生活费。"
                   f"当前可动用资产 {C.yuan(s['liq_now'])}，零收入{months}。")


def _paths(plan):
    p = plan.paths
    if "extra_mo" not in p:
        return
    st.subheader("补足缺口的路径")
    st.caption("针对「继续工作」情景的缺口，两条路径相互独立；估算较粗，只用来感知量级。")
    a, b = st.columns(2)
    with a:
        if p["extra_feasible"]:
            st.metric("每月额外储蓄", C.yuan(p["extra_mo"]) + "/月")
            st.caption(f"从现在起每月多存这么多，并按退休前投资年化增值，到 {plan.date_retire.year} 年补足缺口。")
        else:
            st.metric("每月额外储蓄", "超出月收入")
            st.caption(f"需要每月多存 {C.yuan(p['extra_mo'])}，超过月收入，"
                       f"{p['months_left']} 个月内不可行。")
    with b:
        if p.get("delay_years") is not None:
            st.metric("推迟停止工作", f"约 {p['delay_years']:.1f} 年")
            st.caption(f"按现有月储蓄 {C.yuan(p['saving_mo'])} 和投资增长估算，线性近似。")
        else:
            st.metric("推迟停止工作", "不适用")
            st.caption("月支出不低于月收入，或缺口过大，推迟停止工作单独无法补足。")
    if "semi_required" in p:
        if p["semi_feasible"]:
            st.info(f"半退休情景要补足缺口，半退休月收入需要提高到约 {C.yuan(p['semi_required'])}。")
        else:
            st.warning(f"半退休情景要补足缺口，半退休月收入需要约 {C.yuan(p['semi_required'])}，"
                       "已超过现有月收入的 1.5 倍，可操作性有限。")


def _stress(plan):
    st.subheader("压力测试")
    st.caption("以「继续工作」为基准，逐项施加冲击，用同一个两阶段目标比较。"
               "只模拟到计划停止工作日，退休后的收益和通胀变化没有模拟，属于局部压力测试。")
    df = pd.DataFrame([{
        "冲击": s["label"],
        "退休资产": C.wan(s["real"]),
        "余量（+）/ 缺口（−）": C.wan(s["margin"], True),
        "过渡期流动资产": _cover(s),
    } for s in plan.stress]).set_index("冲击")
    st.table(df)
    st.markdown("**每项冲击改变了什么**")
    for s in plan.stress[1:]:
        flag = ":orange[局部] " if s["partial"] else ""
        st.markdown(f"- **{s['label']}**：{flag}{s['note'].removeprefix('局部：')}")
    st.caption("养老金冲击会改变养老期缺口，对应目标已重算；资产均为今日购买力。")


def _reference(plan):
    with st.expander("方法对照：未扣养老金的 4% 参考值"):
        st.write("传统做法是 退休月支出 × 12 ÷ 4%，既不扣养老金，也不单列过渡期。"
                 f"按你的退休月支出，参考值为 **{C.yuan(plan.ref4)}**。")
        st.caption("它只作对照，不再叫「退休缺口」。上面的比较用的是两阶段目标。")
        ref = pd.DataFrame([{
            "情景": s["name"], "退休资产（今日购买力）": C.yuan(s["real"]),
            "参考值": C.yuan(plan.ref4), "资产 − 参考值": C.yuan(s["ref4_diff"], True),
        } for s in plan.scenarios if s.get("available")])
        st.dataframe(ref, hide_index=True, use_container_width=True)
        st.markdown("**局部指标：可投资资产 ÷ 养老期补充目标**（旧版压力测试的「覆盖倍数」，不含过渡期）")
        old = pd.DataFrame([{
            "冲击": s["label"], "可投资资产（今日购买力）": C.yuan(s["liquid_real"]),
            "养老期补充目标": C.yuan(s["old_target"]),
            "倍数": "无需补充" if s["old_coverage"] == float("inf") else f"{s['old_coverage']:.1f}x",
        } for s in plan.stress])
        st.dataframe(old, hide_index=True, use_container_width=True)
        st.caption("这个倍数只比较可投资资产和养老期缺口，没有计入过渡期消耗，不能当作完整的退休结论。")
