"""持仓的两种录入方式：表格 ⇄ 文本（纯函数，不依赖 Streamlit）。

配置里始终存文本，导出格式不变；表格只是文本的另一种视图。
- 无法识别的文本行原样保留，不会因为在表格里编辑而被悄悄丢掉；
- 表格里没填完的行不写入文本，界面上提示；
- 空表格 = 未填写，需要勾选「暂无」才算明确没有。
"""
from datetime import date, datetime

import pandas as pd

# 每类持仓的列：(键, 表头, 类型, 必填)
SPECS = {
    "funds_dca": [("code", "代码", "text", True), ("shares", "份额", "number", True),
                  ("cost", "持有成本（总额，元）", "number", True),
                  ("value", "当前市值（总额，元）", "number", True)],
    "stocks": [("code", "代码", "text", True), ("shares", "股数 / 份额", "number", True),
               ("cost_price", "成本价", "number", True), ("buy_date", "买入日期", "date", True),
               ("price", "当前价（可选）", "number", False)],
    "deposits": [("bank", "银行", "text", True), ("type", "类型", "text", False),
                 ("balance", "余额（元）", "number", True), ("rate", "年化利率（可选）", "number", False)],
}


def _num(x):
    if x is None or (isinstance(x, float) and x != x):
        return None
    return ("%.10f" % float(x)).rstrip("0").rstrip(".") or "0"


def _split(text):
    for raw in (text or "").splitlines():
        line = raw.replace("，", ",").strip()
        if line:
            yield raw.strip(), [p.strip() for p in line.split(",")]


def rows_from_text(kind, text):
    """文本 → (行列表, 无法识别的原始行)。识别规则与 calc.parse_* 一致。"""
    rows, bad = [], []
    for raw, p in _split(text):
        try:
            if kind == "funds_dca":
                if len(p) < 4:
                    raise ValueError
                row = {"code": p[0], "shares": float(p[1]), "cost": float(p[2]), "value": float(p[3])}
                if row["shares"] <= 0:
                    raise ValueError
            elif kind == "stocks":
                if len(p) < 4:
                    raise ValueError
                row = {"code": p[0], "shares": float(p[1]), "cost_price": float(p[2]),
                       "buy_date": datetime.strptime(p[3], "%Y-%m-%d").date(),
                       "price": float(p[4]) if len(p) > 4 and p[4] else None}
            else:
                if len(p) < 3:
                    raise ValueError
                row = {"bank": p[0], "type": p[1], "balance": float(p[2]),
                       "rate": float(p[3]) if len(p) > 3 and p[3] else None}
        except ValueError:
            bad.append(raw)
            continue
        rows.append(row)
    return rows, bad


def is_complete(kind, row):
    for key, _, typ, required in SPECS[kind]:
        v = row.get(key)
        empty = v is None or (isinstance(v, float) and v != v) or (isinstance(v, str) and not v.strip())
        if required and empty:
            return False
    if kind == "funds_dca" and not (row.get("shares") or 0) > 0:
        return False
    return True


def text_from_rows(kind, rows, bad=()):
    """行 → 文本。只写入填完整的行，并把无法识别的原始行附在后面。"""
    lines = []
    for r in rows:
        if not is_complete(kind, r):
            continue
        if kind == "funds_dca":
            parts = [r["code"].strip(), _num(r["shares"]), _num(r["cost"]), _num(r["value"])]
        elif kind == "stocks":
            parts = [r["code"].strip(), _num(r["shares"]), _num(r["cost_price"]), r["buy_date"].isoformat()]
            if _num(r.get("price")) is not None:
                parts.append(_num(r["price"]))
        else:
            parts = [r["bank"].strip(), (r.get("type") or "").strip(), _num(r["balance"])]
            if _num(r.get("rate")) is not None:
                parts.append(_num(r["rate"]))
        lines.append(",".join(parts))
    return "\n".join(lines + [b for b in bad])


# ── DataFrame 视图 ───────────────────────────────────────────────────────
def df_from_rows(kind, rows):
    cols = {}
    for key, title, typ, _ in SPECS[kind]:
        vals = [r.get(key) for r in rows]
        if typ == "number":
            cols[title] = pd.Series(vals, dtype="float64")
        elif typ == "date":
            cols[title] = pd.Series(vals, dtype="object")
        else:
            cols[title] = pd.Series([v or "" for v in vals], dtype="object")
    return pd.DataFrame(cols)


def _cell(v, typ):
    if v is None or (isinstance(v, float) and v != v) or v is pd.NaT:
        return None
    if typ == "date":
        if isinstance(v, str):
            try:
                return date.fromisoformat(v[:10])
            except ValueError:
                return None
        return v.date() if hasattr(v, "date") else v
    if typ == "number":
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    return str(v)


def rows_from_df(kind, df):
    rows = []
    for rec in df.to_dict("records"):
        row = {key: _cell(rec.get(title), typ) for key, title, typ, _ in SPECS[kind]}
        if any(v not in (None, "") for v in row.values()):
            rows.append(row)
    return rows


def sync(kind, cfg_text, edited_df):
    """表格编辑结果 → 应写入配置的文本。

    返回 (新文本或 None, 未填完的行数, 是否与当前配置不同, 无法识别的行)。
    新文本为 None 表示表格里没有任何完整的行；是否算"明确没有"由界面的「暂无」决定。
    """
    cur_rows, bad = rows_from_text(kind, cfg_text)
    new_rows = rows_from_df(kind, edited_df)
    complete = [r for r in new_rows if is_complete(kind, r)]
    new_text = text_from_rows(kind, complete, bad)
    changed = new_text != text_from_rows(kind, cur_rows, bad)
    return (new_text or None), len(new_rows) - len(complete), changed, bad
