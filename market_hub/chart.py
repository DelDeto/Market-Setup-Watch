from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle


CHART_DIR = Path("output/charts")
CHART_BARS = 120


def _zone_bounds(zone):
    zone = zone or {}
    lower = zone.get("lower")
    upper = zone.get("upper")
    if lower is None or upper is None:
        return None
    lower = float(lower)
    upper = float(upper)
    if lower > upper:
        lower, upper = upper, lower
    return lower, upper


def _shade_zone(ax, zone, label, alpha=0.10):
    bounds = _zone_bounds(zone)
    if not bounds:
        return
    lower, upper = bounds
    ax.axhspan(lower, upper, alpha=alpha, label=label)


def _fmt_price(value):
    if value is None:
        return "-"
    value = float(value)
    if abs(value) >= 1000:
        return f"{value:,.2f}"
    if abs(value) >= 1:
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return f"{value:.6f}".rstrip("0").rstrip(".")


def _draw_candles(ax, frame):
    data = frame.tail(CHART_BARS).copy()
    xs = mdates.date2num(data.index.to_pydatetime())

    if len(xs) > 1:
        width = (xs[1] - xs[0]) * 0.62
    else:
        width = 0.006

    for x, (_, row) in zip(xs, data.iterrows()):
        open_price = float(row["open"])
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])

        rising = close >= open_price
        body_bottom = min(open_price, close)
        body_height = max(abs(close - open_price), 1e-12)

        edge = "#1f9d72" if rising else "#d64f4f"
        face = edge

        ax.vlines(x, low, high, color=edge, linewidth=0.8, zorder=2)
        ax.add_patch(
            Rectangle(
                (x - width / 2, body_bottom),
                width,
                body_height,
                facecolor=face,
                edgecolor=edge,
                linewidth=0.6,
                zorder=3,
            )
        )

    ax.set_xlim(xs[0] - width * 2, xs[-1] + width * 8)
    ax.xaxis_date()
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d\n%H:%M"))
    return data, xs


def render_setup_chart(symbol, frame_15m, item):
    CHART_DIR.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(14, 8), dpi=150)
    data, _ = _draw_candles(ax, frame_15m)

    plan = item.get("trade_plan", {})
    entry = plan.get("entry_zone", {})
    direction = (item.get("direction") or "-").upper()
    bucket = item.get("bucket", "-")
    score = item.get("score", 0)
    mtf = item.get("mtf_alignment", "-")
    rr = plan.get("first_target_rr")
    distance = item.get("entry_distance_atr")

    # PA/SMC zones. HTF zones use lighter shading so the execution chart
    # remains readable.
    a15 = item.get("analysis_15m", {})
    a1h = item.get("analysis_1h", {})
    a4h = item.get("analysis_4h", {})

    _shade_zone(ax, a15.get("nearest_demand"), "15M Demand", alpha=0.12)
    _shade_zone(ax, a15.get("nearest_supply"), "15M Supply", alpha=0.12)
    _shade_zone(ax, a1h.get("nearest_demand"), "1H Demand", alpha=0.06)
    _shade_zone(ax, a1h.get("nearest_supply"), "1H Supply", alpha=0.06)
    _shade_zone(ax, a4h.get("nearest_demand"), "4H Demand", alpha=0.035)
    _shade_zone(ax, a4h.get("nearest_supply"), "4H Supply", alpha=0.035)

    entry_bounds = _zone_bounds(entry)
    if entry_bounds:
        lower, upper = entry_bounds
        ax.axhspan(lower, upper, alpha=0.20, label="ENTRY")

    stop = plan.get("stop_loss")
    if stop is not None:
        ax.axhline(float(stop), linestyle="--", linewidth=1.2, label=f"SL {_fmt_price(stop)}")

    for target in (plan.get("targets") or [])[:3]:
        price = target.get("price")
        if price is None:
            continue
        name = target.get("name") or "TP"
        target_rr = target.get("rr")
        rr_text = f" {target_rr:.2f}R" if target_rr is not None else ""
        ax.axhline(
            float(price),
            linestyle=":",
            linewidth=1.0,
            label=f"{name} {_fmt_price(price)}{rr_text}",
        )

    live_price = (item.get("ticker") or {}).get("last_price")
    if live_price is not None:
        ax.axhline(
            float(live_price),
            linewidth=0.9,
            alpha=0.7,
            label=f"Live {_fmt_price(live_price)}",
        )

    rr_text = f"{rr:.2f}R" if rr is not None else "-"
    dist_text = f"{distance:.2f} ATR" if distance is not None else "-"

    ax.set_title(
        f"{symbol} | 15M | {bucket} | {direction} | Score {score}/100\n"
        f"MTF {mtf} | TP1 RR {rr_text} | Entry distance {dist_text}",
        fontsize=13,
    )
    ax.set_ylabel("Price")
    ax.grid(alpha=0.15)
    ax.legend(loc="best", fontsize=8, framealpha=0.85)
    fig.autofmt_xdate()
    fig.tight_layout()

    safe_symbol = symbol.replace("/", "_").replace(":", "_")
    path = CHART_DIR / f"{safe_symbol}_15M.png"
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)

    return path
