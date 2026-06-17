"""行情接口：A股（新浪）+ 基金（天天基金 → 新浪备选）"""
import re
import json
import requests

_session = requests.Session()
_session.trust_env = False
_PROXIES = {"http": None, "https": None}
_HEADERS_SINA = {
    "Referer": "https://finance.sina.com.cn",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
}
_cache: dict = {}


def _sina_quote(codes: list) -> dict:
    prefixed = [("sh" if c.startswith(("6", "5")) else "sz") + c for c in codes]
    url = "https://hq.sinajs.cn/list=" + ",".join(prefixed)
    try:
        r = _session.get(url, headers=_HEADERS_SINA, timeout=8, proxies=_PROXIES)
        r.encoding = "gbk"
    except Exception:
        return {}

    result = {}
    for line in r.text.strip().splitlines():
        if '="' not in line:
            continue
        code  = line.split('"')[0].rstrip("=")[-6:]   # 修复：rstrip('=') 再取 [-6:]
        inner = line.split('"')[1]
        if not inner:
            continue
        parts = inner.split(",")
        if len(parts) < 7:
            continue
        name   = parts[0]
        yclose = float(parts[1]) if parts[1] else 0
        price  = float(parts[3]) if parts[3] else 0
        if price == 0:
            price = float(parts[6]) if parts[6] else 0
        chg = round((price - yclose) / yclose * 100, 2) if yclose else 0
        result[code] = {"name": name, "price": price, "change_pct": chg}
    return result


def get_price(code: str) -> dict:
    if code not in _cache:
        _cache.update(_sina_quote([code]))
    return _cache.get(code, {})


def get_fund_price(code: str) -> dict:
    """天天基金优先（防止基金代码与同名A股冲突），Sina 备选（场内 ETF）。"""
    # 1. 天天基金
    try:
        url = f"https://fundgz.1234567.com.cn/js/{code}.js"
        r = _session.get(url, headers={"Referer": "https://fund.eastmoney.com/"},
                         timeout=8, proxies=_PROXIES)
        m = re.search(r"\((.+)\)", r.text)
        if m:
            d = json.loads(m.group(1))
            price = float(d.get("gsz") or d.get("dwjz", 0))
            chg   = float(d.get("gszzl", 0))
            label = "盘中估值" if d.get("gsz") else "T-1净值"
            return {"name": d.get("name", code), "price": price,
                    "change_pct": chg, "type": f"开放式基金({label})"}
    except Exception:
        pass

    # 2. Sina 备选（场内 ETF）
    try:
        info = _sina_quote([code]).get(code, {})
        if info and info.get("price", 0) > 0:
            info["type"] = "ETF"
            return info
    except Exception:
        pass

    return {}


def fetch_fund_prices(fund_input: list) -> list:
    result = []
    for f in fund_input:
        info = get_fund_price(f["code"])
        result.append({**f,
                       "current_nav": info.get("price") or f.get("manual_nav"),
                       "name": info.get("name") or f["code"],
                       "change_pct": info.get("change_pct"),
                       "type": info.get("type", "手动录入")})
    return result


def fetch_stock_prices(stock_input: list) -> list:
    result = []
    for s in stock_input:
        info = get_price(s["code"])
        result.append({**s,
                       "current_price": info.get("price") or s.get("manual_price"),
                       "name": info.get("name") or s["code"],
                       "change_pct": info.get("change_pct")})
    return result
