"""输入控件：控件只是编辑器，值通过回调写回 state 里的规范配置。

- 值为 None 表示"未填写"（输入框留空），填 0 就是明确的 0。
- 控件 key 以 "w:" 开头；规范配置变化（导入、示例、清空）后控件状态会被清掉并重新取值。
- 控件的 value 参数恒为 None / 默认，由 session_state 提供初值，避免控件身份随数值变化。
"""
from datetime import date

import streamlit as st

import holdings as H
import state
from config_io import bounds

DATE_MIN, DATE_MAX = date(1940, 1, 1), date(2100, 12, 31)
RATE_HELP = "填小数：3% 填 0.03"


def _key(path):
    return state.WIDGET_PREFIX + ".".join(str(p) for p in path)


def _bounds(path):
    section, name = (path[0], path[-1])
    try:
        return bounds(section, name)
    except KeyError:
        return None, None


def _flag(path, required, default_hint):
    """未填写时在控件下方提示：必填项标橙色，假设项说明默认值。"""
    if state.get(*path) is not None:
        return
    if required:
        st.caption(":orange[未填写（必填）]")
    elif default_hint:
        st.caption(f"留空时使用默认值 {default_hint}")


# ── 数字 ─────────────────────────────────────────────────────────────────
def _commit_number(path, key, kind):
    v = st.session_state.get(key)
    state.set_value(path, None if v is None else (int(v) if kind == "int" else float(v)))


def number(path, label, *, kind="float", step=None, fmt=None, help=None,
           required=False, default_hint=None, lo=None, hi=None):
    key = _key(path)
    cur = state.get(*path)
    if key not in st.session_state and cur is not None:
        st.session_state[key] = int(cur) if kind == "int" else float(cur)
    b_lo, b_hi = _bounds(path)
    lo = b_lo if lo is None else lo
    hi = b_hi if hi is None else hi
    kw = {}
    if kind == "int":
        kw["step"] = int(step or 1)
        lo, hi = (None if lo is None else int(lo)), (None if hi is None else int(hi))
    else:
        kw["step"] = float(step) if step else None
        lo, hi = (None if lo is None else float(lo)), (None if hi is None else float(hi))
        if fmt:
            kw["format"] = fmt
    st.number_input(label, value=None, min_value=lo, max_value=hi, key=key, help=help,
                    on_change=_commit_number, args=(path, key, kind), **kw)
    _flag(path, required, default_hint)


# ── 日期 ─────────────────────────────────────────────────────────────────
def _commit_date(path, key):
    v = st.session_state.get(key)
    state.set_value(path, v.isoformat() if v else None)


def date_field(path, label, *, help=None, required=False, default_hint=None,
               disabled=False, lo=DATE_MIN, hi=DATE_MAX):
    key = _key(path)
    cur = state.get(*path)
    if key not in st.session_state and cur:
        try:
            st.session_state[key] = date.fromisoformat(cur)
        except ValueError:
            pass
    st.date_input(label, value=None, min_value=lo, max_value=hi, key=key, help=help,
                  format="YYYY-MM-DD", disabled=disabled,
                  on_change=_commit_date, args=(path, key))
    if not disabled:
        _flag(path, required, default_hint)


# ── 选择 / 开关 ──────────────────────────────────────────────────────────
def _commit_plain(path, key):
    state.set_value(path, st.session_state.get(key))


def select(path, label, options, *, help=None, required=False):
    key = _key(path)
    cur = state.get(*path)
    if key not in st.session_state and cur in options:
        st.session_state[key] = cur
    st.selectbox(label, options, index=None, key=key, help=help, placeholder="请选择",
                 on_change=_commit_plain, args=(path, key))
    _flag(path, required, None)


def toggle(path, label, *, default=True, help=None):
    key = _key(path)
    cur = state.get(*path)
    if key not in st.session_state:
        st.session_state[key] = default if cur is None else bool(cur)
    st.toggle(label, key=key, help=help, on_change=_commit_plain, args=(path, key))


# ── 持仓文本：留空 = 未填写；勾选「暂无」= 明确没有这类资产 ───────────────────
def _commit_text(path, key, none_key):
    txt = st.session_state.get(key, "")
    state.set_value(path, txt if txt.strip() else None)
    st.session_state[none_key] = False


def _commit_none(path, key, none_key):
    if st.session_state.get(none_key):
        st.session_state[key] = ""
        state.set_value(path, "")
    else:
        state.set_value(path, None)


def holdings(path, label, *, example, height=110, help=None):
    key = _key(path)
    none_key = key + ":none"
    cur = state.get(*path)
    if key not in st.session_state:
        st.session_state[key] = cur or ""
    if none_key not in st.session_state:
        st.session_state[none_key] = (state.cfg().get(path[0]) == "")
    st.text_area(label, key=key, height=height, help=help, placeholder=example,
                 on_change=_commit_text, args=(path, key, none_key))
    st.checkbox("暂无此类资产", key=none_key, on_change=_commit_none, args=(path, key, none_key))


# ── 单行文本（保单名称等，可选）──────────────────────────────────────────────
def text_line(path, label, *, placeholder=None):
    key = _key(path)
    cur = state.get(*path)
    if key not in st.session_state and cur is not None:
        st.session_state[key] = cur
    st.text_input(label, key=key, placeholder=placeholder,
                  on_change=_commit_line, args=(path, key))


def _commit_line(path, key):
    v = st.session_state.get(key, "")
    state.set_value(path, v.strip() or None)


# ── 保单数量：改变数量时调整保单列表，已填写的保单保留 ───────────────────────
def _commit_ins_count(key):
    n = st.session_state.get(key)
    if n is None:
        state.set_value(("insurance",), None)
        return
    cur = state.cfg().get("insurance") or []
    state.set_value(("insurance",), [cur[i] if i < len(cur) else {} for i in range(int(n))])


def insurance_count(label, *, help=None):
    key = _key(("insurance",))
    cur = state.cfg().get("insurance")
    if key not in st.session_state and cur is not None:
        st.session_state[key] = len(cur)
    st.number_input(label, value=None, min_value=0, max_value=5, step=1, key=key, help=help,
                    on_change=_commit_ins_count, args=(key,))
    if cur is None:
        st.caption(":orange[未填写（必填）；没有储蓄险请填 0]")


# ── 持仓表格：配置里仍是文本，表格是它的另一种视图 ──────────────────────────
def drop_holding_widget_state():
    """切换录入方式或清空时，让两种视图都从配置重新取值。"""
    for p in (("funds_dca",), ("stocks",), ("deposits",)):
        base = _key(p)
        for k in (base, base + ":tbl", base + ":base", base + ":none"):
            st.session_state.pop(k, None)


def _commit_none_table(path):
    key = _key(path)
    if st.session_state.get(key + ":none"):
        state.set_value(path, "")
    else:
        state.set_value(path, None)
    st.session_state.pop(key + ":tbl", None)       # 表格重新取值
    st.session_state.pop(key + ":base", None)


def _column_config(kind):
    cfg = {}
    for key, title, typ, _ in H.SPECS[kind]:
        if typ == "number":
            cfg[title] = st.column_config.NumberColumn(title, min_value=0.0)
        elif typ == "date":
            cfg[title] = st.column_config.DateColumn(title, format="YYYY-MM-DD")
        else:
            cfg[title] = st.column_config.TextColumn(title)
    return cfg


def holdings_table(path, kind):
    key = _key(path)
    tbl_key, base_key, none_key = key + ":tbl", key + ":base", key + ":none"
    cur = state.get(*path)
    if base_key not in st.session_state:
        rows, _ = H.rows_from_text(kind, cur or "")
        st.session_state[base_key] = H.df_from_rows(kind, rows)
    edited = st.data_editor(st.session_state[base_key], key=tbl_key, num_rows="dynamic",
                            hide_index=True, use_container_width=True,
                            column_config=_column_config(kind))
    new_text, incomplete, changed, bad = H.sync(kind, cur, edited)
    if changed:
        state.set_value(path, new_text)
        st.session_state[none_key] = False
        st.rerun()
    if incomplete:
        st.caption(f":orange[有 {incomplete} 行没填完，补全后才会计入。]")
    if bad:
        st.warning("有 " + str(len(bad)) + " 行文本无法识别，已保留但不计入，可在「粘贴文本」方式里修改：\n\n"
                   + "\n".join(f"- `{b}`" for b in bad[:5]))
    if none_key not in st.session_state:
        st.session_state[none_key] = (state.cfg().get(path[0]) == "")
    st.checkbox("暂无此类资产", key=none_key, on_change=_commit_none_table, args=(path,))
