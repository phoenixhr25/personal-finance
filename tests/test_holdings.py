"""持仓表格 ⇄ 文本：不丢行、不改语义、没填完的行不写入。"""
from datetime import date

import pandas as pd
import pytest

import calc
import holdings as H

FUNDS = "270023,3250.58,17111.57,20139.62\n016533,8228.15,15052.45,17677.36"
STOCKS = "600036,1500,35.0,2023-06-01,40.0\n510300,20000,4.0,2023-06-01"
DEPOSITS = "示例银行A,活期,150000,0.002\n示例银行B,定期,100000,0.020\n现金,,500"

PARSERS = {"funds_dca": calc.parse_fund_dca, "stocks": calc.parse_stocks, "deposits": calc.parse_deposits}


@pytest.mark.parametrize("kind,text", [("funds_dca", FUNDS), ("stocks", STOCKS), ("deposits", DEPOSITS)])
def test_roundtrip_keeps_what_the_calc_parser_sees(kind, text):
    rows, bad = H.rows_from_text(kind, text)
    assert bad == []
    again = H.text_from_rows(kind, rows)
    assert PARSERS[kind](again)[0] == PARSERS[kind](text)[0]


@pytest.mark.parametrize("kind,text", [("funds_dca", FUNDS), ("stocks", STOCKS), ("deposits", DEPOSITS)])
def test_dataframe_roundtrip(kind, text):
    rows, _ = H.rows_from_text(kind, text)
    df = H.df_from_rows(kind, rows)
    assert H.rows_from_df(kind, df) == rows


def test_chinese_commas_and_spaces_are_accepted():
    rows, bad = H.rows_from_text("funds_dca", "270023， 3250.58 ，17111.57，20139.62")
    assert len(rows) == 1 and not bad and rows[0]["shares"] == 3250.58


def test_bad_lines_are_preserved_not_dropped():
    text = FUNDS + "\n坏行\n000001,x,1,2"
    rows, bad = H.rows_from_text("funds_dca", text)
    assert len(rows) == 2 and bad == ["坏行", "000001,x,1,2"]
    out = H.text_from_rows("funds_dca", rows, bad)
    assert "坏行" in out and "000001,x,1,2" in out


def test_incomplete_rows_are_not_written():
    df = pd.DataFrame({"代码": ["600036", "000001"], "股数 / 份额": [100.0, None],
                       "成本价": [35.0, 10.0], "买入日期": [date(2023, 1, 1), None],
                       "当前价（可选）": [None, None]})
    new_text, incomplete, changed, _ = H.sync("stocks", None, df)
    assert new_text == "600036,100,35,2023-01-01"
    assert incomplete == 1 and changed


def test_empty_table_means_unfilled_not_zero():
    df = H.df_from_rows("deposits", [])
    new_text, incomplete, changed, _ = H.sync("deposits", None, df)
    assert new_text is None and incomplete == 0 and changed is False


def test_declared_none_text_stays_unchanged_for_empty_table():
    new_text, _, changed, _ = H.sync("deposits", "", H.df_from_rows("deposits", []))
    assert changed is False


def test_unedited_table_does_not_rewrite_config_text():
    text = "270023, 3250.58, 17111.57, 20139.62"          # 带空格的原始写法
    rows, _ = H.rows_from_text("funds_dca", text)
    _, _, changed, _ = H.sync("funds_dca", text, H.df_from_rows("funds_dca", rows))
    assert changed is False                               # 只看数据是否变化，不因格式不同而重写


def test_edit_changes_text_and_reverts():
    rows, _ = H.rows_from_text("funds_dca", FUNDS)
    df = H.df_from_rows("funds_dca", rows)
    df.iloc[0, 1] = 4000.0
    new_text, _, changed, _ = H.sync("funds_dca", FUNDS, df)
    assert changed and new_text.startswith("270023,4000,17111.57,20139.62")
    df.iloc[0, 1] = 3250.58
    _, _, changed_back, _ = H.sync("funds_dca", new_text, df)
    assert changed_back                                   # 与已写入的"4000"不同，需要写回


def test_zero_or_negative_shares_are_incomplete_for_funds():
    assert not H.is_complete("funds_dca", {"code": "1", "shares": 0.0, "cost": 1.0, "value": 1.0})


def test_deposit_type_and_rate_are_optional():
    assert H.is_complete("deposits", {"bank": "招行", "type": "", "balance": 100.0, "rate": None})
    assert H.text_from_rows("deposits", [{"bank": "招行", "type": "", "balance": 100.0, "rate": None}]) \
        == "招行,,100"
    assert calc.parse_deposits("招行,,100")[0][0]["balance"] == 100.0
