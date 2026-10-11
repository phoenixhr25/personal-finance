"""配置状态：一份规范配置放在 session_state，所有页面读同一份。

Streamlit 的控件状态在控件不再渲染（例如切到别的页面）时会被丢弃，
所以数据不放在控件 key 里：控件只是编辑器，每次改动通过回调写回规范配置。
导入、示例、清空都只改规范配置，并清掉旧的控件状态，让控件从配置重新取值。
"""
import json
import time
from datetime import date

import streamlit as st

import calc
from config_io import ConfigError, MAX_FILE_BYTES, validate_config, wrap_export

CFG, SRC, PENDING, ERRORS, NOTICE = "cfg", "cfg_source", "_pending_cfg", "_import_error", "_notice"
WIDGET_PREFIX = "w:"
PLAN_KEY = "_plan"

SOURCE_LABELS = {
    "none": "尚无数据",
    "demo": "虚构示例（不是你的数据）",
    "demo_edited": "虚构示例（已修改，起点仍是虚构数据）",
    "import": "导入的配置文件",
    "import_edited": "导入的配置（已在页面上修改）",
    "manual": "手动填写",
}
DEMO_PATH = "examples/demo_config.json"


# ── 初始化与读写 ──────────────────────────────────────────────────────────
def init():
    if CFG not in st.session_state:
        st.session_state[CFG] = calc.empty_cfg()
        st.session_state[SRC] = "none"


def cfg():
    return st.session_state[CFG]


def source():
    return st.session_state.get(SRC, "none")


def is_demo():
    return source().startswith("demo")


def has_data():
    return source() != "none"


def get(*path, default=None):
    cur = cfg()
    for p in path:
        try:
            cur = cur[p]
        except (KeyError, IndexError, TypeError):
            return default
        if cur is None:
            return default
    return cur


def set_value(path, value):
    """写入规范配置并记录来源。path 如 ("pension","account") 或 ("insurance", 0, "cash_value")。"""
    cur = cfg()
    try:
        for p in path[:-1]:
            cur = cur[p]
        if isinstance(cur, list) and path[-1] >= len(cur):
            return                      # 保单数量刚被调小：已不存在的条目不再写入
    except (IndexError, KeyError, TypeError):
        return
    cur[path[-1]] = value
    touch()


def touch():
    src = source()
    st.session_state[SRC] = {"none": "manual", "demo": "demo_edited",
                             "import": "import_edited"}.get(src, src)


def _drop_widget_state():
    for k in [k for k in st.session_state if str(k).startswith(WIDGET_PREFIX)]:
        del st.session_state[k]


def load(clean, src):
    """用已校验的配置整体替换当前数据。"""
    st.session_state[CFG] = calc.cfg_from_clean(clean)
    st.session_state[SRC] = src
    _drop_widget_state()


def load_demo():
    with open(DEMO_PATH, encoding="utf-8") as f:
        clean, _ = validate_config(json.load(f))
    load(clean, "demo")        # 示例有常驻标识，不再另发一次性提示


def clear_all():
    st.session_state[CFG] = calc.empty_cfg()
    st.session_state[SRC] = "none"
    _drop_widget_state()
    st.session_state[NOTICE] = "已清空当前数据。"


# ── 测算（同一份结果供所有页面使用）─────────────────────────────────────────
def plan():
    key = (json.dumps(cfg(), sort_keys=True, default=str), str(date.today()),
           int(time.time() // 300))          # 行情 5 分钟刷新一次
    hit = st.session_state.get(PLAN_KEY)
    if hit and hit[0] == key:
        return hit[1]
    try:
        result = calc.compute_plan(cfg())
    except Exception as exc:        # 保留编辑入口：不让一次意外异常把整个应用打崩
        result = calc.failed_plan(cfg(), exc)
    st.session_state[PLAN_KEY] = (key, result)
    return result


# ── 导入 / 导出 ──────────────────────────────────────────────────────────
def handle_upload(uploaded, widget_key):
    """同一个文件在重新运行时不会被重复处理（守卫放在最前）。"""
    guard = f"_upload_id:{widget_key}"
    if uploaded is None or st.session_state.get(guard) == uploaded.file_id:
        return
    st.session_state[guard] = uploaded.file_id
    st.session_state.pop(PENDING, None)
    st.session_state[ERRORS] = None
    try:
        raw_bytes = uploaded.getvalue()
        if len(raw_bytes) > MAX_FILE_BYTES:
            raise ConfigError([f"文件过大（{len(raw_bytes) // 1024} KB），配置文件通常不足 10 KB"])
        try:
            raw = json.loads(raw_bytes.decode("utf-8-sig"))
        except (UnicodeDecodeError, ValueError) as e:
            raise ConfigError([f"文件不是有效的 JSON：{e}"])
        st.session_state[PENDING] = validate_config(raw)
    except ConfigError as e:
        st.session_state[ERRORS] = e.problems


UPLOAD_KEYS = ("up_main", "up_side")


def process_uploads():
    """处理所有上传控件的值。必须在渲染导入提示之前调用：
    上传控件的值在本轮运行开始时就已在 session_state 里，不需要等控件渲染。"""
    for k in UPLOAD_KEYS:
        handle_upload(st.session_state.get(k), k)


def confirm_import():
    clean, _ = st.session_state.pop(PENDING)
    load(clean, "import")
    st.session_state[NOTICE] = "配置已载入。"


def cancel_import():
    st.session_state.pop(PENDING, None)


def pending():
    return st.session_state.get(PENDING)


def export_json():
    return json.dumps(wrap_export(calc.cfg_for_export(cfg())), ensure_ascii=False, indent=2)
