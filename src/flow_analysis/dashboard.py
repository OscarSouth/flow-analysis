"""Static dashboard — a glanceable snapshot of the practice.

Published as an artifact: private by default, one stable URL, nothing to host.
It is a *snapshot*, re-rendered on demand rather than live.

Two constraints shape the implementation:

1. **The artifact runtime blocks external hosts**, so a Vega-Lite CDN `<script>`
   would silently render nothing. Charts are converted to inline SVG instead.
2. **Inline SVG cannot restyle itself for dark mode** — axis text, gridlines and
   series colours are baked in at render time. So every chart is rendered twice,
   once per theme, and CSS reveals the matching pair. The dark steps are their
   own values validated against the dark surface, not an inversion of the light
   ones.

Palette is the validated categorical set (slots 1–5 for the five modes) with the
reserved status palette for outcomes, so a state colour never impersonates a
series. Both were run through the palette validator for both surfaces.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

import altair as alt
import polars as pl

from .metrics import diagnostics as dx
from .metrics import frames as fr
from .metrics.contracts import REGISTRY

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from .config import Config
    from .metrics.grid import FlowRow

CHART_WIDTH = 600


@dataclass(frozen=True)
class Theme:
    """Everything a chart needs to be legible on one surface."""

    name: str
    surface: str
    ink: str  # axis titles
    ink_muted: str  # tick labels
    grid: str
    series: tuple[str, ...]  # categorical slots 1–5, validated
    good: str
    warning: str
    critical: str
    inactive: str
    single: str  # single-series hue

    @property
    def outcomes(self) -> list[str]:
        """Outcome is a *state*, so it takes the reserved status palette."""
        return [self.good, self.warning, self.critical, self.inactive]


LIGHT = Theme(
    name="light",
    surface="#ffffff",
    ink="#31363b",
    ink_muted="#61686f",
    grid="#e7eaed",
    series=("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"),
    good="#0ca30c",
    warning="#fab219",
    critical="#d03b3b",
    inactive="#c2c7cc",
    single="#2a78d6",
)

DARK = Theme(
    name="dark",
    surface="#1d2023",
    ink="#dfe3e7",
    ink_muted="#9aa1a8",
    grid="#2e3338",
    series=("#3987e5", "#d95926", "#199e70", "#c98500", "#d55181"),
    good="#0ca30c",
    warning="#fab219",
    critical="#d03b3b",
    inactive="#4a5057",
    single="#3987e5",
)


def _configure(chart: alt.Chart, theme: Theme) -> alt.Chart:
    """Text wears text tokens; the grid recedes; the surface stays transparent.

    `background` is a top-level property, not a config key — setting it through
    `.configure()` would replace the config object these calls just built.
    """
    # altair ships types, but its mark/encode/configure builders are generated
    # and hand back `Any`, so every chart chain in this module ends in a cast to
    # keep the declared return honest. A library gap, not a JSON boundary.
    return cast(
        "alt.Chart",
        chart.properties(background="transparent")
        .configure_view(stroke=None, fill=None)
        .configure_axis(
            labelColor=theme.ink_muted,
            titleColor=theme.ink,
            gridColor=theme.grid,
            domainColor=theme.grid,
            tickColor=theme.grid,
            labelFontSize=11,
            titleFontSize=11,
            titleFontWeight="normal",
        )
        .configure_legend(
            labelColor=theme.ink_muted,
            titleColor=theme.ink,
            labelFontSize=11,
            titleFontSize=11,
            # Left at the default weight on purpose: a line-mark legend draws
            # its swatch *as* a stroke, so zeroing it leaves identity carried by
            # nothing but the colour of the line in the plot.
            symbolStrokeWidth=3,
        ),
    )


def _svg(chart: alt.Chart, theme: Theme) -> str:
    import vl_convert as vlc

    return vlc.vegalite_to_svg(_configure(chart, theme).to_json())


# --- charts -----------------------------------------------------------------


def _calendar(bundle: dict[str, Any], theme: Theme) -> alt.Chart:
    n_days = bundle["grid"]["day"].n_unique() or 1
    # The gap between cells is 2px where cells are wide enough to carry it, and
    # 1px once a long history squeezes them — a 2px gap on a 5px cell is a grid
    # of gaps, not of data.
    cell = CHART_WIDTH / n_days
    return cast(
        "alt.Chart",
        alt.Chart(bundle["grid"])
        .mark_rect(stroke=theme.surface, strokeWidth=2 if cell >= 8 else 1)
        .encode(
            # The timeUnit is what gives `rect` a band to occupy. Plain `day:T`
            # is continuous, leaves the mark no width, and every cell ends up
            # spanning the whole row — the last one drawn wins. Keeping the axis
            # temporal (rather than ordinal) also keeps tick density under
            # control as the history grows.
            x=alt.X(
                "yearmonthdate(day):T",
                title=None,
                axis=alt.Axis(format="%-d %b", labelAngle=0, tickCount=8),
            ),
            y=alt.Y("activity:N", title=None, sort=None),
            color=alt.Color(
                "outcome:N",
                title="outcome",
                scale=alt.Scale(domain=fr.OUTCOME_ORDER, range=theme.outcomes),
            ),
        )
        .properties(width=CHART_WIDTH, height=150),
    )


def _rolling(
    bundle: dict[str, Any], theme: Theme, activities: Sequence[str]
) -> alt.Chart:
    return cast(
        "alt.Chart",
        alt.Chart(bundle["rolling"].filter(pl.col("window") == 28))
        .mark_line(strokeWidth=2)
        .encode(
            x=alt.X("day:T", title=None),
            y=alt.Y(
                "rate:Q", title="28-day completion rate", scale=alt.Scale(domain=[0, 1])
            ),
            # Colour follows the entity, in fixed slot order — never cycled, and
            # never repainted when a filter changes the series count.
            color=alt.Color(
                "activity:N",
                title=None,
                scale=alt.Scale(domain=list(activities), range=list(theme.series)),
            ),
        )
        .properties(width=CHART_WIDTH, height=190),
    )


def _latency(touched: pl.DataFrame, theme: Theme) -> alt.Chart:
    # No colour encoding: the y-axis already carries identity, so colouring by
    # activity would encode the same thing twice.
    return cast(
        "alt.Chart",
        alt.Chart(touched.with_columns(hours=pl.col("minutes_to_start") / 60))
        .mark_boxplot(extent="min-max", size=14, color=theme.single)
        .encode(
            x=alt.X("hours:Q", title="hours from appearing to first touch"),
            y=alt.Y("activity:N", title=None, sort=None),
        )
        .properties(width=CHART_WIDTH, height=160),
    )


def _charge(series: pl.DataFrame, theme: Theme) -> alt.Chart:
    return cast(
        "alt.Chart",
        alt.Chart(series)
        .mark_area(
            opacity=0.28,
            line={"color": theme.single, "strokeWidth": 2},
            color=theme.single,
        )
        .encode(
            x=alt.X("day:T", title=None),
            y=alt.Y("charge:Q", title="charge", scale=alt.Scale(domain=[0, 1])),
        )
        .properties(width=CHART_WIDTH, height=150),
    )


def _by_year(frame: pl.DataFrame, theme: Theme, field: str, title: str) -> alt.Chart:
    """Annual totals for a reception series.

    The year is the unit because the question is cumulative reward on sustained
    commitment, and daily figures here are mostly zeros.
    """
    return cast(
        "alt.Chart",
        alt.Chart(frame)
        .mark_bar(cornerRadiusEnd=3, size=18, color=theme.single)
        .encode(
            x=alt.X("year:O", title=None, axis=alt.Axis(labelAngle=0)),
            y=alt.Y(f"{field}:Q", title=title),
        )
        .properties(width=CHART_WIDTH, height=150),
    )


def _net_subscribers(frame: pl.DataFrame, theme: Theme) -> alt.Chart:
    """Net subscriber movement — polarity, so two hues about a zero baseline."""
    bars = (
        alt.Chart(frame)
        .mark_bar(cornerRadiusEnd=3, size=18)
        .encode(
            x=alt.X("year:O", title=None, axis=alt.Axis(labelAngle=0)),
            y=alt.Y("net:Q", title="net subscribers"),
            color=alt.condition(
                alt.datum.net >= 0,
                alt.value(theme.series[0]),
                alt.value(theme.series[1]),
            ),
        )
    )
    zero = (
        alt.Chart(frame)
        .mark_rule(color=theme.grid, strokeWidth=1)
        .encode(y=alt.datum(0))
    )
    return cast("alt.Chart", (bars + zero).properties(width=CHART_WIDTH, height=150))


def _coupling(lags: pl.DataFrame, theme: Theme) -> alt.Chart:
    # Correlation is polarity, so the two directions take opposing hues with a
    # zero baseline between them rather than one ramp.
    bars = (
        alt.Chart(lags)
        .mark_bar(cornerRadiusEnd=4, size=16)
        .encode(
            x=alt.X(
                "lag:O",
                title="lag in days — adherence today, output later",
                axis=alt.Axis(labelAngle=0),
            ),
            y=alt.Y("r:Q", title="correlation"),
            color=alt.condition(
                alt.datum.r > 0, alt.value(theme.series[0]), alt.value(theme.series[1])
            ),
        )
    )
    zero = (
        alt.Chart(lags)
        .mark_rule(color=theme.grid, strokeWidth=1)
        .encode(y=alt.datum(0))
    )
    return cast("alt.Chart", (bars + zero).properties(width=CHART_WIDTH, height=150))


# --- html -------------------------------------------------------------------


def _panel(title: str, body: str, note: str = "") -> str:
    note_html = f'<p class="note">{html.escape(note)}</p>' if note else ""
    return (
        f'<section class="panel"><h2>{html.escape(title)}</h2>{note_html}'
        f'<div class="figure">{body}</div></section>'
    )


def _gated(gate: fr.Gate) -> str:
    return (
        '<div class="gate"><strong>Not enough data yet</strong>'
        f"<span>{gate.n} of {gate.needs} needed — {gate.needs - gate.n} more to "
        f"go</span></div>"
    )


def _both_themes(build: Callable[[Theme], alt.Chart]) -> str:
    """Render a chart for each surface; CSS reveals the matching one."""
    return (
        f'<div class="only-light">{_svg(build(LIGHT), LIGHT)}</div>'
        f'<div class="only-dark">{_svg(build(DARK), DARK)}</div>'
    )


def _hypotheses(diag: dict[str, Any]) -> str:
    """The contract registry as a table.

    Deterministic verdicts render inline; posterior contracts show their gate
    state here (verdicts live on the posterior snapshot, in the evidence
    surface). Colour is health, not verdict: c9's floor is health-positive,
    so `supported` is green there and red would be wrong.
    """
    css = {
        "supported": "yes",
        "inconclusive": "watch",
        "not supported": "no",
        "not testable yet": "pending",
    }
    rows = []
    for contract in REGISTRY:
        measure = diag["measures"].get(contract.key)
        label = f"{contract.title} [{contract.component}]"
        if measure is None or not measure.ok:
            n = measure.n if measure is not None else 0
            needs = measure.needs if measure is not None else contract.needs
            verdict = f'<span class="pending">not testable yet — {n} of {needs}</span>'
        elif contract.kind == "deterministic":
            state = measure.value["verdict"]
            healthy = state == contract.healthy_verdict
            klass = (
                ("yes" if healthy else css.get(state, "watch"))
                if state != "not testable yet"
                else "pending"
            )
            if not healthy and state in {"supported", "not supported"}:
                klass = "no"
            verdict = f'<span class="{klass}">{html.escape(state)}</span>'
        else:
            verdict = '<span class="pending">gate met — see evidence</span>'
        rows.append(f"<tr><td>{html.escape(label)}</td><td>{verdict}</td></tr>")
    return f"<table><tbody>{''.join(rows)}</tbody></table>"


def _failure_kind(diag: dict[str, Any]) -> str:
    measure = diag["measures"]["allocation_vs_capacity"]
    if not measure.ok:
        return _gated(fr.Gate("failure kind", measure.n, measure.needs))
    rows = [
        "<tr><th>mode</th><th>dominant</th><th>never "
        "started</th><th>abandoned</th></tr>"
    ]
    for activity, stat in measure.value.items():
        rows.append(
            f"<tr><td>{html.escape(activity)}</td><td>{stat['dominant'] or '—'}</td>"
            f"<td class='num'>{stat['allocation']}</td><td "
            f"class='num'>{stat['capacity']}</td></tr>"
        )
    return f"<table><tbody>{''.join(rows)}</tbody></table>"


def _dormancy(diag: dict[str, Any]) -> str:
    measure = diag["measures"]["dormancy"]
    if not measure.ok:
        return _gated(fr.Gate("dormancy", measure.n, measure.needs))
    # Three states, three colours: a channel closed for a week is a warning, one
    # closed for three weeks is evidence about R itself. Collapsing the two into
    # one red would lose the distinction the measure exists to draw.
    css_for = {"open": "yes", "dormant": "watch", "escalate": "no"}
    rows = ["<tr><th>mode</th><th>closed now</th><th>longest</th><th>state</th></tr>"]
    for activity, stat in measure.value.items():
        css = css_for.get(stat["status"], "pending")
        rows.append(
            f"<tr><td>{html.escape(activity)}</td><td "
            f"class='num'>{stat['current']}</td>"
            f"<td class='num'>{stat['longest']}</td>"
            f"<td><span class='{css}'>{stat['status']}</span></td></tr>"
        )
    return f"<table><tbody>{''.join(rows)}</tbody></table>"


def _flow_era_table(summary: dict[str, Any]) -> str:
    """Growth since the epoch, with the inherited baseline demoted beside it."""
    era = summary.get("flow_era") or {}
    labels = [
        ("youtube_subscribers", "YouTube subscribers, net"),
        ("youtube_views", "YouTube views"),
        ("youtube_minutes", "YouTube minutes watched"),
        ("github_stars", "GitHub stars"),
        ("forum_outsiders", "Forum posts by outsiders"),
    ]
    rows = ["<tr><th>signal</th><th>since flow</th><th>baseline before</th></tr>"]
    for key, label in labels:
        stat = era.get(key)
        if stat is None:
            continue
        css = "yes" if stat["since"] > 0 else "pending"
        rows.append(
            f"<tr><td>{html.escape(label)}</td>"
            f"<td class='num'><span class='{css}'>{stat['since']:+}</span></td>"
            f"<td class='num muted'>{stat['baseline']:,}</td></tr>"
        )
    return f"<table><tbody>{''.join(rows)}</tbody></table>"


def render(
    cfg: Config,
    rows: Sequence[FlowRow],
    production: dict[str, int],
    signal_rows: Sequence[dict[str, Any]],
    fabricated: bool = False,
) -> str:
    """The whole dashboard as one self-contained HTML file.

    Charts are rendered twice, light and dark, and CSS reveals the matching one —
    the file has to work offline from a filesystem, so there is no runtime to ask
    which theme is in force.
    """
    rows = list(rows)
    bundle = fr.load(cfg, rows, production)
    diag = dx.run_all(cfg, rows, production)
    generated = datetime.now(UTC).strftime("%-d %B %Y, %H:%M UTC")
    activities = list(cfg.activities)

    # Charts, each gated before it is built.
    cal_gate = fr.gate("calendar", bundle["n_days"])
    calendar = (
        _gated(cal_gate)
        if not cal_gate.open
        else _both_themes(lambda t: _calendar(bundle, t))
    )

    roll_gate = fr.gate("rolling_rate", bundle["n_days"])
    rolling = (
        _gated(roll_gate)
        if not roll_gate.open
        else _both_themes(lambda t: _rolling(bundle, t, activities))
    )

    touched = bundle["grid"].filter(pl.col("minutes_to_start").is_not_null())
    per_mode = touched.group_by("activity").agg(n=pl.len())
    lat_gate = fr.gate(
        "start_latency", int(per_mode["n"].min()) if per_mode.height else 0
    )
    latency = (
        _gated(lat_gate)
        if not lat_gate.open
        else _both_themes(lambda t: _latency(touched, t))
    )

    charge_m = diag["measures"]["charge"]
    if charge_m.ok:
        charge_series = pl.DataFrame(charge_m.detail["series"]).with_columns(
            pl.col("day").str.to_date()
        )
        charge = _both_themes(lambda t: _charge(charge_series, t))
    else:
        charge = _gated(fr.Gate("charge", charge_m.n, charge_m.needs))

    coup_m = diag["measures"]["coupling"]
    if coup_m.ok:
        lag_frame = pl.DataFrame(coup_m.detail["by_lag"])
        coupling = _both_themes(lambda t: _coupling(lag_frame, t))
    else:
        coupling = _gated(fr.Gate("coupling", coup_m.n, coup_m.needs))

    # Reception. Deliberately outside the practice gates: a cumulative total is a
    # fact and needs no N, and the epoch delta is the headline regardless.
    from .metrics import reception as reception_mod

    rec = reception_mod.summarise(cfg, signal_rows)
    reception_panels = ""
    if rec.get("counters") or rec.get("youtube_by_year"):
        years = rec["youtube_by_year"]
        blocks = [
            _panel(
                f"Since flow began — {rec['epoch']}",
                _flow_era_table(rec),
                "Everything before that date is ground zero: real, but earned by "
                "ad-hoc ventures rather than by this practice. Only the left column "
                "belongs to flow.",
            )
        ]
        if years:
            frame = pl.DataFrame(
                [
                    {
                        "year": year,
                        "views": stat["views"],
                        "net": stat["net_subscribers"],
                        "hours": stat["minutes"] // 60,
                    }
                    for year, stat in years.items()
                ]
            )
            blocks.append(
                _panel(
                    "YouTube views by year",
                    _both_themes(lambda t: _by_year(frame, t, "views", "views")),
                    "Inherited context. The year is the unit because the question is "
                    "cumulative reward on sustained commitment.",
                )
            )
            blocks.append(
                _panel(
                    "YouTube net subscribers by year",
                    _both_themes(lambda t: _net_subscribers(frame, t)),
                    "Inherited context, and not attributable to the practice — these "
                    "were earned before it began.",
                )
            )
        stars = rec["stars"]
        if stars["total"]:
            star_frame = pl.DataFrame(
                [{"year": y, "stars": n} for y, n in stars["by_year"].items()]
            )
            blocks.append(
                _panel(
                    "GitHub stars by year",
                    _both_themes(lambda t: _by_year(star_frame, t, "stars", "stars")),
                    f"Peaked in {stars['peak_year']} and faded. A record of when "
                    "attention arrived, never a forecast.",
                )
            )
        reception_panels = "".join(blocks)

    banner = (
        '<div class="warn"><strong>Fabricated data.</strong> Built to contain the '
        "patterns the analysis looks for. Not evidence about the practice.</div>"
        if fabricated
        else ""
    )
    short = diag["underpowered"]
    status = (
        f"{len(short)} of {len(diag['measures'])} measures still waiting for data"
        if short
        else "every measure has enough data"
    )

    panels = "".join(
        [
            _panel("Calendar", calendar, "Five modes by day, coloured by outcome."),
            _panel(
                "Completion rate",
                rolling,
                "Rate over a 28-day window, never a cumulative count — a missed day is "
                "data, not debt, so there is no backlog to carry.",
            ),
            _panel(
                "Pre-registered hypotheses",
                _hypotheses(diag),
                "Committed to publicly before any data existed, and tested as "
                "published.",
            ),
            _panel(
                "Failure kind",
                _failure_kind(diag),
                "Never-started is an allocation failure and wants protected time. "
                "Abandoned is a capacity failure and wants drills. One label in the "
                "framework, opposite remedies.",
            ),
            _panel(
                "Dormancy",
                _dormancy(diag),
                "Consecutive days a channel went untouched. Not uninspiration — "
                "nothing was attempted, so nothing failed to be reached.",
            ),
            _panel("Time to first touch", latency, "The hesitation signal."),
            _panel(
                "Charge",
                charge,
                "How unevenly attention is spread across the five. Zero is harmonious, "
                "and the quiet precursor to stagnation.",
            ),
            _panel(
                "Coupling to output",
                coupling,
                "Association only. Nothing is randomised, so a good day plausibly "
                "raises both completions and output.",
            ),
        ]
    )
    panels += reception_panels

    return f"""<title>W.A.T.E.R. Diagnostics</title>
<style>
  :root {{
    --bg: #f7f8f9;
    --card: #ffffff;
    --ink: #1b1f23;
    --ink-2: #4d555d;
    --ink-3: #7b848d;
    --line: #e2e6ea;
    --accent: #2a78d6;
    --good: #0ca30c;
    --mid: #8a5a00;
    --bad: #d03b3b;
    --warn-bg: #fdf3e3;
    --warn-ink: #7a5312;
  }}
  @media (prefers-color-scheme: dark) {{
    :root:not([data-theme="light"]) {{
      --bg: #141719;
      --card: #1d2023;
      --ink: #e8ebee;
      --ink-2: #b3bac1;
      --ink-3: #858e97;
      --line: #2e3338;
      --accent: #3987e5;
      --mid: #fab219;
      --warn-bg: #2c2413;
      --warn-ink: #e8c887;
    }}
  }}
  :root[data-theme="dark"] {{
    --bg: #141719;
    --card: #1d2023;
    --ink: #e8ebee;
    --ink-2: #b3bac1;
    --ink-3: #858e97;
    --line: #2e3338;
    --accent: #3987e5;
    --mid: #fab219;
    --warn-bg: #2c2413;
    --warn-ink: #e8c887;
  }}

  body {{
    margin: 0;
    padding: 2.5rem 1.25rem 5rem;
    background: var(--bg);
    color: var(--ink);
    font: 400 16px/1.6 ui-sans-serif, -apple-system, BlinkMacSystemFont,
          "Segoe UI", sans-serif;
    -webkit-font-smoothing: antialiased;
  }}
  /* Wide enough that a chart plus its legend renders at its intrinsic size.
     Inline SVG cannot reflow, so a narrower column would scale the whole figure
     down and take the axis text with it. */
  .wrap {{ max-width: 860px; margin: 0 auto; display: flex;
           flex-direction: column; gap: 1rem; }}

  header {{ display: flex; flex-direction: column; gap: .35rem; margin-bottom: .5rem; }}
  h1 {{
    margin: 0; font-size: 1.55rem; font-weight: 600; letter-spacing: -.025em;
    text-wrap: balance;
  }}
  .modes {{
    display: flex; flex-wrap: wrap; gap: .4rem; font-size: .74rem;
    letter-spacing: .09em; text-transform: uppercase; color: var(--ink-3);
  }}
  .modes span::after {{ content: " ·"; }}
  .modes span:last-child::after {{ content: ""; }}
  .meta {{ color: var(--ink-3); font-size: .85rem;
           font-variant-numeric: tabular-nums; }}

  .panel {{
    background: var(--card); border: 1px solid var(--line); border-radius: 12px;
    padding: 1.15rem 1.25rem; display: flex; flex-direction: column; gap: .55rem;
  }}
  h2 {{ margin: 0; font-size: .95rem; font-weight: 600; letter-spacing: -.01em; }}
  .note {{ margin: 0; color: var(--ink-2); font-size: .845rem; max-width: 60ch; }}
  .figure {{ overflow-x: auto; margin-top: .2rem; }}
  .figure svg {{ max-width: 100%; height: auto; display: block; }}

  .gate {{
    border: 1px dashed var(--line); border-radius: 9px; padding: .95rem 1rem;
    display: flex; flex-wrap: wrap; gap: .5rem; align-items: baseline;
    color: var(--ink-3); font-size: .87rem;
  }}
  .gate strong {{ color: var(--ink-2); font-weight: 600; }}

  table {{ border-collapse: collapse; width: 100%; font-size: .87rem; }}
  th, td {{ text-align: left; padding: .5rem .35rem;
            border-bottom: 1px solid var(--line); }}
  th {{ color: var(--ink-3); font-weight: 500; font-size: .78rem;
        text-transform: uppercase; letter-spacing: .06em; }}
  tr:last-child td {{ border-bottom: none; }}
  td.num {{ font-variant-numeric: tabular-nums; }}
  .yes {{ color: var(--good); font-weight: 600; }}
  .watch {{ color: var(--mid); font-weight: 600; }}
  .no {{ color: var(--bad); font-weight: 600; }}
  .pending {{ color: var(--ink-3); }}
  .muted {{ color: var(--ink-3); }}

  .warn {{
    background: var(--warn-bg); color: var(--warn-ink); border-radius: 9px;
    padding: .75rem .95rem; font-size: .87rem;
  }}
  footer {{ color: var(--ink-3); font-size: .8rem; max-width: 60ch; }}
  code {{ font-size: .95em; }}

  /* Inline SVG bakes its colours at render time, so each chart ships twice. */
  .only-dark {{ display: none; }}
  @media (prefers-color-scheme: dark) {{
    :root:not([data-theme="light"]) .only-light {{ display: none; }}
    :root:not([data-theme="light"]) .only-dark {{ display: block; }}
  }}
  :root[data-theme="dark"] .only-light {{ display: none; }}
  :root[data-theme="dark"] .only-dark {{ display: block; }}
  :root[data-theme="light"] .only-light {{ display: block; }}
  :root[data-theme="light"] .only-dark {{ display: none; }}
</style>
<div class="wrap">
  {banner}
  <header>
    <h1>W.A.T.E.R. Diagnostics</h1>
    <div class="modes">
      <span>Write</span><span>Absorb</span><span>Train</span>
      <span>Express</span><span>Reveal</span>
    </div>
    <p class="meta">{bundle["n_days"]} days observed · {status} · {generated}</p>
  </header>
  {panels}
  <footer>
    Five cards appear each morning; anything unfinished drains at 04:00. Diagnostics
    follow <code>docs/06-diagnostics.md</code>, which names which of validity,
    evaluation or traversal each failure implicates.
  </footer>
</div>"""
