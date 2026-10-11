"""各页共用的样式、金额格式和提示块。"""
import streamlit as st

import state

NAVY, TEAL, AMBER, MUTED = "#1F3A5F", "#2A8C8C", "#C58A2B", "#6B778C"
PRIVACY_URL = "https://github.com/phoenixhr25/personal-finance/blob/main/PRIVACY.md"

CSS = f"""
<style>
h1, h2, h3, h4 {{ color: {NAVY}; letter-spacing: 0; }}
h1 {{ font-size: 1.9rem; }}
[data-testid="stMetricValue"] {{ color: {NAVY}; }}
[data-testid="stMetricLabel"] p {{ color: {MUTED}; }}
.block-container {{ padding-top: 2.2rem; max-width: 1100px; }}
.pf-lead {{ font-size: 1.02rem; color: #26323F; margin: .2rem 0 .6rem; }}
.pf-tag {{ display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: .78rem;
          background: #FFF4DC; color: {AMBER}; margin-left: 6px; vertical-align: middle; }}
.pf-tag-demo {{ background: #FFF4DC; color: {AMBER}; }}
.pf-tag-ok {{ background: #E3F3F3; color: {TEAL}; }}
@media (max-width: 640px) {{
  .block-container {{ padding-left: 1rem; padding-right: 1rem; }}
  h1 {{ font-size: 1.5rem; }}
}}
</style>
"""


def inject_css():
    st.markdown(CSS, unsafe_allow_html=True)


# ── 金额与比例：正文用万元，明细保留准确金额 ──────────────────────────────────
def yuan(x, signed=False):
    if x is None:
        return "—"
    s = f"{abs(x):,.0f}"
    if x < 0:
        return f"−¥{s}"
    return f"+¥{s}" if signed and x > 0 else f"¥{s}"


def wan(x, signed=False):
    if x is None:
        return "—"
    if abs(x) < 10000:
        return yuan(x, signed)
    s = f"{abs(x) / 10000:,.1f} 万"
    if x < 0:
        return f"−¥{s}"
    return f"+¥{s}" if signed and x > 0 else f"¥{s}"


def pct(x, digits=1, signed=False):
    if x is None:
        return "—"
    return f"{x:+.{digits}%}" if signed else f"{x:.{digits}%}"


def ym(d):
    return f"{d.year} 年 {d.month} 月" if d else "—"


def default_tag(is_default):
    return "（默认）" if is_default else ""


# ── 通用提示块 ────────────────────────────────────────────────────────────
def render_notice():
    msg = st.session_state.pop(state.NOTICE, None)
    if msg:
        st.success(msg)


def render_import_status():
    """导入校验结果和待确认提示，所有页面顶部都会显示，避免用户错过。"""
    errs = st.session_state.get(state.ERRORS)
    if errs:
        st.error("配置未导入，当前数据保持不变：\n\n" + "\n".join(f"- {p}" for p in errs[:8]))
    pend = state.pending()
    if pend:
        _, warns = pend
        with st.container(border=True):
            st.markdown("**配置文件校验通过。** 确认后将覆盖当前全部数据，建议先导出当前配置。")
            for w in warns:
                st.caption(f"· {w}")
            c1, c2 = st.columns(2)
            c1.button("确认覆盖", key="import_confirm", type="primary",
                      use_container_width=True, on_click=state.confirm_import)
            c2.button("取消", key="import_cancel", use_container_width=True,
                      on_click=state.cancel_import)


def source_banner():
    if state.is_demo():
        st.info("**当前显示的是虚构示例**，人物和数字都是虚构的，用来演示工具。"
                "要看自己的测算，请到「数据与假设」填写，或导入自己的配置。")


def issue_lines(issues):
    """缺失项列表：写明是哪一项、缺什么。"""
    for i in issues:
        tail = "" if i.message == "未填写" else f"：{i.message}"
        st.markdown(f"- {i.label}{tail}")


def plan_error(plan):
    """测算出现意外异常时给出说明；返回 True 表示调用方应停止渲染结果。"""
    if not plan.error:
        return False
    st.error("测算过程中遇到意外错误，没有给出任何数字。请检查最近修改的输入，"
             "或在「数据与假设」里重新填写相关项。\n\n"
             f"技术信息：{plan.error}")
    return True
