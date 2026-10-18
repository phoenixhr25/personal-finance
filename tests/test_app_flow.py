"""页面状态流：无界面运行整个应用（含 st.navigation），验证状态、导入导出和页面一致性。

文件上传控件 AppTest 不支持，导入走 state.handle_upload 的同一条代码路径单独测。
"""
import copy
import json
import os
from datetime import date

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

import calc  # noqa: E402
from config_io import validate_config, wrap_export  # noqa: E402
from views import common as C  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGES = ("overview", "assets", "scenarios", "data")


def demo_cfg():
    clean, _ = validate_config(json.load(open(os.path.join(ROOT, "examples", "demo_config.json"),
                                              encoding="utf-8")))
    return calc.cfg_from_clean(clean)


def run_page(page="overview", cfg=None, source=None, extra=None):
    at = AppTest.from_string(f"import shell; shell.main(default={page!r})", default_timeout=180)
    if cfg is not None:
        at.session_state["cfg"] = cfg
        at.session_state["cfg_source"] = source or "import"
    for k, v in (extra or {}).items():
        at.session_state[k] = v
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def open_group(at, name):
    """数据页一次显示一组输入：先选组再找控件。"""
    at.radio(key="w:data_group").set_value(name).run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def texts(at):
    parts = [m.value for m in at.markdown] + [i.value for i in at.info]
    parts += [h.value for h in at.subheader] + [w.value for w in at.warning]
    parts += [c.value for c in at.caption]
    return " ".join(parts)


def metric(at, label):
    return next(m.value for m in at.metric if m.label == label)


# ── 首次打开 ─────────────────────────────────────────────────────────────
def test_first_open_offers_three_ways_and_no_conclusion():
    at = run_page("overview")
    assert at.button(key="start_demo")
    assert "填写我的数据" in texts(at) and "导入配置" in texts(at)
    assert "按当前假设" not in texts(at)
    assert not at.metric                       # 没有任何数字结论


def test_demo_button_loads_marked_example():
    at = run_page("overview")
    at.button(key="start_demo").click().run()
    assert not at.exception
    assert at.session_state["cfg_source"] == "demo"
    assert any("虚构示例" in i.value for i in at.info)
    assert "按当前假设" in texts(at)


@pytest.mark.parametrize("page", PAGES)
def test_demo_marked_on_every_page(page):
    at = run_page(page, demo_cfg(), "demo")
    assert any("虚构示例" in i.value for i in at.info)
    assert "虚构示例" in " ".join(m.value for m in at.sidebar.markdown)


@pytest.mark.parametrize("page", PAGES)
@pytest.mark.parametrize("cfg_kind", ["empty", "partial", "full"])
def test_every_page_renders_in_every_state(page, cfg_kind):
    cfg = {"empty": calc.empty_cfg(),
           "partial": {**calc.empty_cfg(), "global": {"date_retire": "2037-01-01"}},
           "full": demo_cfg()}[cfg_kind]
    source = "none" if cfg_kind == "empty" else "manual"
    run_page(page, cfg, source)


def test_missing_inputs_are_listed_not_defaulted():
    cfg = {**calc.empty_cfg(), "global": {"date_retire": "2037-01-01"}}
    at = run_page("overview", cfg, "manual")
    body = texts(at)
    assert "还差几项信息" in body and "个人账户余额" in body
    assert "按当前假设" not in body and not at.metric


# ── 编辑与跨页一致 ───────────────────────────────────────────────────────
def test_edit_writes_back_and_other_pages_agree():
    at = run_page("data", demo_cfg(), "import")
    n = next(n for n in at.number_input if n.label.startswith("退休后每月支出"))
    n.set_value(12000.0).run()
    assert not at.exception
    cfg = at.session_state["cfg"]
    assert cfg["sim"]["retire_expense_mo"] == 12000.0
    assert at.session_state["cfg_source"] == "import_edited"

    plan = calc.compute_plan(cfg)
    ov = run_page("overview", cfg, "import_edited")
    assert metric(ov, "两阶段目标") == C.wan(plan.target["total"])
    sc = run_page("scenarios", cfg, "import_edited")
    table = sc.dataframe[0].value
    assert table.loc["两阶段目标"].tolist() == [C.yuan(plan.target["total"])] * 3


def test_overview_and_scenarios_share_one_target_in_demo():
    plan = calc.compute_plan(demo_cfg())
    ov = run_page("overview", demo_cfg(), "demo")
    sc = run_page("scenarios", demo_cfg(), "demo")
    assert metric(ov, "两阶段目标") == C.wan(plan.target["total"])
    assert sc.dataframe[0].value.loc["两阶段目标"].iloc[0] == C.yuan(plan.target["total"])
    assert sc.dataframe[0].value.loc["余量（+）/ 缺口（−）"].iloc[0] == C.yuan(plan.headline["margin"], True)


DROP_HARNESS = """
import streamlit as st, shell
if st.session_state.pop("_drop", False):
    for k in [k for k in st.session_state if str(k).startswith("w:")]:
        del st.session_state[k]
shell.main(default="data")
"""


def test_widget_state_dropped_then_restored_from_config():
    """切到别的页面时控件状态会被丢弃；回来后应从规范配置重新取值。"""
    cfg = demo_cfg()
    cfg["sim"]["retire_expense_mo"] = 13579.0
    at = AppTest.from_string(DROP_HARNESS, default_timeout=180)
    at.session_state["cfg"], at.session_state["cfg_source"] = cfg, "import"
    at.run()
    n = next(n for n in at.number_input if n.label.startswith("退休后每月支出"))
    n.set_value(24680.0).run()                        # 用户在页面上改了一个值
    assert at.session_state["cfg"]["sim"]["retire_expense_mo"] == 24680.0
    at.session_state["_drop"] = True                  # 模拟切到别的页面：控件状态被丢弃
    at.run()
    assert not at.exception
    n = next(n for n in at.number_input if n.label.startswith("退休后每月支出"))
    assert n.value == 24680.0                         # 从规范配置恢复，不是回到旧值或默认值


def test_unfilled_stays_unfilled_and_zero_is_zero():
    at = open_group(run_page("data", demo_cfg(), "import"), "收支与未来假设")
    n = next(n for n in at.number_input if n.label.startswith("每月总支出"))
    n.set_value(None).run()
    assert at.session_state["cfg"]["sim"]["monthly_expense"] is None
    n = next(n for n in at.number_input if n.label.startswith("每月总支出"))
    n.set_value(0.0).run()
    assert at.session_state["cfg"]["sim"]["monthly_expense"] == 0.0


def test_none_declared_checkbox_marks_holding_as_empty():
    cfg = demo_cfg()
    cfg["funds_dca"] = None
    at = open_group(run_page("data", cfg, "import"), "基金、股票、存款")
    assert any("定投基金" in i.label for i in calc.compute_plan(cfg).missing)
    box = [c for c in at.checkbox if c.key.startswith("w:funds_dca")][0]
    box.check().run()
    assert at.session_state["cfg"]["funds_dca"] == ""
    assert not any(i.path == ("funds_dca",) for i in calc.compute_plan(at.session_state["cfg"]).missing)


def test_insurance_count_resizes_and_keeps_filled_policy():
    at = open_group(run_page("data", demo_cfg(), "import"), "养老金、公积金、保险")
    first = copy.deepcopy(at.session_state["cfg"]["insurance"][0])
    cnt = next(n for n in at.number_input if n.label == "保单数量")
    cnt.set_value(2).run()
    ins = at.session_state["cfg"]["insurance"]
    assert len(ins) == 2 and ins[0] == first and ins[1] == {}
    assert any("保单 2" in i.label for i in calc.compute_plan(at.session_state["cfg"]).missing)
    cnt = next(n for n in at.number_input if n.label == "保单数量")
    cnt.set_value(0).run()
    assert at.session_state["cfg"]["insurance"] == []


GROUPS = list(calc.GROUPS)


@pytest.mark.parametrize("group", GROUPS)
def test_every_number_input_has_bounds(group):
    at = open_group(run_page("data", demo_cfg(), "import"), group)
    assert [n.label for n in at.number_input if n.min is None or n.max is None] == []


@pytest.mark.parametrize("pick", ["min", "max"])
def test_extreme_legal_values_do_not_crash_any_page(pick):
    at = run_page("data", demo_cfg(), "import")
    for group in GROUPS:
        open_group(at, group)
        for _ in range(2):      # 保单数量变化后会出现新的输入框
            for n in at.number_input:
                n.set_value(n.min if pick == "min" else n.max)
            at.run()
            assert not at.exception, [e.value.splitlines()[0] for e in at.exception]
    cfg = at.session_state["cfg"]
    for page in ("overview", "assets", "scenarios"):
        run_page(page, cfg, "import_edited")


# ── 分步填写与引导 ───────────────────────────────────────────────────────
def test_data_page_shows_progress_and_group_status():
    cfg = demo_cfg()
    cfg["sim"]["monthly_expense"] = None
    at = run_page("data", cfg, "import")
    done, total = calc.required_progress(cfg)["_all"]
    assert at.get("progress")[0].proto.text == f"必填项 已填 {done} / {total}"
    body = texts(at)
    assert "缺 1 项" in body and "已完成" in body


def test_next_and_previous_group_buttons_move_between_groups():
    at = run_page("data", demo_cfg(), "import")
    assert at.radio(key="w:data_group").value == GROUPS[0]
    assert not any(b.key == "grp_prev" for b in at.button)       # 第一组没有「上一组」
    at.button(key="grp_next").click().run()
    assert at.radio(key="w:data_group").value == GROUPS[1]
    at.button(key="grp_next").click().run()
    at.button(key="grp_prev").click().run()
    assert at.radio(key="w:data_group").value == GROUPS[1]
    assert not at.exception


def test_last_group_offers_link_back_to_overview_not_next():
    at = open_group(run_page("data", demo_cfg(), "import"), GROUPS[-1])
    assert not any(b.key == "grp_next" for b in at.button)


def test_start_fill_button_goes_to_data_page_without_inventing_values():
    at = run_page("overview")
    at.button(key="start_fill").click().run()
    assert not at.exception
    assert "数据与假设" in [t.value for t in at.title]
    assert at.session_state["cfg_source"] == "none"
    assert at.session_state["cfg"]["sim"] == {}


def test_progress_total_follows_pension_mode_and_policy_count():
    cfg = demo_cfg()
    auto_total = calc.required_progress(cfg)["_all"][1]
    cfg["pension"]["auto"] = False
    assert calc.required_progress(cfg)["_all"][1] < auto_total       # 手填月领少几项
    cfg["insurance"] = cfg["insurance"] + [{}]
    assert calc.required_progress(cfg)["_all"][1] > calc.required_progress(
        {**cfg, "insurance": cfg["insurance"][:1]})["_all"][1]


# ── 持仓：表格与文本 ─────────────────────────────────────────────────────
def test_table_mode_renders_without_rewriting_config_text():
    cfg = demo_cfg()
    cfg["funds_dca"] = "000001, 50000, 90000, 100000"       # 带空格的原始写法
    at = open_group(run_page("data", cfg, "import"), "基金、股票、存款")
    assert at.session_state["cfg"]["funds_dca"] == "000001, 50000, 90000, 100000"
    assert at.session_state["cfg_source"] == "import"       # 没有被当成"已修改"


def test_text_mode_edit_writes_back_and_table_reseeds():
    at = open_group(run_page("data", demo_cfg(), "import"), "基金、股票、存款")
    at.radio(key="w:hold_mode").set_value("粘贴文本").run()
    box = next(t for t in at.text_area if t.key == "w:funds_dca")
    box.set_value("000009,100,10,12").run()
    assert at.session_state["cfg"]["funds_dca"] == "000009,100,10,12"
    at.radio(key="w:hold_mode").set_value("表格").run()
    assert not at.exception
    assert at.session_state["cfg"]["funds_dca"] == "000009,100,10,12"


def test_text_mode_blank_means_unfilled():
    at = open_group(run_page("data", demo_cfg(), "import"), "基金、股票、存款")
    at.radio(key="w:hold_mode").set_value("粘贴文本").run()
    next(t for t in at.text_area if t.key == "w:deposits").set_value("   ").run()
    assert at.session_state["cfg"]["deposits"] is None


# ── 导入 / 取消 / 导出 ───────────────────────────────────────────────────
def modified_pending(**sim):
    cfg = calc.cfg_for_export(demo_cfg())
    cfg["sim"].update(sim)
    return validate_config(wrap_export(cfg))


def test_import_confirm_replaces_everything_and_refreshes_widgets():
    at = run_page("data", demo_cfg(), "demo")
    at.session_state["_pending_cfg"] = modified_pending(retire_expense_mo=9999.0)
    at.run()
    assert at.session_state["cfg"]["sim"]["retire_expense_mo"] == 10000.0   # 确认前不改
    assert any("确认后将覆盖" in m.value for m in at.markdown)
    at.button(key="import_confirm").click().run()
    assert not at.exception
    assert at.session_state["cfg"]["sim"]["retire_expense_mo"] == 9999.0
    assert at.session_state["cfg_source"] == "import"
    n = next(n for n in at.number_input if n.label.startswith("退休后每月支出"))
    assert n.value == 9999.0


def test_import_cancel_keeps_current_data():
    at = run_page("data", demo_cfg(), "demo")
    at.session_state["_pending_cfg"] = modified_pending(retire_expense_mo=9999.0)
    at.run()
    at.button(key="import_cancel").click().run()
    assert at.session_state["cfg"]["sim"]["retire_expense_mo"] == 10000.0
    assert at.session_state["cfg_source"] == "demo"
    assert "_pending_cfg" not in at.session_state


UPLOAD_HARNESS = '''
import json, streamlit as st, state
class Up:
    file_id = "f1"
    def __init__(self, b): self.b = b
    def getvalue(self): return self.b
state.init()
state.handle_upload(Up(st.session_state["_bytes"]), "k")
'''


def upload(raw_bytes):
    at = AppTest.from_string(UPLOAD_HARNESS, default_timeout=60)
    at.session_state["_bytes"] = raw_bytes
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def test_invalid_upload_reports_field_and_keeps_data():
    bad = {"global": {"discount_rate": 999}, "hpf": {"balance": -1}}
    at = upload(json.dumps(bad).encode())
    errs = " ".join(at.session_state["_import_error"])
    assert "global.discount_rate" in errs and "hpf.balance" in errs
    assert at.session_state["cfg_source"] == "none"
    assert "_pending_cfg" not in at.session_state


def test_non_json_upload_is_rejected():
    at = upload(b"not json")
    assert at.session_state["_import_error"]


def test_legacy_file_without_version_goes_to_pending_with_note():
    legacy = calc.cfg_for_export(demo_cfg())          # 没有 format / schema_version
    at = upload(json.dumps(legacy).encode())
    clean, warnings = at.session_state["_pending_cfg"]
    assert any("旧版" in w for w in warnings)
    assert clean["sim"]["retire_expense_mo"] == 10000.0


def test_export_then_import_gives_identical_results():
    at = AppTest.from_string(
        "import streamlit as st, state\nstate.init()\nst.session_state['exported'] = state.export_json()",
        default_timeout=60)
    at.session_state["cfg"] = demo_cfg()
    at.session_state["cfg_source"] = "import"
    at.run()
    clean, notes = validate_config(json.loads(at.session_state["exported"]))
    assert notes == []
    today = date(2026, 10, 11)
    a = calc.compute_plan(demo_cfg(), today)
    b = calc.compute_plan(calc.cfg_from_clean(clean), today)
    assert (a.total_npv, a.headline["real"], a.target["total"]) == \
           (b.total_npv, b.headline["real"], b.target["total"])


# ── 审阅发现的回归 ───────────────────────────────────────────────────────
def cfg_blank_contrib_and_retire():
    cfg = demo_cfg()
    cfg["pension"].pop("contrib_end")
    cfg["global"].pop("date_retire")
    return cfg


def cfg_unknown_city():
    cfg = demo_cfg()
    cfg["pension"]["city"] = "苏州"
    return cfg


@pytest.mark.parametrize("page", PAGES)
@pytest.mark.parametrize("make", [cfg_blank_contrib_and_retire, cfg_unknown_city],
                         ids=["blank_contrib_end_and_retire_date", "unknown_city"])
def test_review_cases_render_every_page(page, make):
    run_page(page, make(), "import")


def test_blank_retire_date_stays_editable_and_explains_why():
    at = run_page("data", cfg_blank_contrib_and_retire(), "import")
    dates = {d.label: d for d in at.date_input}
    assert "计划停止工作日期" in dates                    # 补填入口还在
    assert "缴费" in texts(at)                           # 说明为什么必填


def test_unknown_city_is_explained_and_selectable_on_data_page():
    at = open_group(run_page("data", cfg_unknown_city(), "import"), "养老金、公积金、保险")
    assert "苏州" in texts(at)
    sel = next(s for s in at.selectbox if s.label == "所在城市")
    sel.set_value("其他（手动输入）").run()
    assert at.session_state["cfg"]["pension"]["city"] == "其他（手动输入）"


def test_unexpected_calc_error_keeps_data_page_usable():
    harness = ("import calc\n"
               "def boom(*a, **k): raise RuntimeError('boom')\n"
               "calc.compute_plan = boom\n"
               "import shell; shell.main(default=%r)")
    original = calc.compute_plan                          # AppTest 在同一进程里执行，必须还原
    try:
        for page in ("overview", "data"):
            at = AppTest.from_string(harness % page, default_timeout=120)
            at.session_state["cfg"], at.session_state["cfg_source"] = demo_cfg(), "import"
            at.run()
            assert not at.exception, [e.value for e in at.exception]
            assert any("意外错误" in e.value for e in at.error)
        assert at.number_input                            # 数据页的输入框仍在
    finally:
        calc.compute_plan = original


UPLOAD_ORDER_HARNESS = '''
import streamlit as st, state
from views import common as C
class Up:
    file_id = "f1"
    def __init__(self, b): self.b = b
    def getvalue(self): return self.b
state.init()
# 与 shell.main 相同的顺序：先处理上传，再渲染待确认 / 错误提示
st.session_state["up_main"] = Up(st.session_state["_bytes"]) if False else None
state.handle_upload(Up(st.session_state["_bytes"]), "up_main")
C.render_import_status()
'''


def test_pending_confirmation_shows_in_the_same_run_as_upload():
    good = json.dumps(calc.cfg_for_export(demo_cfg())).encode()
    at = AppTest.from_string(UPLOAD_ORDER_HARNESS, default_timeout=60)
    at.session_state["_bytes"] = good
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.button(key="import_confirm")               # 同一轮就有「确认覆盖」


def test_error_shows_in_the_same_run_as_upload():
    at = AppTest.from_string(UPLOAD_ORDER_HARNESS, default_timeout=60)
    at.session_state["_bytes"] = b'{"global":{"discount_rate":999}}'
    at.run()
    assert any("global.discount_rate" in e.value for e in at.error)


def test_shell_processes_uploads_before_rendering_import_status():
    import inspect
    import shell
    src = inspect.getsource(shell.main)
    assert src.index("process_uploads()") < src.index("render_import_status()")
    assert "handle_upload" not in inspect.getsource(shell._sidebar)
    import views.overview as ov
    assert "handle_upload" not in inspect.getsource(ov)   # 页面里不再各自处理上传


def test_upload_values_are_read_from_session_before_widgets_render():
    harness = ("import streamlit as st, state\n"
               "class Up:\n"
               "    file_id='f9'\n"
               "    def getvalue(self): return st.session_state['_bytes']\n"
               "state.init()\n"
               "st.session_state['up_side'] = Up()\n"      # 控件的值已在会话里
               "state.process_uploads()\n"
               "st.write('pending' if state.pending() else 'none')")
    at = AppTest.from_string(harness, default_timeout=60)
    at.session_state["_bytes"] = json.dumps(calc.cfg_for_export(demo_cfg())).encode()
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.markdown[0].value == "pending"


# ── 快速估算 ─────────────────────────────────────────────────────────────
QUICK_LABEL = "快速估算（9 项合计数，粗略）"
FULL_LABEL = "完整填写（逐项，更准确）"


def quick_cfg():
    import calc as c
    full = c.compute_plan(demo_cfg(), date(2026, 10, 11))
    cfg = demo_cfg()
    snap = full.snap_now
    q = c.empty_cfg()
    q["mode"] = "quick"
    q["global"] = {"date_retire": cfg["global"]["date_retire"]}
    q["pension"] = {"birth": cfg["pension"]["birth"], "retire_age": cfg["pension"]["retire_age"],
                    "monthly": round(full.pension_real, 2)}
    q["sim"] = {k: cfg["sim"][k] for k in ("retire_expense_mo", "monthly_income", "monthly_expense")}
    q["quick"] = {"investment": snap["investment"], "cash": snap["cash"],
                  "locked": snap["pension_hpf"] + snap["insurance"]}
    return q


def test_first_open_offers_quick_and_full_entry():
    at = run_page("overview")
    assert at.button(key="start_quick") and at.button(key="start_fill")
    assert not at.metric


def test_quick_button_sets_mode_and_opens_a_nine_item_form():
    at = run_page("overview")
    at.button(key="start_quick").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.session_state["cfg"]["mode"] == "quick"
    assert "数据与假设" in [t.value for t in at.title]
    assert at.get("progress")[0].proto.text == "必填项 已填 0 / 9"
    labels = [n.label for n in at.number_input]
    for must in ("投资资产合计（元）", "存款合计（元）", "社保与保险类资产合计（元）"):
        assert must in labels
    assert at.session_state["cfg"]["sim"] == {}                       # 没有凭空填值


def test_quick_form_filled_gives_a_rough_conclusion_on_overview():
    ov = run_page("overview", quick_cfg(), "manual")
    assert "粗估：按当前假设" in texts(ov)
    assert "快速估算" in " ".join(i.value for i in ov.info)
    assert metric(ov, "两阶段目标") == C.wan(calc.compute_plan(quick_cfg()).target["total"])


@pytest.mark.parametrize("page", PAGES)
def test_every_page_says_it_is_a_rough_estimate_in_quick_mode(page):
    at = run_page(page, quick_cfg(), "manual")
    assert any("快速估算" in i.value for i in at.info)


@pytest.mark.parametrize("page", PAGES)
def test_every_page_renders_for_empty_and_partial_quick_config(page):
    empty = calc.empty_cfg()
    empty["mode"] = "quick"
    run_page(page, empty, "manual")
    part = quick_cfg()
    part["quick"]["cash"] = None
    run_page(page, part, "manual")


def test_quick_overview_lists_the_missing_totals_without_a_conclusion():
    part = quick_cfg()
    part["quick"]["cash"] = None
    at = run_page("overview", part, "manual")
    body = texts(at)
    assert "存款合计" in body and "按当前假设" not in body and not at.metric


def test_editing_a_total_in_the_form_writes_back_and_changes_the_result():
    at = run_page("data", quick_cfg(), "manual")
    n = next(n for n in at.number_input if n.label == "存款合计（元）")
    n.set_value(0.0).run()
    assert not at.exception
    assert at.session_state["cfg"]["quick"]["cash"] == 0.0
    before = calc.compute_plan(quick_cfg()).headline["margin"]
    after = calc.compute_plan(at.session_state["cfg"]).headline["margin"]
    assert after < before


def test_switch_to_full_keeps_inputs_and_asks_for_the_split():
    at = run_page("data", quick_cfg(), "manual")
    at.radio(key="w:data_mode").set_value(FULL_LABEL).run()
    assert not at.exception, [e.value for e in at.exception]
    cfg = at.session_state["cfg"]
    assert cfg["mode"] == "full"
    assert calc.QUICK_FUND_LABEL in cfg["funds_dca"] and calc.QUICK_CASH_LABEL in cfg["deposits"]
    assert cfg["pension"]["monthly"] == quick_cfg()["pension"]["monthly"]
    assert cfg["quick"] == quick_cfg()["quick"]                    # 快速估算的合计数保留，便于对照
    assert any("拆成个人账户、公积金、储蓄险" in s.value for s in at.success)
    assert at.get("progress")[0].proto.text.startswith("必填项 已填")


def test_switch_back_to_quick_keeps_everything():
    at = run_page("data", quick_cfg(), "manual")
    at.radio(key="w:data_mode").set_value(FULL_LABEL).run()
    at.radio(key="w:data_mode").set_value(QUICK_LABEL).run()
    assert not at.exception
    cfg = at.session_state["cfg"]
    assert cfg["mode"] == "quick" and cfg["quick"] == quick_cfg()["quick"]
    assert not calc.compute_plan(cfg).missing


def test_full_demo_is_unchanged_by_quick_mode_existing():
    at = run_page("overview", demo_cfg(), "demo")
    assert not any("快速估算" in i.value for i in at.info)
    assert "粗估" not in texts(at)


def test_quick_config_roundtrips_through_the_export_function_path():
    q = quick_cfg()
    clean, notes = validate_config(wrap_export(calc.cfg_for_export(q)))
    assert notes == [] and calc.cfg_from_clean(clean)["mode"] == "quick"
