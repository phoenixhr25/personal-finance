"""行情缓存：不联网，替换 _sina_quote 和时钟。"""
import market_api as ma


def _fake_quotes(prices):
    calls = []

    def quote(codes):
        calls.append(list(codes))
        return {c: {"name": c, "price": prices[c], "change_pct": 0} for c in codes if c in prices}
    return quote, calls


def test_cache_hit_within_ttl(monkeypatch):
    ma._cache.clear()
    quote, calls = _fake_quotes({"600036": 30.0})
    monkeypatch.setattr(ma, "_sina_quote", quote)
    monkeypatch.setattr(ma.time, "monotonic", lambda: 1000.0)
    assert ma.get_price("600036")["price"] == 30.0
    assert ma.get_price("600036")["price"] == 30.0
    assert len(calls) == 1


def test_cache_refreshes_after_ttl(monkeypatch):
    ma._cache.clear()
    prices = {"600036": 30.0}
    quote, calls = _fake_quotes(prices)
    monkeypatch.setattr(ma, "_sina_quote", quote)
    clock = {"t": 1000.0}
    monkeypatch.setattr(ma.time, "monotonic", lambda: clock["t"])
    ma.get_price("600036")
    prices["600036"] = 31.5
    clock["t"] += ma.CACHE_TTL_SECONDS + 1
    assert ma.get_price("600036")["price"] == 31.5
    assert len(calls) == 2


def test_failed_lookup_cached_briefly_then_retried(monkeypatch):
    ma._cache.clear()
    quote, calls = _fake_quotes({})
    monkeypatch.setattr(ma, "_sina_quote", quote)
    clock = {"t": 1000.0}
    monkeypatch.setattr(ma.time, "monotonic", lambda: clock["t"])
    assert ma.get_price("000000") == {}
    assert ma.get_price("000000") == {}
    assert len(calls) == 1            # 失败短暂缓存，不会每次重算都等超时
    clock["t"] += ma.NEGATIVE_TTL_SECONDS + 1
    assert ma.get_price("000000") == {}
    assert len(calls) == 2            # 过期后重试


def test_fund_lookup_cached(monkeypatch):
    ma._fund_cache.clear()
    n = {"c": 0}

    def fetch(code):
        n["c"] += 1
        return {"name": code, "price": 1.5, "change_pct": 0}
    monkeypatch.setattr(ma, "_fetch_fund_price", fetch)
    monkeypatch.setattr(ma.time, "monotonic", lambda: 50.0)
    ma.get_fund_price("000001"); ma.get_fund_price("000001")
    assert n["c"] == 1


def test_fetch_uses_injected_lookup_and_skips_manual():
    seen = []

    def lookup(code):
        seen.append(code)
        return {"name": "x", "price": 2.0, "change_pct": 0.1}
    out = ma.fetch_fund_prices([{"code": "A"}, {"code": "B", "manual_nav": 3.0}], lookup=lookup)
    assert seen == ["A"]
    assert [o["current_nav"] for o in out] == [2.0, 3.0]
