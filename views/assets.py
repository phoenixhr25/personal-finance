"""资产：你现在有什么、分在哪一层、市值和 NPV 各是多少。

这一页保留资产整合表的原有价值，不依赖退休测算是否填完。
"""
import pandas as pd
import streamlit as st

import state
from views import charts
from views import common as C

LAYER_ORDER = ["① 社会保障层", "② 保险保障层", "③ 投资层", "④ 现金等价物层"]


def render(nav):
    st.title("资产")
    plan = state.plan()
    C.source_banner()
    if C.plan_error(plan):
        return
    if not state.has_data():
        st.info("还没有数据。请先到「概览」载入示例，或到「数据与假设」填写。")
        if nav is not None:
            st.page_link(nav.overview, label="回到概览")
        return
    if not plan.assets_ready:
        miss = [i for i in plan.missing if i.stage == "assets"]
        st.subheader("资产信息还没填完")
        st.write("下面这些项补全后，才能汇总资产：")
        C.issue_lines(miss)
        if nav is not None:
            st.page_link(nav.data, label="去「数据与假设」补全")
        return

    # 1. 总览
    c1, c2, c3 = st.columns(3)
    c1.metric("当前总资产", C.wan(plan.total_mv), help=C.yuan(plan.total_mv))
    c2.metric("可投资资产", C.wan(plan.investable_now),
              help=f"基金 + 股票 + 存款 {C.yuan(plan.investable_now)}")
    c3.metric("浮盈", C.wan(plan.total_mv - plan.total_cost, signed=True),
              help=f"市值 − 成本 = {C.yuan(plan.total_mv - plan.total_cost, signed=True)}")
    st.caption("总资产含养老保险个人账户、公积金和保险现金价值，其中不少不能随时取出；"
               f"可投资资产只算基金、股票和存款。加权年化 {plan.w_return:.2%}，含历史浮盈，只用于诊断，不能预测未来。")
    if plan.price_failed:
        st.warning(f"{len(plan.price_failed)} 个持仓没有取到行情（{', '.join(plan.price_failed)}），"
                   "已按成本价计算，对应的年化收益显示为 0。")

    # 2. 四层结构
    st.subheader("四层资产结构")
    st.caption("按流动性从低到高排列：越靠前越难变现。")
    fig = charts.donut({k: plan.layer_mv.get(k, 0.0) for k in LAYER_ORDER if k in plan.layer_mv})
    if fig is None:
        st.info("资产合计为 0，无法绘制结构图。")
    else:
        st.pyplot(fig, use_container_width=False)
        charts.plt.close(fig)
    share = pd.DataFrame([{
        "层级": k, "市值": C.yuan(v),
        "占比": C.pct(v / plan.total_mv) if plan.total_mv else "—",
    } for k, v in plan.layer_mv.items()])
    st.dataframe(share, hide_index=True, use_container_width=True)

    # 3. 各层明细
    st.subheader("各层明细")
    df = pd.DataFrame(plan.rows)
    for layer in LAYER_ORDER:
        sub = df[df["layer"] == layer] if len(df) else df
        if not len(sub):
            continue
        mv, cost, npv = sub["market_value"].sum(), sub["cost_basis"].sum(), sub["npv"].sum()
        wav = float((sub["cost_basis"] / cost * sub["annual_return"]).sum()) if cost else 0.0
        st.markdown(f"**{layer}**")
        shown = pd.DataFrame({
            "资产": sub["category"],
            "市值": sub["market_value"].map(C.yuan),
            "成本": sub["cost_basis"].map(C.yuan),
            "浮盈": (sub["market_value"] - sub["cost_basis"]).map(lambda x: C.yuan(x, True)),
            "年化": sub["annual_return"].map(lambda x: f"{x:.1%}"),
            "NPV": sub["npv"].map(C.yuan),
        })
        st.dataframe(shown, hide_index=True, use_container_width=True)
        st.caption(f"小计：市值 {C.yuan(mv)} · 成本 {C.yuan(cost)} · 浮盈 {C.yuan(mv - cost, True)} · "
                   f"加权年化 {wav:.1%} · NPV {C.yuan(npv)}")
    st.caption("年化收益率按持有期计算，持有不足一个月的显示总收益率；"
               "加权年化只用于诊断结构，不能用来预测未来。")

    # 4. 市值与 NPV
    st.subheader("当前市值和 NPV 的区别")
    st.markdown(
        "- **市值**：今天账户里显示的金额。\n"
        "- **NPV（净现值）**：把未来才会拿到的钱，按折现率折成今天的价值，"
        "用来把不同资产放在同一把尺子下比较。\n"
        "- **NPV 不是可提取的资金。** 例如养老金的现值来自未来几十年的月领，现在取不出来。")
    pen = plan.pension
    diff = pd.DataFrame([
        {"项目": "全部资产", "市值": C.yuan(plan.total_mv), "NPV": C.yuan(plan.total_npv),
         "差额": C.yuan(plan.total_npv - plan.total_mv, True)},
        {"项目": "其中：养老保险", "市值": C.yuan(pen["personal_account"]),
         "NPV": C.yuan(pen["npv"]) if plan.npv_complete else "待补充",
         "差额": C.yuan(pen["npv"] - pen["personal_account"], True) if plan.npv_complete else "—"},
    ])
    st.dataframe(diff, hide_index=True, use_container_width=True)
    if not plan.npv_complete:
        st.warning("养老金的 NPV 还缺开始领取日期或月领金额，上面的 NPV 合计不含这一项。")
    d_rate, d_def = plan.assumptions["discount_rate"]
    st.caption(f"折现率 {C.pct(d_rate)}{C.default_tag(d_def)}。"
               f"等值月均 {C.yuan(plan.eaa_month)}：把 NPV 平摊到每个月相当于的现金流，"
               "只用于比较，不是每月可以支取的金额。")

    # 5. 历史快照与退休推算
    st.subheader("历史快照与退休推算")
    labels, values = [], []
    b1, b2 = plan.base_dates
    if plan.snap_b1:
        labels.append(str(b1)); values.append(sum(plan.snap_b1.values()))
    if plan.snap_b2:
        labels.append(str(b2)); values.append(sum(plan.snap_b2.values()))
    labels.append("当前"); values.append(sum(plan.snap_now.values()))
    if plan.snap_ret:
        labels.append(f"{plan.date_retire.year} 年推算"); values.append(sum(plan.snap_ret.values()))
    fig2 = charts.bars(labels, values)
    st.pyplot(fig2, use_container_width=False)
    charts.plt.close(fig2)
    if not (plan.snap_b1 and plan.snap_b2):
        st.caption("没有填写历史快照时只显示当前和退休推算。历史快照在「数据与假设」的高级设置里，"
                   "不影响退休测算。")
    if plan.snap_ret:
        total_ret = sum(plan.snap_ret.values())
        r1, r2 = st.columns(2)
        r1.metric(f"{plan.date_retire.year} 年推算总资产（名义）", C.wan(total_ret),
                  help=C.yuan(total_ret))
        r2.metric("折合今日购买力", C.wan(total_ret / plan.deflator),
                  help=f"按通胀 {C.pct(plan.assumptions['inflation'][0])}，折算系数 {plan.deflator:.3f}")
        st.caption("退休推算是「停止工作后纯靠现有资产增值」的机械推算，不含未来工资转入。各层按各自的利率增长："
                   "个人账户按记账利率，公积金按 2.5%，储蓄险按保单 IRR，投资按退休前投资年化，存款按各笔利率加权。"
                   "这里是名义金额，与目标比较请看「概览」和「情景」。")
    else:
        st.caption("填写计划停止工作日期后，这里显示退休推算。")

    _diagnosis(plan)


# ── 结构检查（原「投资建议」）────────────────────────────────────────────
def _diagnosis(plan):
    with st.expander("持仓结构检查"):
        st.caption("几条结构检查规则和目标配置对比，用来发现占比失衡，不是投资建议。")
        s = plan.snap_now
        layers = {"社保层": s["pension_hpf"], "保险层": s["insurance"],
                  "投资层": s["investment"], "现金层": s["cash"]}
        total = sum(layers.values())
        pcts = {k: (v / total if total else 0.0) for k, v in layers.items()}
        diags = []
        if pcts["投资层"] < 0.20:
            diags.append(("warning", f"投资层占 {pcts['投资层']:.1%}，低于 20%"))
        if pcts["现金层"] > 0.30:
            diags.append(("warning", f"现金层占 {pcts['现金层']:.1%}，高于 30%"))
        held = plan.fund_list + plan.stock_list
        if layers["投资层"] > 0 and held:
            top = max(held, key=lambda x: x["market_value"])
            share = top["market_value"] / layers["投资层"]
            if share > 0.50:
                diags.append(("warning", f"{top.get('name', top.get('code', ''))} 占投资层 {share:.1%}，高于 50%"))
        illiquid = (layers["社保层"] + layers["保险层"]) / total if total else 0.0
        if illiquid > 0.60:
            diags.append(("warning", f"社保 + 保险占总资产 {illiquid:.1%}，高于 60%，短期可用资金有限"))
        if diags:
            for _, msg in diags:
                st.warning(msg)
        else:
            st.write(":green[四条结构规则均未触发。]")

        targets = [state.get("sim", k) for k in ("target_ph", "target_ins", "target_inv", "target_csh")]
        if any(t is None for t in targets):
            st.caption("未设置目标资产配置。可在「数据与假设」的高级设置里填写，用来对比当前占比。")
            return
        rows = []
        for (name, val), tgt in zip(layers.items(), targets):
            cur, tg = pcts[name], tgt / 100
            rows.append({"层级": name, "当前": f"{cur:.1%}", "目标": f"{tg:.1%}",
                         "偏差": f"{cur - tg:+.1%}",
                         "调仓金额（正=增配）": C.yuan((tg - cur) * total, True)})
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        if abs(sum(targets) - 100) > 1:
            st.warning(f"目标配置合计 {sum(targets)}%，请调整到 100%。")
