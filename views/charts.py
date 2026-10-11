"""图表（matplotlib）。两张图上下排列，窄屏下也能看。"""
import glob

import matplotlib
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

NAVY, TEAL, AMBER, GRAY, LIGHT = "#1F3A5F", "#2A8C8C", "#C58A2B", "#B8C4D2", "#F5F7FA"
PIE_COLORS = [NAVY, TEAL, "#8AB3C4", AMBER, "#7B8FA1", "#9DBE9B"]


def _setup_font():
    fm = matplotlib.font_manager
    known = {f.name for f in fm.fontManager.ttflist}
    for name in ("PingFang SC", "PingFang HK", "Heiti TC", "STHeiti", "SimHei",
                 "Noto Sans CJK SC", "Noto Sans SC", "WenQuanYi Micro Hei"):
        if name in known:
            matplotlib.rcParams["font.family"] = name
            break
    else:
        for pat in ("/usr/share/fonts/**/*CJK*", "/usr/share/fonts/**/*Noto*SC*",
                    "/usr/share/fonts/**/*WenQuanYi*"):
            hits = glob.glob(pat, recursive=True)
            if hits:
                fm.fontManager.addfont(hits[0])
                matplotlib.rcParams["font.family"] = fm.FontProperties(fname=hits[0]).get_name()
                break
    matplotlib.rcParams["axes.unicode_minus"] = False


_setup_font()


def _fmt_wan(x, _=None):
    return f"{x / 1e4:,.0f} 万"


def donut(layer_mv):
    """四层资产结构。合计为 0 时返回 None。"""
    names = list(layer_mv)
    vals = [layer_mv[n] for n in names]
    total = sum(vals)
    if total <= 0:
        return None
    fig, ax = plt.subplots(figsize=(6, 4.3), facecolor="white")
    wedges, _, autotexts = ax.pie(
        vals, startangle=90, counterclock=False, colors=PIE_COLORS[:len(vals)],
        autopct=lambda p: f"{p:.0f}%" if p >= 4 else "", pctdistance=0.79,
        wedgeprops={"width": 0.38, "edgecolor": "white", "linewidth": 3})
    for t in autotexts:
        t.set_color("white"); t.set_fontsize(10); t.set_fontweight("bold")
    ax.text(0, 0.07, "总资产", ha="center", color="#6B778C", fontsize=10)
    ax.text(0, -0.1, f"¥{total / 1e4:,.1f} 万", ha="center", color=NAVY, fontsize=15, fontweight="bold")
    ax.legend(wedges, [f"{n}  ¥{v:,.0f}" for n, v in zip(names, vals)], loc="upper center",
              bbox_to_anchor=(0.5, 0.02), ncol=1, frameon=False, fontsize=9.5)
    fig.tight_layout()
    return fig


def bars(labels, values, note_last=None):
    """总资产变化：历史快照、当前、退休推算（名义金额）。"""
    fig, ax = plt.subplots(figsize=(6, 3.8), facecolor="white")
    colors = [GRAY] * len(values)
    colors[-1] = TEAL
    rects = ax.bar(labels, values, width=0.55, color=colors, edgecolor="none")
    top = max(values) if values and max(values) > 0 else 1
    ax.set_ylim(0, top * 1.2)
    for r, v in zip(rects, values):
        ax.text(r.get_x() + r.get_width() / 2, v + top * 0.02, f"¥{v / 1e4:,.1f} 万",
                ha="center", va="bottom", fontsize=9, fontweight="bold", color=NAVY)
    ax.yaxis.set_major_formatter(FuncFormatter(_fmt_wan))
    ax.grid(axis="y", color="#E3E8EE", linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(length=0, colors="#5E6C84", labelsize=9)
    for sp in ax.spines.values():
        sp.set_visible(False)
    fig.tight_layout()
    return fig
