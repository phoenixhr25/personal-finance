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


def texts(at):
    parts = [m.value for m in at.markdown] + [i.value for i in at.info]
    parts += [h.value for h in at.subheader] + [w.value for w in at.warning]
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
    at = run_page("data", demo_cfg(), "import")
    n = next(n for n in at.number_input if n.label.startswith("每月总支出"))
    n.set_value(None).run()
    assert at.session_state["cfg"]["sim"]["monthly_expense"] is None
    n = next(n for n in at.number_input if n.label.startswith("每月总支出"))
    n.set_value(0.0).run()
    assert at.session_state["cfg"]["sim"]["monthly_expense"] == 0.0


def test_none_declared_checkbox_marks_holding_as_empty():
    cfg = demo_cfg()
    cfg["funds_dca"] = None
    at = run_page("data", cfg, "import")
    assert any("定投基金" in i.label for i in calc.compute_plan(cfg).missing)
    box = [c for c in at.checkbox if c.key.startswith("w:funds_dca")][0]
    box.check().run()
    assert at.session_state["cfg"]["funds_dca"] == ""
    assert not any(i.path == ("funds_dca",) for i in calc.compute_plan(at.session_state["cfg"]).missing)


def test_insurance_count_resizes_and_keeps_filled_policy():
    at = run_page("data", demo_cfg(), "import")
    first = copy.deepcopy(at.session_state["cfg"]["insurance"][0])
    cnt = next(n for n in at.number_input if n.label == "保单数量")
    cnt.set_value(2).run()
    ins = at.session_state["cfg"]["insurance"]
    assert len(ins) == 2 and ins[0] == first and ins[1] == {}
    assert any("保单 2" in i.label for i in calc.compute_plan(at.session_state["cfg"]).missing)
    cnt = next(n for n in at.number_input if n.label == "保单数量")
    cnt.set_value(0).run()
    assert at.session_state["cfg"]["insurance"] == []


def test_every_number_input_has_bounds():
    at = run_page("data", demo_cfg(), "import")
    assert [n.label for n in at.number_input if n.min is None or n.max is None] == []


@pytest.mark.parametrize("pick", ["min", "max"])
def test_extreme_legal_values_do_not_crash_any_page(pick):
    at = run_page("data", demo_cfg(), "import")
    for _ in range(2):          # 保单数量变化后会出现新的输入框
        for n in at.number_input:
            n.set_value(n.min if pick == "min" else n.max)
        at.run()
        assert not at.exception, [e.value.splitlines()[0] for e in at.exception]
    cfg = at.session_state["cfg"]
    for page in ("overview", "assets", "scenarios"):
        run_page(page, cfg, "import_edited")


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
