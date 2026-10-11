"""
个人资产收益整合表 — Streamlit Web App
运行：streamlit run app.py

页面按用户任务组织：概览｜资产｜情景｜数据与假设。
  state.py   配置状态（一份规范配置，所有页面共用）
  calc.py    共享测算（概览与情景读同一份结果）
  views/     各页渲染
  shell.py   导航与侧边栏
计算公式仍在 finance_engine.py。
"""
import shell

shell.main()
