"""共享测算：配置 → 一份结果（Plan）。

概览、资产、情景三页都读这一份结果，不各算各的。纯函数，不依赖 Streamlit。
计算公式仍在 finance_engine.py，这里只负责：
  1. 判断哪些必填项缺失（区分"未填写"和"明确填 0"）；
  2. 解析持仓文本，并报告无法识别的行；
  3. 把配置喂给引擎，得到资产、养老金、情景、压力测试；
  4. 用同一个两阶段目标比较所有情景。
"""
from dataclasses import dataclass, field
from datetime import date, datetime

from dateutil.relativedelta import relativedelta

from finance_engine import (
    annuity_months, auto_monthly_pension, build_rows, compute_deposits, compute_funds,
    compute_hpf, compute_insurance, compute_pension, compute_stocks, eaa, margin_ratio,
    months_between, retirement_projection, run_scenario, run_stress, statutory_retirement,
    two_phase_target, weighted_avg_return, _sim_params,
)
from market_api import fetch_fund_prices, fetch_stock_prices

# ── 分组（与「数据与假设」页的四个分组一致）──────────────────────────────
GROUP_BASIC = "退休目标与基本信息"
GROUP_SOCIAL = "养老金、公积金、保险"
GROUP_HOLD = "基金、股票、存款"
GROUP_CASH = "收支与未来假设"
GROUPS = (GROUP_BASIC, GROUP_SOCIAL, GROUP_HOLD, GROUP_CASH)

# ── 参考数据与默认假设 ───────────────────────────────────────────────────
CITY_BASE_YEAR = 2025
OTHER_CITY = "其他（手动输入）"
# 2025 年基本养老金计发基数（元/月）。第二项 False 表示尚未核实为当地公布的计发基数
CITY_BASES = {
    "深圳": (11293, True), "北京": (12049, True), "上海": (12434, True),
    "广州": (9493, True), "杭州": (10500, False), "成都": (8500, False),
    "武汉": (8500, False), "南京": (9500, False), OTHER_CITY: (0, False),
}

# 假设类参数：用户没填时用默认值，并在界面上标明"默认"，不当作用户的数据
DEFAULTS = {
    "discount_rate": 0.03, "proj_invest_rate": 0.05, "inflation": 0.025,
    "date_life_end": date(2080, 1, 1), "rate": 0.015, "wage_growth": 0.02,
    "hpf_years": 10.0, "income_interrupt_months": 12, "hpf_rate": 0.025,
}

STRESS_CASES = [
    ("基准（继续工作）", {}, "与「继续工作」情景相同"),
    ("市场跌 20%", {"investment_shock": 0.8}, "现有基金、股票市值一次性下调 20%"),
    ("市场跌 40%", {"investment_shock": 0.6}, "现有基金、股票市值一次性下调 40%"),
    ("通胀 3%", {"inflation": 0.03},
     "局部：只提高退休前每月支出；折算系数和退休后支出目标没有随之变化"),
    ("养老金打七折", {"pension_mult": 0.7}, "月领 × 70%，养老期缺口和目标已重算"),
    ("投资收益 1%", {"proj_rate": 0.01}, "只降低退休前的投资增长；退休后收益率未模拟"),
    ("组合冲击（跌 20% + 七折）", {"investment_shock": 0.8, "pension_mult": 0.7},
     "市场下跌与养老金打折同时发生"),
]


@dataclass
class Issue:
    group: str
    path: tuple
    label: str
    message: str
    level: str = "missing"      # missing 必填缺失 | invalid 有问题但不阻断
    stage: str = "retire"       # assets 资产 | pension 养老金与日期 | retire 退休测算


# ═════════════════════════════════════════════════════════════════════════
# 配置读取
# ═════════════════════════════════════════════════════════════════════════
def _g(cfg, *path, default=None):
    cur = cfg
    for p in path:
        if cur is None:
            return default
        try:
            cur = cur[p]
        except (KeyError, IndexError, TypeError):
            return default
    return default if cur is None else cur


def _d(v):
    """配置里的日期是 ISO 字符串；已经是 date 的原样返回。"""
    if v is None or isinstance(v, date):
        return v
    try:
        return date.fromisoformat(v)
    except (TypeError, ValueError):
        return None


def _assumed(cfg, section, key, name):
    """假设类参数：返回 (值, 是否为默认值)。"""
    v = _g(cfg, section, key)
    if v is None:
        return DEFAULTS[name], True
    return v, False


# ═════════════════════════════════════════════════════════════════════════
# 持仓文本解析：返回 (条目, 问题行)。问题行不参与计算，但会在界面上指出
# ═════════════════════════════════════════════════════════════════════════
def _lines(text):
    for n, raw in enumerate((text or "").splitlines(), 1):
        line = raw.replace("，", ",").strip()
        if line:
            yield n, raw.strip(), [p.strip() for p in line.split(",")]


def parse_fund_dca(text):
    """A 类定投基金：代码, 份额, 持有成本(总额¥), 当前市值(总额¥)"""
    items, problems = [], []
    for n, raw, parts in _lines(text):
        if len(parts) < 4:
            problems.append((n, raw, "需要 4 列：代码, 份额, 持有成本, 当前市值"))
            continue
        try:
            shares, cost, value = float(parts[1]), float(parts[2]), float(parts[3])
        except ValueError:
            problems.append((n, raw, "份额、成本、市值需要是数字"))
            continue
        if shares <= 0:
            problems.append((n, raw, "份额必须大于 0"))
            continue
        items.append({"code": parts[0], "shares": shares, "cost_nav": cost / shares,
                      "manual_nav": value / shares, "buy_date": None})
    return items, problems


def parse_stocks(text):
    """B 类单笔：代码, 股数/份额, 成本价, 买入日期[, 当前价]"""
    items, problems = [], []
    for n, raw, parts in _lines(text):
        if len(parts) < 4:
            problems.append((n, raw, "需要至少 4 列：代码, 股数, 成本价, 买入日期"))
            continue
        try:
            buy = datetime.strptime(parts[3], "%Y-%m-%d").date()
        except ValueError:
            problems.append((n, raw, "买入日期格式应为 YYYY-MM-DD"))
            continue
        try:
            items.append({
                "code": parts[0], "shares": float(parts[1]), "cost_price": float(parts[2]),
                "buy_date": buy,
                "manual_price": float(parts[4]) if len(parts) > 4 and parts[4] else None,
            })
        except ValueError:
            problems.append((n, raw, "股数、成本价、当前价需要是数字"))
    return items, problems


def parse_deposits(text):
    """存款：银行名, 类型, 余额[, 年化利率]"""
    items, problems = [], []
    for n, raw, parts in _lines(text):
        if len(parts) < 3:
            problems.append((n, raw, "需要至少 3 列：银行名, 类型, 余额"))
            continue
        try:
            items.append({
                "bank": parts[0], "type": parts[1], "balance": float(parts[2]),
                "rate": float(parts[3]) if len(parts) > 3 and parts[3] else 0.0,
                "term_years": 0,
            })
        except ValueError:
            problems.append((n, raw, "余额、利率需要是数字"))
    return items, problems


# ═════════════════════════════════════════════════════════════════════════
# 缺失项与校验
# ═════════════════════════════════════════════════════════════════════════
INS_FIELDS = (
    ("cash_value", "现金价值"), ("cost_basis", "已缴保费"), ("annual_premium", "年缴保费"),
    ("premium_years_left", "还需缴年"), ("maturity_value", "满期金额"),
    ("years_to_maturity", "距满期年"), ("policy_irr", "保单 IRR"),
)


def pension_start_info(cfg):
    """领金日期：出生年月 + 原法定年龄可推算时按延迟退休规则推算，否则用手填日期。

    返回 (领金日, 法定退休年龄月数或 None, 来源说明)；缺信息时领金日为 None。
    """
    birth = _d(_g(cfg, "pension", "birth"))
    age0 = _g(cfg, "pension", "retire_age")
    if birth and age0:
        age_m, start = statutory_retirement(birth, int(age0))
        return start, age_m, "按渐进式延迟退休规则推算"
    manual = _d(_g(cfg, "global", "date_pension_start"))
    if manual:
        return manual, None, "手动填写"
    return None, None, ""


@dataclass
class Requirement:
    group: str
    path: tuple
    label: str
    filled: bool
    stage: str = "retire"
    hint: str = "未填写"


def requirements(cfg):
    """当前配置下所有适用的必填项及是否已填。总数会随养老金模式、保单数量变化。"""
    req = []

    def need(group, path, label, filled, stage="retire", hint="未填写"):
        req.append(Requirement(group, tuple(path), label, bool(filled), stage, hint))

    # —— 退休目标与基本信息
    # 个人账户缴费到留空时，默认等于计划停止工作日期，养老金推算要用到它
    feeds_pension = (bool(_g(cfg, "pension", "auto", default=True))
                     and _d(_g(cfg, "pension", "contrib_end")) is None)
    need(GROUP_BASIC, ("global", "date_retire"), "计划停止工作日期",
         _d(_g(cfg, "global", "date_retire")) is not None,
         "pension" if feeds_pension else "retire",
         "未填写（个人账户缴费到留空时，缴费截止日默认取这一天）" if feeds_pension else "未填写")
    start, _, _ = pension_start_info(cfg)
    need(GROUP_BASIC, ("global", "date_pension_start"), "开始领取养老金的日期", start is not None,
         "pension", "填写出生年月和原法定退休年龄，或直接填写领取日期")
    need(GROUP_BASIC, ("sim", "retire_expense_mo"), "退休后每月支出（按今天的物价）",
         _g(cfg, "sim", "retire_expense_mo") is not None)

    # —— 养老金、公积金、保险
    need(GROUP_SOCIAL, ("pension", "account"), "养老保险个人账户余额",
         _g(cfg, "pension", "account") is not None, "assets")
    if _g(cfg, "pension", "auto", default=True):
        city = _g(cfg, "pension", "city")
        known = city in CITY_BASES
        need(GROUP_SOCIAL, ("pension", "city"), "所在城市", known, "pension",
             "未填写" if city is None else
             f"「{city}」不在预设城市里，请改选「{OTHER_CITY}」并填写当地计发基数")
        if city == OTHER_CITY:
            need(GROUP_SOCIAL, ("pension", "city_wage"), "当地计发基数",
                 _g(cfg, "pension", "city_wage") is not None, "pension")
        need(GROUP_SOCIAL, ("pension", "contrib_years"), "预计缴费年限",
             _g(cfg, "pension", "contrib_years") is not None, "pension")
        need(GROUP_SOCIAL, ("pension", "contrib_index"), "缴费指数",
             _g(cfg, "pension", "contrib_index") is not None, "pension")
        need(GROUP_BASIC, ("pension", "retire_age"), "原法定退休年龄（改革前）",
             _g(cfg, "pension", "retire_age") is not None, "pension")
    else:
        need(GROUP_SOCIAL, ("pension", "monthly"), "预计养老金月领（今天的购买力）",
             _g(cfg, "pension", "monthly") is not None, "pension")
    need(GROUP_SOCIAL, ("hpf", "balance"), "公积金余额", _g(cfg, "hpf", "balance") is not None, "assets")
    ins = cfg.get("insurance") if isinstance(cfg, dict) else None
    need(GROUP_SOCIAL, ("insurance",), "储蓄险保单数量（没有填 0）", ins is not None, "assets")
    for i, pol in enumerate(ins or []):
        for key, label in INS_FIELDS:
            need(GROUP_SOCIAL, ("insurance", i, key), f"保单 {i + 1} · {label}",
                 (pol or {}).get(key) is not None, "assets")

    # —— 基金、股票、存款
    for key, label in (("funds_dca", "定投基金"), ("stocks", "单笔买入 / ETF / A 股"),
                       ("deposits", "银行存款")):
        need(GROUP_HOLD, (key,), label, cfg.get(key) is not None, "assets",
             "未填写；没有这类资产请勾选「暂无」")

    # —— 收支
    for key, label in (("monthly_income", "每月税后收入"), ("monthly_expense", "每月总支出")):
        need(GROUP_CASH, ("sim", key), label, _g(cfg, "sim", key) is not None)
    return req


def required_progress(cfg):
    """各组和合计的 (已填, 总数)。"""
    out = {g: [0, 0] for g in GROUPS}
    for r in requirements(cfg):
        out[r.group][1] += 1
        out[r.group][0] += 1 if r.filled else 0
    done = sum(v[0] for v in out.values())
    total = sum(v[1] for v in out.values())
    return {**{g: tuple(v) for g, v in out.items()}, "_all": (done, total)}


def collect_issues(cfg):
    out = [Issue(r.group, r.path, r.label, r.hint, "missing", r.stage)
           for r in requirements(cfg) if not r.filled]
    start, _, _ = pension_start_info(cfg)

    # —— 不阻断的问题
    for key, parser, label in (("funds_dca", parse_fund_dca, "定投基金"),
                               ("stocks", parse_stocks, "单笔买入"),
                               ("deposits", parse_deposits, "银行存款")):
        for n, raw, why in parser(cfg.get(key))[1]:
            out.append(Issue(GROUP_HOLD, (key,), f"{label} 第 {n} 行",
                             f"{why}（已忽略这一行：{raw}）", "invalid", "assets"))
    d_ret = _d(_g(cfg, "global", "date_retire"))
    life_end = _d(_g(cfg, "global", "date_life_end")) or DEFAULTS["date_life_end"]
    if start and life_end <= start:
        out.append(Issue(GROUP_CASH, ("global", "date_life_end"), "预期寿命终止日",
                         "不晚于开始领取养老金的日期，养老金现值会是 0", "invalid", "pension"))
    if d_ret and start and start < d_ret:
        out.append(Issue(GROUP_BASIC, ("global", "date_pension_start"), "开始领取养老金的日期",
                         "早于计划停止工作日期，过渡期按 0 个月计算", "invalid", "pension"))
    return out


# ═════════════════════════════════════════════════════════════════════════
# 结果对象
# ═════════════════════════════════════════════════════════════════════════
@dataclass
class Plan:
    today: date
    issues: list = field(default_factory=list)
    assets_ready: bool = False
    pension_ready: bool = False
    retire_ready: bool = False
    assumptions: dict = field(default_factory=dict)   # 名称 -> (值, 是否默认)
    # 资产
    rows: list = field(default_factory=list)
    pension: dict = None
    hpf: dict = None
    ins_list: list = field(default_factory=list)
    fund_list: list = field(default_factory=list)
    stock_list: list = field(default_factory=list)
    dep_list: list = field(default_factory=list)
    layer_mv: dict = field(default_factory=dict)
    total_mv: float = 0.0
    total_cost: float = 0.0
    total_npv: float = 0.0
    npv_complete: bool = False
    w_return: float = 0.0
    eaa_month: float = 0.0
    snap_now: dict = None
    snap_ret: dict = None
    snap_b1: dict = None
    snap_b2: dict = None
    base_dates: tuple = (None, None)
    price_failed: list = field(default_factory=list)
    # 养老金与日期
    date_retire: date = None
    pension_start: date = None
    pension_start_note: str = ""
    pension_age_months: int = None
    pension_mode: str = "auto"
    pension_nominal: float = 0.0
    pension_real: float = 0.0
    pension_detail: dict = field(default_factory=dict)
    years_to_retire: float = 0.0
    deflator: float = 1.0
    # 退休测算
    target: dict = None
    retire_expense: float = 0.0
    ref4: float = 0.0               # 未扣养老金的 4% 参考值（仅对照）
    scenarios: list = field(default_factory=list)
    stress: list = field(default_factory=list)
    paths: dict = field(default_factory=dict)
    error: str = None               # 测算过程中的意外异常（界面据此保留编辑入口）

    @property
    def missing(self):
        return [i for i in self.issues if i.level == "missing"]

    @property
    def problems(self):
        return [i for i in self.issues if i.level == "invalid"]

    @property
    def headline(self):
        return self.scenarios[0] if self.scenarios else None

    @property
    def investable_now(self):
        return (self.snap_now["investment"] + self.snap_now["cash"]) if self.snap_now else 0.0


# ═════════════════════════════════════════════════════════════════════════
# 计算
# ═════════════════════════════════════════════════════════════════════════
def _ins_inputs(cfg):
    out = []
    for i, p in enumerate(cfg.get("insurance") or []):
        out.append({
            "name": p.get("name") or f"储蓄险{i + 1}",
            "cash_value": float(p["cash_value"]), "cost_basis": float(p["cost_basis"]),
            "annual_premium": float(p["annual_premium"]),
            "premium_years_left": int(p["premium_years_left"]),
            "maturity_value": float(p["maturity_value"]),
            "years_to_maturity": int(p["years_to_maturity"]),
            "policy_irr": float(p["policy_irr"]),
        })
    return out


def compute_plan(cfg, today=None, fund_lookup=None, stock_lookup=None):
    today = today or date.today()
    issues = collect_issues(cfg)
    plan = Plan(today=today, issues=issues)

    def blocked(stage):
        return any(i.level == "missing" and i.stage == stage for i in issues)

    plan.assets_ready = not blocked("assets")
    plan.pension_ready = plan.assets_ready and not blocked("pension")
    plan.retire_ready = plan.pension_ready and not blocked("retire")

    discount, d_def = _assumed(cfg, "global", "discount_rate", "discount_rate")
    invest, i_def = _assumed(cfg, "global", "proj_invest_rate", "proj_invest_rate")
    infl, f_def = _assumed(cfg, "global", "inflation", "inflation")
    life_end = _d(_g(cfg, "global", "date_life_end"))
    life_def = life_end is None
    life_end = life_end or DEFAULTS["date_life_end"]
    acct_rate, r_def = _assumed(cfg, "pension", "rate", "rate")
    growth, w_def = _assumed(cfg, "pension", "wage_growth", "wage_growth")
    hpf_years, h_def = _assumed(cfg, "hpf", "years", "hpf_years")
    interrupt, n_def = _assumed(cfg, "sim", "income_interrupt_months", "income_interrupt_months")
    plan.assumptions = {
        "discount_rate": (discount, d_def), "proj_invest_rate": (invest, i_def),
        "inflation": (infl, f_def), "date_life_end": (life_end, life_def),
        "account_rate": (acct_rate, r_def), "wage_growth": (growth, w_def),
        "hpf_years": (hpf_years, h_def), "interrupt_months": (interrupt, n_def),
    }
    if not plan.assets_ready:
        return plan

    # —— 资产
    funds_raw, _ = parse_fund_dca(cfg.get("funds_dca"))
    stocks_raw, _ = parse_stocks(cfg.get("stocks"))
    deps_raw, _ = parse_deposits(cfg.get("deposits"))
    fund_in = fetch_fund_prices(funds_raw, lookup=fund_lookup)
    stock_in = fetch_stock_prices(stocks_raw, lookup=stock_lookup)
    plan.price_failed = ([f["code"] for f in fund_in if not f.get("current_nav")]
                         + [s["code"] for s in stock_in if not s.get("current_price")])

    account = float(_g(cfg, "pension", "account"))
    ins_in = _ins_inputs(cfg)
    plan.ins_list = compute_insurance(ins_in, discount)
    plan.hpf = compute_hpf({
        "balance": float(_g(cfg, "hpf", "balance")), "cost_basis": float(_g(cfg, "hpf", "balance")),
        "annual_rate": DEFAULTS["hpf_rate"], "expected_use_years": hpf_years, "note": "",
    }, discount)
    plan.fund_list = compute_funds(fund_in, today)
    plan.stock_list = compute_stocks(stock_in, today)
    plan.dep_list = compute_deposits(deps_raw, discount)

    # —— 养老金与日期
    plan.date_retire = _d(_g(cfg, "global", "date_retire"))
    start, age_m, note = pension_start_info(cfg)
    plan.pension_start, plan.pension_age_months, plan.pension_start_note = start, age_m, note
    auto = bool(_g(cfg, "pension", "auto", default=True))
    plan.pension_mode = "auto" if auto else "manual"

    if plan.pension_ready:
        y_to_pension = (start - today).days / 365.25
        if auto:
            city = _g(cfg, "pension", "city")
            base = (float(_g(cfg, "pension", "city_wage")) if city == OTHER_CITY
                    else float(CITY_BASES[city][0]))     # 城市已由 requirements() 保证在预设里
            age0 = int(_g(cfg, "pension", "retire_age"))
            age_years = (age_m / 12) if age_m is not None else age0
            contrib_end = _d(_g(cfg, "pension", "contrib_end")) or plan.date_retire
            contrib_months = (months_between(today, min(contrib_end, start))
                              if contrib_end else 0)
            nominal = auto_monthly_pension(
                account, acct_rate, y_to_pension, base, growth,
                _g(cfg, "pension", "contrib_years"), _g(cfg, "pension", "contrib_index"),
                age_years, contrib_months=contrib_months,
                base_growth_years=max(start.year - CITY_BASE_YEAR, 0))
            real = nominal / (1 + infl) ** max(y_to_pension, 0)
            plan.pension_detail = {
                "base": base, "city": city, "age_years": age_years, "annuity_months": annuity_months(age_years),
                "contrib_months": contrib_months, "contrib_end": contrib_end,
                "growth_years": max(start.year - CITY_BASE_YEAR, 0), "years_to_pension": y_to_pension,
                "contrib_years": _g(cfg, "pension", "contrib_years"),
                "contrib_index": _g(cfg, "pension", "contrib_index"),
            }
        else:
            nominal = real = float(_g(cfg, "pension", "monthly"))
            plan.pension_detail = {"years_to_pension": y_to_pension}
        plan.pension_nominal, plan.pension_real = nominal, real
        plan.pension = compute_pension({
            "personal_account": account, "cost_basis": account, "monthly_pension": nominal,
            "account_annual_return": acct_rate, "monthly_pension_real": real,
        }, discount, start, life_end, today)
        plan.npv_complete = True
    else:
        # 养老金现值需要领金日期和月领金额；缺失时只保留账户余额，NPV 不含这一项
        plan.pension = {"personal_account": account, "cost_basis": account, "npv": 0.0,
                        "annualized_return": acct_rate, "account_annual_return": acct_rate,
                        "monthly_pension": 0.0, "monthly_pension_real": 0.0}

    plan.rows = build_rows(plan.pension, plan.hpf, plan.ins_list, plan.fund_list,
                           plan.stock_list, plan.dep_list)
    plan.w_return = weighted_avg_return(plan.rows)
    plan.total_mv = sum(r["market_value"] for r in plan.rows)
    plan.total_cost = sum(r["cost_basis"] for r in plan.rows)
    plan.total_npv = sum(r["npv"] for r in plan.rows)
    for r in plan.rows:
        plan.layer_mv[r["layer"]] = plan.layer_mv.get(r["layer"], 0.0) + r["market_value"]
    horizon = (life_end - today).days / 365.25
    plan.eaa_month = eaa(plan.total_npv, discount, horizon) / 12

    plan.snap_now = {
        "pension_hpf": plan.pension["personal_account"] + plan.hpf["balance"],
        "insurance": sum(i["cash_value"] for i in plan.ins_list),
        "investment": sum(f["market_value"] for f in plan.fund_list)
                      + sum(s["market_value"] for s in plan.stock_list),
        "cash": sum(d["balance"] for d in plan.dep_list),
    }
    snap = cfg.get("snapshots") or {}
    b1_d, b2_d = _d(_g(cfg, "global", "date_base_1")), _d(_g(cfg, "global", "date_base_2"))
    keys1 = ("b1_ph", "b1_ins", "b1_inv", "b1_csh")
    keys2 = ("b2_ph", "b2_ins", "b2_inv", "b2_csh")
    names = ("pension_hpf", "insurance", "investment", "cash")
    if all(snap.get(k) is not None for k in keys1) and b1_d:
        plan.snap_b1 = {n: float(snap[k]) for n, k in zip(names, keys1)}
    if all(snap.get(k) is not None for k in keys2) and b2_d:
        plan.snap_b2 = {n: float(snap[k]) for n, k in zip(names, keys2)}
    plan.base_dates = (b1_d, b2_d)

    if plan.date_retire:
        plan.years_to_retire = max((plan.date_retire - today).days / 365.25, 0.0)
        plan.snap_ret = retirement_projection(plan.snap_now, invest, ins_in, plan.years_to_retire)
        plan.deflator = (1 + infl) ** plan.years_to_retire

    if not plan.retire_ready:
        return plan

    # —— 退休测算：所有情景、压力测试共用同一个两阶段目标
    expense = float(_g(cfg, "sim", "retire_expense_mo"))
    income = float(_g(cfg, "sim", "monthly_income"))
    spend = float(_g(cfg, "sim", "monthly_expense"))
    semi = _g(cfg, "sim", "semi_income")
    bridge = months_between(plan.date_retire, start)
    plan.target = two_phase_target(expense, bridge, plan.pension_real)
    plan.ref4 = expense * 12 / 0.04
    plan.retire_expense = expense

    sp = _sim_params(plan.pension, plan.hpf, plan.ins_list, plan.fund_list, plan.stock_list,
                     plan.dep_list, income, spend, expense, invest, today, plan.date_retire,
                     inflation=infl)
    cash_now = sum(d["balance"] for d in plan.dep_list)
    liq_now = cash_now + plan.snap_now["investment"]

    def view(key, name, sched):
        r = run_scenario(name, sched, sp)
        target = plan.target["total"]
        margin = r["total_real"] - target
        liquid_ok = None if bridge == 0 else r["inv_cash_real"] >= plan.target["bridge_cost"]
        return {
            "key": key, "name": name, "available": True,
            "nominal": r["total_2036"], "real": r["total_real"], "target": target,
            "margin": margin, "margin_pct": margin_ratio(margin, target), "meets": margin >= 0,
            "liquid_real": r["inv_cash_real"], "liquid_ok": liquid_ok,
            "liquid_short": max(0.0, plan.target["bridge_cost"] - r["inv_cash_real"]),
            "cash_depl": r["cash_depl"],
            "liq_now": liq_now, "liq_months": int(liq_now / spend) if spend else None,
            "ref4_diff": r["total_real"] - plan.ref4,
        }

    plan.scenarios.append(view("continue", "继续工作", []))
    plan.scenarios.append(view(
        "interrupt", f"收入中断 {int(interrupt)} 个月",
        [(today, today + relativedelta(months=int(interrupt)), 0)]))
    if semi is None:
        plan.scenarios.append({"key": "semi", "name": "半退休至退休", "available": False,
                               "note": "未填写半退休月收入，暂不计算这一情景"})
    else:
        plan.scenarios.append(view("semi", "半退休至退休",
                                   [(today, plan.date_retire, float(semi))]))

    for label, kw, note in STRESS_CASES:
        t = run_stress(label, sp, **kw)
        tgt = two_phase_target(expense, bridge, plan.pension_real, kw.get("pension_mult", 1.0))
        margin = t["total_real"] - tgt["total"]
        plan.stress.append({
            "label": label, "note": note, "partial": note.startswith("局部"),
            "real": t["total_real"], "target": tgt["total"], "margin": margin,
            "margin_pct": margin_ratio(margin, tgt["total"]), "meets": margin >= 0,
            "liquid_real": t["inv_cash_real"],
            "liquid_ok": None if bridge == 0 else t["inv_cash_real"] >= tgt["bridge_cost"],
            "old_coverage": t["coverage"], "old_target": t["target_adj"],
        })

    # —— 补缺口路径（沿用原有算法，仅对「继续工作」情景）
    months_left = max(months_between(today, plan.date_retire), 1)
    r_mo = (1 + invest) ** (1 / 12) - 1
    head = plan.scenarios[0]
    paths = {"months_left": months_left}
    if not head["meets"]:
        gap_real = -head["margin"]
        gap_nom = gap_real * plan.deflator     # 储蓄与投资增长是名义金额
        extra = gap_nom * r_mo / ((1 + r_mo) ** months_left - 1) if r_mo > 0 else gap_nom / months_left
        paths["gap_real"], paths["gap_nominal"] = gap_real, gap_nom
        paths["extra_mo"], paths["extra_feasible"] = extra, extra <= income
        saving = income - spend
        paths["saving_mo"] = saving
        if saving > 0 and r_mo > 0:
            growth_mo = plan.snap_now["investment"] * r_mo + cash_now * r_mo + saving
            years = (int(gap_nom / growth_mo) / 12) if growth_mo > 0 else 9999
            paths["delay_years"] = years if years < 20 else None
        else:
            paths["delay_years"] = None
        semi_view = plan.scenarios[2]
        if semi_view.get("available") and not semi_view["meets"]:
            need = (-semi_view["margin"]) * plan.deflator / months_left
            paths["semi_required"] = float(semi) + need
            paths["semi_feasible"] = paths["semi_required"] <= income * 1.5
    plan.paths = paths
    return plan


def failed_plan(cfg, exc, today=None):
    """测算意外失败时返回的结果：不给任何数字，但页面仍能渲染，用户还能改输入。"""
    return Plan(today=today or date.today(), issues=collect_issues(cfg),
                error=f"{type(exc).__name__}: {exc}")


# ═════════════════════════════════════════════════════════════════════════
# 配置结构（与导出格式一致；None 表示"未填写"，0 表示"明确填了 0"）
# ═════════════════════════════════════════════════════════════════════════
def empty_cfg():
    return {"global": {}, "pension": {}, "hpf": {}, "insurance": None,
            "funds_dca": None, "stocks": None, "deposits": None,
            "snapshots": {}, "sim": {}}


def cfg_from_clean(clean):
    """validate_config 的结果 → 完整配置。文件里没有的项保持 None，不用默认值冒充。"""
    cfg = empty_cfg()
    for sec in ("global", "pension", "hpf", "snapshots", "sim"):
        cfg[sec] = dict(clean.get(sec) or {})
    if "insurance" in clean:
        cfg["insurance"] = [dict(p) for p in clean["insurance"]]
    for key in ("funds_dca", "stocks", "deposits"):
        if key in clean:
            cfg[key] = clean[key]
    return cfg


def cfg_for_export(cfg):
    """去掉空值之外原样导出；None 写成 null，重新导入后仍是"未填写"。"""
    out = {}
    for sec in ("global", "pension", "hpf", "snapshots", "sim"):
        out[sec] = dict(cfg.get(sec) or {})
    out["insurance"] = [dict(p) for p in cfg["insurance"]] if cfg.get("insurance") is not None else None
    for key in ("funds_dca", "stocks", "deposits"):
        out[key] = cfg.get(key)
    return out
