"""界面冒烟测试：无界面运行 app.py。需要 streamlit（pip install streamlit pytest）。"""
import os
import sys

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from config_io import validate_config, wrap_export  # noqa: E402
from test_config_io import sample_export  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "app.py")


def fresh():
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def test_default_state_runs_clean():
    at = fresh()
    assert len(at.number_input) > 0


def test_every_number_input_has_bounds():
    at = fresh()
    assert [n.label for n in at.number_input if n.min is None or n.max is None] == []


@pytest.mark.parametrize("pick", [lambda n: n.min, lambda n: n.max], ids=["all_min", "all_max"])
def test_extreme_legal_values_do_not_crash(pick):
    at = fresh()
    for _ in range(2):  # 保单数量变化后会出现新的输入框
        for n in at.number_input:
            n.set_value(pick(n))
        at.run()
    for b in at.button:
        if "运行计算" in (b.label or ""):
            b.click().run()
    assert not at.exception, [e.value.splitlines()[0] for e in at.exception]


def test_import_confirm_applies_and_cancel_keeps():
    cfg = sample_export()
    cfg["hpf"]["balance"] = 123456.0
    clean = validate_config(wrap_export(cfg))

    at = fresh()
    at.session_state["_pending_cfg"] = clean
    at.run()
    assert at.session_state["hpf_bal"] != 123456.0      # 确认前不改动
    at.button(key="import_confirm").click().run()
    assert not at.exception
    assert at.session_state["hpf_bal"] == 123456.0

    at = fresh()
    at.session_state["_pending_cfg"] = clean
    at.run()
    at.button(key="import_cancel").click().run()
    assert at.session_state["hpf_bal"] != 123456.0


def test_persistent_error_message_after_bad_import():
    at = fresh()
    at.session_state["_import_error"] = ["global.discount_rate 超出合理范围"]
    at.run()
    at.run()
    assert any("配置未导入" in e.value for e in at.error)
