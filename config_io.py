"""配置文件的校验与版本迁移。

纯函数，不依赖 Streamlit。导入时先整体校验，通过后才会写入界面状态。
"""
import math
from datetime import date

CONFIG_FORMAT = "personal-finance-config"
SCHEMA_VERSION = 2
MAX_FILE_BYTES = 1_000_000
MAX_TEXT_CHARS = 20_000
RETIRE_AGES = (50, 55, 60)   # 改革前的原法定退休年龄


class ConfigError(Exception):
    """配置文件无法使用。problems 里是逐条的具体原因。"""

    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__("；".join(self.problems))


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


# 字段规格：名称 -> (类型, 最小值, 最大值)。类型 f=浮点 i=整数 s=字符串 b=布尔 d=ISO 日期
_SPEC = {
    "global": {
        "discount_rate": ("f", 0.0, 0.30),
        "proj_invest_rate": ("f", -0.20, 0.30),
        "inflation": ("f", 0.0, 0.10),
        "date_retire": ("d",), "date_pension_start": ("d",), "date_life_end": ("d",),
        "date_base_1": ("d",), "date_base_2": ("d",),
    },
    "pension": {
        "account": ("f", 0, 1e9), "monthly": ("f", 0, 1e7), "rate": ("f", -0.10, 0.30),
        "auto": ("b",), "city": ("s", 20), "city_wage": ("f", 0, 1e6),
        "wage_growth": ("f", -0.10, 0.30), "contrib_years": ("i", 0, 60),
        "contrib_index": ("f", 0, 10), "retire_age": ("i", 50, 60),
        "birth": ("d",), "contrib_end": ("d",),
    },
    "hpf": {"balance": ("f", 0, 1e9), "years": ("f", 0, 80)},
    "snapshots": {k: ("f", 0, 1e10) for k in
                  ("b1_ph", "b1_ins", "b1_inv", "b1_csh", "b2_ph", "b2_ins", "b2_inv", "b2_csh")},
    "sim": {
        "monthly_income": ("f", 0, 1e8), "monthly_expense": ("f", 0, 1e8),
        "retire_expense_mo": ("f", 0, 1e8), "semi_income": ("f", 0, 1e8),
        "income_interrupt_months": ("i", 1, 600),
        "target_ph": ("i", 0, 100), "target_ins": ("i", 0, 100),
        "target_inv": ("i", 0, 100), "target_csh": ("i", 0, 100),
    },
}
_INS_SPEC = {
    "name": ("s", 40), "cash_value": ("f", 0, 1e9), "cost_basis": ("f", 0, 1e9),
    "annual_premium": ("f", 0, 1e9), "premium_years_left": ("i", 0, 100),
    "maturity_value": ("f", 0, 1e9), "years_to_maturity": ("i", 0, 100),
    "policy_irr": ("f", -0.20, 0.30),
}
_TEXT_FIELDS = ("funds_dca", "stocks", "deposits")
MAX_POLICIES = 5


def bounds(section, key):
    """返回字段的 (最小值, 最大值)，供界面输入框使用，与导入校验共用同一组范围。"""
    spec = _INS_SPEC if section == "insurance" else _SPEC[section]
    kind, lo, hi = spec[key][:3]
    return (int(lo), int(hi)) if kind == "i" else (float(lo), float(hi))


def _check(path, value, spec, problems):
    """校验单个字段，返回规范化后的值；不合格时记录原因并返回 None。"""
    kind = spec[0]
    if kind == "b":
        if isinstance(value, bool):
            return value
    elif kind == "s":
        if isinstance(value, str) and len(value) <= spec[1]:
            return value
    elif kind == "d":
        if isinstance(value, str):
            try:
                date.fromisoformat(value)
                return value
            except ValueError:
                pass
    elif kind in ("f", "i"):
        if _is_num(value):
            lo, hi = spec[1], spec[2]
            if kind == "i":
                if float(value) != int(value):
                    problems.append(f"{path} 必须是整数，收到 {value}")
                    return None
                value = int(value)
            else:
                value = float(value)
            if lo <= value <= hi:
                return value
            problems.append(f"{path} 超出合理范围 [{lo:g}, {hi:g}]，收到 {value:g}")
            return None
    problems.append(f"{path} 的类型或格式不正确")
    return None


def _check_section(name, raw, spec, problems, warnings):
    if not isinstance(raw, dict):
        problems.append(f"{name} 必须是对象")
        return {}
    clean = {}
    for key, value in raw.items():
        path = f"{name}.{key}"
        if key not in spec:
            warnings.append(f"忽略未知字段 {path}")
            continue
        if value is None:          # 导出时未启用的项会写成 null，按缺省处理
            continue
        got = _check(path, value, spec[key], problems)
        if got is not None:
            clean[key] = got
    if name == "pension" and clean.get("retire_age") not in (None, *RETIRE_AGES):
        problems.append(f"pension.retire_age 只能是 {list(RETIRE_AGES)}，收到 {clean['retire_age']}")
    return clean


def migrate(raw):
    """把旧版配置升级到当前版本。返回 (新字典, 提示列表)。不修改入参。"""
    notes = []
    data = dict(raw)
    version = data.get("schema_version")
    if version is None:
        notes.append("这是旧版配置文件（没有版本号），已按旧版格式读取")
        if "funds_dca" not in data and "funds" in data:
            data["funds_dca"] = data["funds"]
            notes.append("旧字段 funds 已并入定投基金 funds_dca")
        data.pop("funds", None)
        version = 1
    if version == 1:
        # v2：retire_age 从「退休年龄」改为「改革前的原法定退休年龄」，没有 65 这一档
        pension = data.get("pension")
        if isinstance(pension, dict) and pension.get("retire_age") == 65:
            data["pension"] = {**pension, "retire_age": 60}
            notes.append("退休年龄 65 已改为原法定退休年龄 60，请补填出生年月以按延迟退休规则推算")
    return data, notes


def validate_config(raw):
    """校验并规范化配置。返回 (clean, warnings)；无法使用时抛出 ConfigError。

    clean 只包含合格且非空的字段，缺失项由界面使用各自的缺省值。
    """
    if not isinstance(raw, dict):
        raise ConfigError(["配置文件顶层必须是对象"])

    fmt = raw.get("format")
    if fmt is not None and fmt != CONFIG_FORMAT:
        raise ConfigError([f"不是本工具的配置文件（format={fmt!r}）"])
    version = raw.get("schema_version")
    if version is not None:
        if isinstance(version, bool) or not isinstance(version, int):
            raise ConfigError(["schema_version 必须是整数"])
        if version > SCHEMA_VERSION:
            raise ConfigError([f"配置由更新版本（v{version}）生成，当前只支持到 v{SCHEMA_VERSION}"])
        if version < 1:
            raise ConfigError(["schema_version 必须 ≥ 1"])

    data, warnings = migrate(raw)
    problems = []
    clean = {}

    for name, spec in _SPEC.items():
        if name in data:
            sec = _check_section(name, data[name], spec, problems, warnings)
            if sec:
                clean[name] = sec

    if "insurance" in data:
        ins = data["insurance"]
        if not isinstance(ins, list):
            problems.append("insurance 必须是列表")
        elif len(ins) > MAX_POLICIES:
            problems.append(f"insurance 最多 {MAX_POLICIES} 张保单，收到 {len(ins)}")
        else:
            rows = []
            for i, item in enumerate(ins):
                rows.append(_check_section(f"insurance[{i}]", item, _INS_SPEC, problems, warnings))
            clean["insurance"] = rows

    for key in _TEXT_FIELDS:
        if key in data and data[key] is not None:
            v = data[key]
            if not isinstance(v, str):
                problems.append(f"{key} 必须是文本")
            elif len(v) > MAX_TEXT_CHARS:
                problems.append(f"{key} 过长（{len(v)} 字符，上限 {MAX_TEXT_CHARS}）")
            else:
                clean[key] = v

    known = set(_SPEC) | {"insurance", "format", "schema_version"} | set(_TEXT_FIELDS)
    for key in data:
        if key not in known:
            warnings.append(f"忽略未知字段 {key}")

    g = clean.get("global", {})
    order = [("date_retire", "date_pension_start", "退休日期晚于法定领金日期"),
             ("date_pension_start", "date_life_end", "法定领金日期晚于预期寿命终止日"),
             ("date_base_1", "date_base_2", "基期起始晚于对比节点")]
    for a, b, msg in order:
        if a in g and b in g and date.fromisoformat(g[a]) > date.fromisoformat(g[b]):
            warnings.append(f"日期顺序异常：{msg}，请确认")

    if problems:
        raise ConfigError(problems)
    return clean, warnings


def wrap_export(data):
    """给导出内容加上格式标识和版本号。"""
    return {"format": CONFIG_FORMAT, "schema_version": SCHEMA_VERSION, **data}
