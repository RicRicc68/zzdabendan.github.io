import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, timezone


def plot_equity(result, save_path="equity_curve.png"):
    timestamps, equity = result.equity_curve()
    dates = [datetime.fromtimestamp(ts, tz=timezone.utc) for ts in timestamps]

    # Ricostruisco il picco progressivo per ombreggiare i drawdown
    peaks, peak = [], equity[0]
    for v in equity:
        peak = max(peak, v)
        peaks.append(peak)

    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(12, 8), sharex=True,
        gridspec_kw={"height_ratios": [3, 1]}
    )

    # --- Pannello 1: equity curve ---
    ax1.plot(dates, equity, color="#2e7d32", linewidth=1.8, label="Capitale")
    ax1.plot(dates, peaks, color="#9e9e9e", linewidth=0.8,
             linestyle="--", label="Picco storico")
    ax1.fill_between(dates, equity, peaks, where=[e < p for e, p in zip(equity, peaks)],
                     color="#ef5350", alpha=0.25, label="Drawdown")
    ax1.axhline(result.starting_bankroll, color="#1565c0",
                linewidth=0.8, linestyle=":", label="Capitale iniziale")
    ax1.set_ylabel("Capitale (USD)")
    ax1.set_title("Equity Curve — Copy-Trading Bot Polymarket")
    ax1.legend(loc="upper left", fontsize=9)
    ax1.grid(alpha=0.3)

    # --- Pannello 2: drawdown percentuale nel tempo ---
    dd_series = [(e - p) / p * 100 if p else 0 for e, p in zip(equity, peaks)]
    ax2.fill_between(dates, dd_series, 0, color="#ef5350", alpha=0.5)
    ax2.set_ylabel("Drawdown (%)")
    ax2.set_xlabel("Data")
    ax2.grid(alpha=0.3)

    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m"))
    fig.autofmt_xdate()
    plt.tight_layout()
    plt.savefig(save_path, dpi=120)
    print(f"[plot] grafico salvato in {save_path}")
    plt.show()