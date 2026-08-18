import marimo

__generated_with = "0.23.16"
app = marimo.App(width="medium", app_title="Flow — W.A.T.E.R. diagnostics")


@app.cell
def imports():
    import sys
    from pathlib import Path

    import altair as alt
    import marimo as mo
    import polars as pl

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

    from flow_analysis import dashboard, fixtures, store
    from flow_analysis.config import load_config
    from flow_analysis.metrics import diagnostics as dx
    from flow_analysis.metrics import frames
    from flow_analysis.metrics import grid
    from flow_analysis.graph import loaders
    from flow_analysis.metrics.production import production_by_day

    # One palette, defined once, shared with the published dashboard: the
    # validated categorical slots for identity and the reserved status palette
    # for outcomes. marimo renders on a light surface, so the light steps apply.
    theme = dashboard.LIGHT
    return (
        alt,
        dx,
        fixtures,
        frames,
        grid,
        load_config,
        loaders,
        mo,
        pl,
        production_by_day,
        store,
        theme,
    )


@app.cell
def intro(mo):
    mo.md("""
    # Flow — W.A.T.E.R. diagnostics

    **What this is**: the analysis surface over the daily practice. Five cards
    appear each morning; anything unfinished is drained at 04:00. This notebook
    asks what that record says.

    **The discipline** (see `docs/06-diagnostics.md`):

    - Hypotheses are **pre-registered**. Three are committed to publicly in
      article 05 and are tested exactly as published.
    - Every plot is **N-gated** and refuses rather than misleads. Five binary-ish
      outcomes a day is thin; rates are noise for 8–12 weeks.
    - Nothing is **causal**. Card order is randomised for variety, not inference,
      so any coupling to output is confounded.

    **How to read this notebook** (literate contract: `notebooks/README.md`):
    top to bottom, as one story. It moves from *what happened* (the calendar,
    the rates) through *how the days actually went* (latency, ordering) to
    *what the system judges* (diagnostics) and finally *what it believes, with
    how strongly* (the posterior chapter at the end). Every closed gate speaks
    in prose — "not yet" is part of the story.

    **Toggle the source below.** Fixture data is fabricated to *contain* the
    patterns the analysis looks for — use it to check the machinery, never as
    evidence about the practice.
    """)
    return


@app.cell
def source_toggle(mo):
    source = mo.ui.radio(
        options=["real", "fixture (fabricated)"],
        value="real",
        label="Data source",
    )
    days = mo.ui.slider(30, 365, value=120, label="Fixture days")
    mo.hstack([source, days], justify="start")
    return days, source


@app.cell
def load_data(
    days,
    dx,
    fixtures,
    frames,
    grid,
    load_config,
    loaders,
    production_by_day,
    source,
    store,
):
    import tempfile
    from pathlib import Path as _Path

    if source.value.startswith("fixture"):
        _fx = fixtures.synthesize(days=days.value)
        _tmp = _Path(tempfile.mkdtemp())
        store.ACTIONS_PATH = _tmp / "actions.jsonl"
        store.CARDS_PATH = _tmp / "cards.jsonl"
        store.SIGNALS_PATH = _tmp / "signals.jsonl"
        store.STATE_PATH = _tmp / "state.json"
        store.DATA_DIR = _tmp
        store.append_actions(_fx.actions, set())
        store.append_cards(_fx.cards, set())
        cfg = fixtures.fixture_config(_fx.days[0])
        production = production_by_day(
            cfg, [{"id": p["id"], "created_at": p["created_at"]} for p in _fx.forum]
        )
        fabricated = True
        # Fixture rows fold from the throwaway store: fabricated data never
        # passes through the real graph.
        rows = grid.fold_rows(cfg, store.load_cards_latest(), store.load_actions())
    else:
        # Real analysis reads the graph and only the graph (2026-08-18).
        cfg = load_config()
        production = loaders.production_by_day()
        rows = loaders.flow_rows()
        fabricated = False
    F = frames.load(cfg, rows, production)
    diag = dx.run_all(cfg, rows, production)
    return F, diag, fabricated, rows


@app.cell
def header(F, diag, fabricated, mo):
    _warning = (
        "> ⚠️ **Fabricated data.** Built to contain the patterns being looked "
        "for. Never cite as evidence.\n\n"
        if fabricated
        else ""
    )
    _short = diag["underpowered"]
    _status = (
        ", ".join(_short) if _short else "none — every measure has enough data"
    )
    mo.md(
        f"""{_warning}**{F['n_days']} days observed.**
        {len(_short)} of {len(diag['measures'])} measures are underpowered: `{_status}`
        """
    )
    return


@app.cell
def _preregistered_header(mo):
    mo.md("""
    ## Pre-registered hypotheses

    "
        "Committed to publicly in article 05, before any data existed. Tested as "
        "published, not reworded to whatever the numbers happen to support.
    """)
    return


@app.cell
def preregistered(diag, mo):
    _labels = {
        "h1_train_most_never_started": "**H1** — Train is the most frequent never-started",
        "h2_express_slowest_to_start": "**H2** — Express carries the longest delay to first touch",
        "h3_write_carries_the_others": "**H3** — days Write is missed show lower completion elsewhere",
    }
    _lines = []
    for _key, _label in _labels.items():
        _m = diag["measures"][_key]
        if not _m.ok:
            _lines.append(f"- {_label}\n    - *underpowered*: N={_m.n}, needs {_m.needs}")
        else:
            _verdict = "**supported**" if _m.value["supported"] else "**not supported**"
            _rest = {k: v for k, v in _m.value.items() if k != "supported"}
            _lines.append(f"- {_label}\n    - {_verdict} — `{_rest}`")
    mo.md("\n".join(_lines))
    return


@app.cell
def _plot1_header(mo):
    mo.md("""
    ## 1 — Calendar

    The glance: five modes by day, coloured by outcome.
    """)
    return


@app.cell
def plot_calendar(F, alt, frames, mo, theme):
    _g = frames.gate("calendar", F["n_days"])
    if not _g.open:
        _view = mo.md(_g.message)
    else:
        _view = mo.ui.altair_chart(
            alt.Chart(F["grid"])
            .mark_rect(stroke=theme.surface, strokeWidth=1)
            .encode(
                # timeUnit, not plain `day:T`: a continuous x leaves `rect` no
                # band, so every cell spans the row and the last drawn wins.
                x=alt.X(
                    "yearmonthdate(day):T",
                    title=None,
                    axis=alt.Axis(format="%-d %b", labelAngle=0, tickCount=8),
                ),
                y=alt.Y("activity:N", title=None, sort=None),
                color=alt.Color(
                    "outcome:N",
                    title="outcome",
                    scale=alt.Scale(
                        domain=frames.OUTCOME_ORDER,
                        range=theme.outcomes,
                    ),
                ),
                tooltip=["day:T", "activity:N", "outcome:N", "minutes_to_start:Q"],
            )
            .properties(height=180)
        )
    _view
    return


@app.cell
def _plot2_header(mo):
    mo.md("""
    ## 2 — Rolling completion rate

    "
        "Rate, never cumulative count: a missed day is data, not debt, so there "
        "is no backlog to accumulate.
    """)
    return


@app.cell
def plot_rolling(F, alt, frames, mo, theme):
    _g = frames.gate("rolling_rate", F["n_days"])
    if not _g.open:
        _view = mo.md(_g.message)
    else:
        _view = mo.ui.altair_chart(
            alt.Chart(F["rolling"])
            .mark_line()
            .encode(
                x=alt.X("day:T", title=None),
                y=alt.Y("rate:Q", title="completion rate", scale=alt.Scale(domain=[0, 1])),
                # Two fixed slots, so the short and long window keep the same
                # colours no matter which facets happen to have data.
                color=alt.Color(
                    "window:N",
                    title="window (days)",
                    scale=alt.Scale(
                        domain=["7", "28"],
                        range=[theme.series[1], theme.series[0]],
                    ),
                ),
                tooltip=["day:T", "activity:N", "rate:Q", "window:N"],
            )
            .properties(height=110)
            .facet(row=alt.Row("activity:N", title=None))
            .resolve_scale(y="shared")
        )
    _view
    return


@app.cell
def _plot34_header(mo):
    mo.md("""
    ## 3 & 4 — Latency and the clock

    "
        "How long until a mode is first touched, and when work actually lands. "
        "Time-to-start is the hesitation signal — the quantity most likely to "
        "move before a streak breaks.
    """)
    return


@app.cell
def plot_latency(F, alt, frames, mo, pl, theme):
    _touched = F["grid"].filter(pl.col("minutes_to_start").is_not_null())
    _per_mode = _touched.group_by("activity").agg(n=pl.len())
    _smallest = int(_per_mode["n"].min()) if _per_mode.height else 0
    _g = frames.gate("start_latency", _smallest)
    if not _g.open:
        _view = mo.md(_g.message + "  *(counted per mode, not per day)*")
    else:
        _view = mo.ui.altair_chart(
            alt.Chart(_touched.with_columns(hours=pl.col("minutes_to_start") / 60))
            # One hue: the y-axis already carries identity, so colouring by
            # activity too would encode the same thing twice.
            .mark_boxplot(extent="min-max", color=theme.single)
            .encode(
                x=alt.X("hours:Q", title="hours from appearing to first touch"),
                y=alt.Y("activity:N", title=None, sort=None),
            )
            .properties(height=180)
        )
    _view
    return


@app.cell
def plot_clock(F, alt, frames, mo, pl):
    _done = F["grid"].filter(pl.col("completed_hour").is_not_null())
    _per_mode = _done.group_by("activity").agg(n=pl.len())
    _smallest = int(_per_mode["n"].min()) if _per_mode.height else 0
    _g = frames.gate("completion_clock", _smallest)
    if not _g.open:
        _view = mo.md(_g.message + "  *(counted per mode, not per day)*")
    else:
        _view = mo.ui.altair_chart(
            alt.Chart(_done)
            .mark_rect()
            .encode(
                x=alt.X("completed_hour:O", title="local hour completed"),
                y=alt.Y("activity:N", title=None, sort=None),
                color=alt.Color("count():Q", title="completions", scale=alt.Scale(scheme="blues")),
                tooltip=["activity:N", "completed_hour:O", "count():Q"],
            )
            .properties(height=180)
        )
    _view
    return


@app.cell
def _plot56_header(mo):
    mo.md("""
    ## 5 & 6 — Weekday shape and pull order

    "
        "Cards are refilled in random order, so which mode gets reached first is "
        "a choice rather than an artefact of the list.
    """)
    return


@app.cell
def plot_weekday(F, alt, frames, mo):
    _g = frames.gate("weekday", F["n_days"])
    if not _g.open:
        _view = mo.md(_g.message)
    else:
        _view = mo.ui.altair_chart(
            alt.Chart(F["weekday"])
            .mark_rect()
            .encode(
                x=alt.X(
                    "weekday:N",
                    sort=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
                    title=None,
                ),
                y=alt.Y("activity:N", title=None, sort=None),
                color=alt.Color(
                    "rate:Q",
                    title="completion",
                    scale=alt.Scale(scheme="blues", domain=[0, 1]),
                ),
                tooltip=["activity:N", "weekday:N", "rate:Q", "n:Q"],
            )
            .properties(height=180)
        )
    _view
    return


@app.cell
def plot_pull_order(F, alt, frames, mo):
    _g = frames.gate("pull_order", F["n_days"])
    if not _g.open:
        _view = mo.md(_g.message)
    else:
        _view = mo.ui.altair_chart(
            alt.Chart(F["pull_order"])
            .mark_bar()
            .encode(
                x=alt.X("n:Q", title="share of days reached at this position", stack="normalize"),
                y=alt.Y("activity:N", title=None, sort=None),
                color=alt.Color(
                    "pull_rank:O", title="position", scale=alt.Scale(scheme="blues")
                ),
                tooltip=["activity:N", "pull_rank:O", "n:Q"],
            )
            .properties(height=180)
        )
    _view
    return


@app.cell
def _plot78_header(mo):
    mo.md("""
    ## 7 & 8 — Charge and streaks

    "
        "**Charge** is the normalised spread of completion rates across the five. "
        "Zero means attention is spread evenly — harmonious, and the precursor to "
        "stagnation. Approaching one means one mode thrives while another is dead.
    """)
    return


@app.cell
def plot_charge(alt, diag, frames, mo, pl):
    _m = diag["measures"]["charge"]
    if not _m.ok:
        _view = mo.md(frames.Gate("charge", _m.n, _m.needs).message)
    else:
        _series = pl.DataFrame(_m.detail["series"]).with_columns(pl.col("day").str.to_date())
        _view = mo.ui.altair_chart(
            alt.Chart(_series)
            .mark_area(opacity=0.6, line=True)
            .encode(
                x=alt.X("day:T", title=None),
                y=alt.Y("charge:Q", title="charge", scale=alt.Scale(domain=[0, 1])),
                tooltip=["day:T", "charge:Q"],
            )
            .properties(height=160)
        )
    _view
    return


@app.cell
def plot_streaks(F, alt, frames, mo):
    _g = frames.gate("streaks", F["n_days"])
    if not _g.open:
        _view = mo.md(_g.message)
    else:
        _long = F["streaks"].unpivot(
            index="activity",
            on=["current", "longest"],
            variable_name="kind",
            value_name="run",
        )
        _view = mo.ui.altair_chart(
            alt.Chart(_long)
            .mark_bar()
            .encode(
                x=alt.X("run:Q", title="consecutive days completed"),
                y=alt.Y("activity:N", title=None, sort=None),
                color=alt.Color("kind:N", title=None),
                yOffset="kind:N",
                tooltip=["activity:N", "kind:N", "run:Q"],
            )
            .properties(height=180)
        )
    _view
    return


@app.cell
def _plot910_header(mo):
    mo.md("""
    ## 9 & 10 — Coupling to production

    "
        "Does the practice running actually produce anything? Forum posts are the "
        "external trace; Trello can only ever record that the practice ran.

    "
        "> **Association only.** No randomisation by design, so this is "
        "confounded: a good day plausibly raises both completions and output.
    """)
    return


@app.cell
def plot_coupling(alt, diag, frames, mo, pl, theme):
    _m = diag["measures"]["coupling"]
    if not _m.ok:
        _view = mo.md(frames.Gate("coupling", _m.n, _m.needs).message)
    else:
        _lags = pl.DataFrame(_m.detail["by_lag"])
        _view = mo.ui.altair_chart(
            alt.Chart(_lags)
            .mark_bar()
            .encode(
                x=alt.X("lag:O", title="lag (days): adherence today → output later"),
                y=alt.Y("r:Q", title="correlation"),
                color=alt.condition(
                    alt.datum.r > 0,
                    alt.value(theme.series[0]),
                    alt.value(theme.series[1]),
                ),
                tooltip=["lag:O", "r:Q", "n:Q"],
            )
            .properties(height=160)
        )
    _view
    return


@app.cell
def plot_cumulative(F, alt, frames, mo):
    _g = frames.gate("cumulative_output", F["n_days"])
    if not _g.open:
        _view = mo.md(_g.message)
    else:
        _view = mo.ui.altair_chart(
            alt.Chart(F["cumulative"])
            .mark_area(opacity=0.7, line=True)
            .encode(
                x=alt.X("day:T", title=None),
                y=alt.Y("cumulative:Q", title="cumulative forum posts"),
                tooltip=["day:T", "cumulative:Q", "rate:Q", "band:N"],
            )
            .properties(height=180)
        )
    _view
    return


@app.cell
def _diag_header(mo):
    mo.md("""
    ## Diagnostics

    "
        "The table from `docs/06-diagnostics.md`, as far as N allows — including "
        "the modes Wiggins has no vocabulary for, because his systems always run "
        "and a daily practice can simply fail to.
    """)
    return


@app.cell
def diagnostics_panel(diag, mo, pl):
    _blocks = []

    _alloc = diag["measures"]["allocation_vs_capacity"]
    if _alloc.ok:
        _table = pl.DataFrame(
            [
                {"activity": _a, **{_k: _v for _k, _v in _s.items() if _k != "allocation_share"}}
                for _a, _s in _alloc.value.items()
            ]
        )
        _blocks.append(
            mo.vstack([
                mo.md(
                    "**Failure kind** — allocation wants protected time; capacity "
                    "wants drills. Same CSF label, opposite remedies."
                ),
                mo.ui.table(_table, selection=None),
            ])
        )
    else:
        _blocks.append(mo.md(f"**Failure kind** — {_alloc}"))

    _dorm = diag["measures"]["dormancy"]
    if _dorm.ok:
        _blocks.append(
            mo.vstack([
                mo.md(
                    "**Dormancy** — consecutive days a channel was never attempted. "
                    "Not uninspiration: nothing was tried, so nothing failed to be reached."
                ),
                mo.ui.table(
                    pl.DataFrame(
                        [{"activity": _a, **_s} for _a, _s in _dorm.value.items()]
                    ),
                    selection=None,
                ),
            ])
        )

    for _key, _label in (
        ("aberration", "**Productive aberration** — output arriving without Reveal, i.e. from outside the rules"),
        ("adherence_without_production", "**Adherence without production** — the quiet precursor to stagnation"),
    ):
        _m = diag["measures"][_key]
        _blocks.append(
            mo.md(f"{_label}\n\n`{_m.value if _m.ok else 'insufficient data'}`")
        )

    mo.vstack(_blocks)
    return


@app.cell
def _inference_header(mo):
    mo.md("""
    ## Inference — what the system believes, and how strongly

    Everything above is observation and gated judgement. This chapter is
    *belief*: seed-pinned Bayesian fits over the cumulative record, snapshotted
    daily into the graph. Three readings matter throughout:

    - **the interval is the honest part** — a wide one is visibility of
      uncertainty, not a claim;
    - **red means the sampler distrusts itself** (R̂, effective sample size,
      divergences) — stored as a fact about the fit, never read as a result;
    - **verdicts gate separately**: a posterior is always shown, but the
      published hypotheses only earn `supported`/`not supported` once their
      evidence gate clears. Until then they say *not testable yet*, however
      the probability leans.
    """)
    return


@app.cell
def posterior_forest(alt, loaders, mo, pl, theme):
    _md = mo.md(
        "*Posteriors read the real graph; fixture mode shows the real "
        "snapshot too (fabricated practice has no posterior history).*"
    )
    _post = loaders.posteriors()
    if _post.is_empty():
        _view = mo.md("*No posterior snapshots yet — run `flow sync`.*")
    else:
        _last_day = _post["day"].max()
        _last = _post.filter(
            (pl.col("day") == _last_day)
            & (
                pl.col("measure").str.starts_with("adherence:")
                | pl.col("measure").str.starts_with("p_never_started:")
            )
        )
        _base = alt.Chart(_last)
        _view = mo.ui.altair_chart(
            (
                _base.mark_rule(strokeWidth=2).encode(
                    x=alt.X("ci_low:Q", title="rate / probability (90% CI)",
                            scale=alt.Scale(domain=[0, 1])),
                    x2="ci_high:Q",
                    y=alt.Y("measure:N", title=None),
                    color=alt.Color(
                        "trusted:N", title="sampler trusts it",
                        scale=alt.Scale(domain=[True, False],
                                        range=[theme.accent, theme.bad]),
                    ),
                )
                + _base.mark_point(filled=True, size=60).encode(
                    x="mean:Q", y="measure:N", color="trusted:N"
                )
            ).properties(height=280, title=f"Posterior snapshot — {_last_day}")
        )
    mo.vstack([_md, _view])
    return


@app.cell
def _survival_header(mo):
    mo.md("""
    ### Time-to-start survival — where the day actually goes

    *What's asking:* how long does each mode wait before being touched — and
    how often is it never touched at all? *How:* a Kaplan-Meier product-limit
    curve per mode over minutes from the card appearing (06:00) to first
    touch, with never-started days **censored at the drain** (04:00, minute
    1320) rather than dropped. *How to read:* the curve is "share still
    untouched at this minute"; where it flattens without reaching zero, **the
    plateau height is the allocation-failure probability** — the share of days
    that mode is simply never reached. *What would change it:* a mode whose
    curve drops early is being reached for first; one with a high plateau has
    an allocation problem no amount of drilling will fix.
    """)
    return


@app.cell
def survival_curves(alt, frames, mo, pl, rows, theme):
    _g = frames.gate("start_latency", sum(1 for r in rows if r.started_at))
    _t_max = 1320.0
    _records = []
    for _mode in sorted({r.activity for r in rows}):
        _mine = [r for r in rows if r.activity == _mode
                 and r.outcome != "never_appeared"]
        _events = sorted(
            (min(float(r.minutes_to_start), _t_max - 1), True)
            if r.minutes_to_start is not None else (_t_max, False)
            for r in _mine
        )
        _n = len(_events)
        if _n == 0:
            continue
        _surv, _at_risk = 1.0, _n
        _records.append({"mode": _mode, "minutes": 0.0, "surviving": 1.0})
        for _t, _observed in _events:
            if _observed:
                _surv *= (_at_risk - 1) / _at_risk
            _at_risk -= 1
            _records.append({"mode": _mode, "minutes": _t, "surviving": _surv})
        _records.append({"mode": _mode, "minutes": _t_max, "surviving": _surv})
    if not _records:
        _view = mo.md("*No started days yet.*")
    else:
        _view = mo.ui.altair_chart(
            alt.Chart(pl.DataFrame(_records))
            .mark_line(interpolate="step-after")
            .encode(
                x=alt.X("minutes:Q", title="minutes since the cards appeared"),
                y=alt.Y("surviving:Q", title="share still untouched",
                        scale=alt.Scale(domain=[0, 1])),
                color=alt.Color("mode:N", title=None,
                                scale=alt.Scale(range=list(theme.series))),
            )
            .properties(height=260)
        )
    mo.vstack([
        mo.md("" if _g.open else f"*{_g.message} — curves shown as "
              "visibility; read no ranking from them yet.*"),
        _view,
    ])
    return


@app.cell
def _evolution_header(mo):
    mo.md("""
    ### The evolving posterior — belief over time

    *What's asking:* how has the system's belief in the practice-level
    completion rate moved as evidence accumulated? *How:* each day's snapshot
    is one interval; laid side by side they are the credible band narrowing
    (or refusing to). *How to read:* the band should tighten as days
    accumulate; a band that jumps marks a genuine shift in the practice, not
    noise — that is what "rolling Bayesian" buys.
    """)
    return


@app.cell
def posterior_evolution(alt, loaders, mo, pl, theme):
    _hist = loaders.posteriors()
    _days = 0 if _hist.is_empty() else _hist["day"].n_unique()
    if _days < 7:
        _view = mo.md(
            f"**Not yet** — {_days} snapshot day(s) of the 7 this chart needs. "
            "It will draw itself as the record accumulates; each sync adds one "
            "column of belief."
        )
    else:
        _series = _hist.filter(pl.col("measure") == "adherence:practice")
        _base = alt.Chart(_series)
        _view = mo.ui.altair_chart(
            (
                _base.mark_area(opacity=0.25, color=theme.accent).encode(
                    x=alt.X("day:T", title=None),
                    y=alt.Y("ci_low:Q", title="practice completion rate",
                            scale=alt.Scale(domain=[0, 1])),
                    y2="ci_high:Q",
                )
                + _base.mark_line(color=theme.accent).encode(
                    x="day:T", y="mean:Q"
                )
            ).properties(height=220)
        )
    _view
    return


@app.cell
def _closing(mo):
    mo.md("""
    ---
    *The deep guide to the graph these views read from is
    `graph.py` in this folder; the theory is
    `docs/08-creative-systems-practice.md`.*
    """)
    return


if __name__ == "__main__":
    app.run()
