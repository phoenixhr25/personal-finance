"""页面外壳：导航、侧边栏（来源、假设摘要、导入导出）。入口 app.py 只调用 main()。"""
from types import SimpleNamespace

import streamlit as st

import state
from views import assets, common, data, overview, scenarios


def _sidebar(plan):
    with st.sidebar:
        st.markdown("**当前数据来源**")
        label = state.SOURCE_LABELS[state.source()]
        tone = "pf-tag-demo" if state.is_demo() else ""
        st.markdown(f'<span class="pf-tag {tone}" style="margin-left:0">{label}</span>',
                    unsafe_allow_html=True)
        if state.has_data() and plan.assumptions:
            n = len(plan.missing)
            st.caption("必填项已完整" if n == 0 else f"必填项还缺 {n} 项")

            A = plan.assumptions
            st.markdown("**关键假设**")
            tag = common.default_tag
            lines = [
                f"通胀 {common.pct(A['inflation'][0])}{tag(A['inflation'][1])}",
                f"投资年化 {common.pct(A['proj_invest_rate'][0])}{tag(A['proj_invest_rate'][1])}",
                f"折现率 {common.pct(A['discount_rate'][0])}{tag(A['discount_rate'][1])}",
                "养老金：" + ("手动填写" if plan.pension_mode == "manual" else "按城职保公式推算"),
            ]
            st.caption(" · ".join(lines))

        with st.expander("导入 / 导出配置"):
            st.file_uploader("导入 JSON 配置", type=["json"], key="up_side",
                             label_visibility="collapsed")
            st.download_button("导出配置", data=state.export_json(), file_name="finance_config.json",
                               mime="application/json", use_container_width=True,
                               disabled=not state.has_data())
            st.caption("配置文件是明文，含余额和出生年月，请勿公开分享。")
        st.caption(f"[隐私说明]({common.PRIVACY_URL})")


def main(default="overview"):
    st.set_page_config(page_title="个人资产收益整合表", layout="wide")
    state.init()
    common.inject_css()

    nav = SimpleNamespace()
    keys = {"overview": ("概览", lambda: overview.render(nav)),
            "assets": ("资产", lambda: assets.render(nav)),
            "scenarios": ("情景", lambda: scenarios.render(nav)),
            "data": ("数据与假设", lambda: data.render(nav))}
    pages = []
    for key, (title, fn) in keys.items():
        page = st.Page(fn, title=title, url_path=key,
                       default=(key == default))
        setattr(nav, key, page)
        pages.append(page)
    current = st.navigation(pages)
    if st.session_state.pop(state.GOTO, None) == "data":
        st.switch_page(nav.data)

    state.process_uploads()          # 先处理上传，再渲染待确认 / 错误提示
    _sidebar(state.plan())
    common.render_notice()
    common.render_import_status()
    current.run()
