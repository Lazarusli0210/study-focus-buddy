"""
charts.py — builds the 7-day history chart shown in the History window.

Uses matplotlib's object-oriented Figure class (not pyplot) because the figure is embedded
inside a tkinter window; pyplot would open its own extra window.
Embedding approach from the matplotlib docs, "Embed in Tk":
https://matplotlib.org/stable/gallery/user_interfaces/embedding_in_tk_sgskip.html
The chart design itself (focus bars + distraction line on a second axis) is original.
"""

from matplotlib.figure import Figure

FOCUS_COLOUR = "#3b7a57"        # calm green for focused minutes
DISTRACTION_COLOUR = "#c2553d"  # warm red for distractions


def build_history_figure(daily_totals) -> Figure:
    """Return a Figure from SessionLog.daily_totals() output: [(day, minutes, distractions)]."""
    labels = [d.strftime("%a\n%d") for d, _, _ in daily_totals]   # e.g. "Mon\n26"
    minutes = [m for _, m, _ in daily_totals]
    distractions = [n for _, _, n in daily_totals]

    fig = Figure(figsize=(6.4, 3.4), dpi=100)
    ax = fig.add_subplot(111)
    ax.bar(labels, minutes, color=FOCUS_COLOUR, label="Focused minutes")
    ax.set_ylabel("Focused minutes")
    ax.set_ylim(bottom=0)
    ax.spines[["top"]].set_visible(False)

    # Second y-axis sharing the same x-axis, so both measures fit on one chart.
    ax2 = ax.twinx()
    ax2.plot(labels, distractions, color=DISTRACTION_COLOUR, marker="o", label="Distractions")
    ax2.set_ylabel("Distractions + pauses")
    ax2.set_ylim(bottom=0, top=max(distractions + [3]) + 1)
    ax2.spines[["top"]].set_visible(False)

    ax.set_title("Last 7 days")
    # Merge the two legends into one box.
    handles = ax.get_legend_handles_labels()[0] + ax2.get_legend_handles_labels()[0]
    ax.legend(handles, [h.get_label() for h in handles], loc="upper left", frameon=False)
    fig.tight_layout()
    return fig
