"""
个人资产收益整合表 — 参数配置示例
====================================
使用方法：
1. 复制此文件为 config.py
2. 按注释填入你的真实数据
3. 在 notebook 第一格 import config 后即可运行
（或直接在 notebook 的参数格里填写）
"""

from datetime import date

# ─────────────────────────────────────────────
# 一、全局参数
# ─────────────────────────────────────────────

DISCOUNT_RATE    = 0.03           # 折现率（国债基准，一般取 3%）
DATE_BASE_1      = date(2020, 1, 1)  # 基期起始——你开始认真积累资产的时间
DATE_BASE_2      = date(2023, 1, 1)  # 中间参考节点（可选，用于趋势对比）
DATE_RETIRE      = date(2040, 1, 1)  # 预计退休日期
DATE_LIFE_END    = date(2080, 1, 1)  # 预期寿命终止日
PROJ_INVEST_RATE = 0.05              # 退休推算用投资层预期年化（保守 3-4%，中性 5-6%，激进 7-8%）


# ─────────────────────────────────────────────
# 二、社会保障层
# ─────────────────────────────────────────────

# 养老保险（数据来源：社保 App）
PENSION_PARAMS = {
    'personal_account':     100_000,  # 个人账户余额（元）
    'cost_basis':           100_000,  # 历史累计个人缴纳总额
    'monthly_pension':        3_000,  # 预计退休后月领金额
    'account_annual_return':  0.055,  # 个人账户记账利率（官方约 5.5%）
}

# 住房公积金（数据来源：公积金 App）
HPF_PARAMS = {
    'balance':              80_000,   # 当前余额（个人缴纳部分）
    'cost_basis':           80_000,   # 历史累计个人缴纳
    'annual_rate':           0.025,   # 年化利率（现行基准 2.5%）
    'expected_use_years':    10.0,    # 预计几年后动用（买房/退休）
    'note': '预计用于首付',
}


# ─────────────────────────────────────────────
# 三、保险保障层
# ─────────────────────────────────────────────

# 储蓄险保单列表（数据来源：保单合同 / 保险 App）
# 每张保单一个字典，复制追加即可
INSURANCE_LIST = [
    {
        'name':              'XX 年金保险',
        'cash_value':         50_000,   # 当前现金价值（退保可得）
        'cost_basis':         50_000,   # 已缴保费合计
        'annual_premium':          0,   # 年缴保费（已缴完填 0）
        'premium_years_left':      0,   # 还需缴纳年数
        'maturity_value':     50_000,   # 满期/减保可领金额
        'years_to_maturity':       0,   # 距满期年数（已到期填 0）
        'policy_irr':          0.030,   # 保单 IRR（投保书/产品说明书上有）
    },
    {
        'name':              'XX 终身寿险',
        'cash_value':         30_000,
        'cost_basis':         30_000,
        'annual_premium':     10_000,
        'premium_years_left':      5,
        'maturity_value':     80_000,
        'years_to_maturity':       5,
        'policy_irr':          0.028,
    },
]


# ─────────────────────────────────────────────
# 四、投资层
# ─────────────────────────────────────────────

# 基金持仓（名称自动从天天基金接口获取，无需手填）
# cost_nav  → 券商 App「持仓成本」（移动加权均价）
# shares    → 持有份额
# buy_date  → 首次建仓日（近似值，用于年化收益率估算）
# manual_nav→ 手动覆盖净值（None = 自动获取）
FUND_INPUT = [
    {'code': '000001', 'shares': 10000.00, 'cost_nav': 1.5000, 'buy_date': date(2023, 1, 1), 'manual_nav': None},
    {'code': '110022', 'shares':  5000.00, 'cost_nav': 2.1000, 'buy_date': date(2023, 6, 1), 'manual_nav': None},
    {'code': '270023', 'shares':  3000.00, 'cost_nav': 4.5000, 'buy_date': date(2024, 1, 1), 'manual_nav': None},
    # 继续添加...
]

# A股/ETF 持仓（名称自动从新浪行情获取）
# cost_price → 券商 App「持仓成本」
# manual_price → 手动覆盖价格（None = 自动获取）
STOCK_INPUT = [
    {'code': '600036', 'shares': 100,  'cost_price': 35.00, 'buy_date': date(2023, 1, 1), 'manual_price': None},
    {'code': '000001', 'shares': 200,  'cost_price': 12.50, 'buy_date': date(2023, 6, 1), 'manual_price': None},
    # 场内 ETF 填这里（如沪深300 ETF 510300）
    # {'code': '510300', 'shares': 1000, 'cost_price': 4.20, 'buy_date': date(2024,1,1), 'manual_price': None},
]


# ─────────────────────────────────────────────
# 五、现金等价物层
# ─────────────────────────────────────────────

# 银行存款 / 货币基金
# term_years → 活期填 0，定期填年限
DEPOSIT_LIST = [
    {'type': '活期', 'bank': '工商银行',    'balance': 50_000, 'rate': 0.002, 'term_years': 0},
    {'type': '活期', 'bank': '支付宝余额宝', 'balance': 20_000, 'rate': 0.018, 'term_years': 0},
    {'type': '定期', 'bank': '招商银行',    'balance': 50_000, 'rate': 0.020, 'term_years': 1},
]


# ─────────────────────────────────────────────
# 六、四期对比历史快照（估计值即可）
# ─────────────────────────────────────────────

SNAP_BASE1_DATA = {
    'pension_hpf':  50_000,   # 养老+公积金合计
    'insurance':    10_000,   # 储蓄险现金价值
    'investment':   30_000,   # 基金+A股合计
    'cash':         50_000,   # 银行存款合计
}

SNAP_BASE2_DATA = {
    'pension_hpf': 120_000,
    'insurance':    30_000,
    'investment':  100_000,
    'cash':        100_000,
}
