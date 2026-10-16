# 参与说明

这是一个个人资产整合与简化退休测算的小工具。欢迎提问题、建议口径，也欢迎提交修改。

## 先看这三条

1. **不要提交真实的个人数据。** 配置文件、持仓、余额、出生年月、含这些内容的截图，都不要出现在 Issue、PR、测试和示例里。测试和示例只用虚构数据（见 `examples/demo_config.json`）。
2. **改计算口径要写依据。** 政策文件、公布的数据来源，或者说明为什么选这种算法；并补测试。
3. **推送到 `main` 即上线。** 公开页面会自动重新部署，所以改动先在分支上做，本地跑通再合并。

## 本地运行

```bash
pip install -r requirements.txt
streamlit run app.py
```

需要 Streamlit 1.36 及以上（用到 `st.navigation`）。

## 运行测试

```bash
python -m pytest -q
```

测试分三类：

| 文件 | 内容 |
|---|---|
| `tests/test_finance_engine.py` | 引擎公式：现值、年化、养老金、情景、压力测试 |
| `tests/test_calc.py` | 共享测算：与改版前基线对账、目标口径统一、缺失项、边界情况 |
| `tests/test_app_flow.py` | 页面状态流：导入导出、跨页一致、分步填写 |

## 代码结构

| 文件 | 作用 |
|---|---|
| `app.py` | 入口 |
| `shell.py` | 导航与侧边栏 |
| `state.py` | 配置状态（一份数据，所有页面共用） |
| `calc.py` | 共享测算（概览与情景读同一份结果） |
| `holdings.py` | 持仓的表格与文本互转 |
| `views/` | 各页渲染 |
| `finance_engine.py` | 计算公式 |
| `config_io.py` | 配置文件校验与版本迁移 |
| `market_api.py` | 行情接口 |

## 设计原则

能用一张表解决的，不建系统。加功能前先问：这是整合报表需要的，还是想多了？详见 [NOTES.md](NOTES.md)。
