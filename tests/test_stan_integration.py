"""The sampler, held to the algebra — and the snapshot, held to the graph.

Integration-marked: needs CmdStan installed and (for the second test) Neo4j
populated. Seed-pinned throughout, so a pass is reproducible.
"""

from __future__ import annotations

import pytest

from flow_analysis.metrics.inference import run_model, summarise_draws

pytestmark = pytest.mark.integration


def test_stan_reproduces_the_conjugate_posterior():
    """Beta(2,2) prior + Binomial(20, k=13) has posterior Beta(15, 9).

    The sampler must land on the closed form. If this drifts, nothing else the
    engine reports can be trusted either.
    """
    fit = run_model("beta_binomial", {"n": 20, "k": 13, "prior_a": 2.0, "prior_b": 2.0})
    assert fit.trusted, (fit.rhat_max, fit.ess_min, fit.divergences)
    posterior = summarise_draws(fit.draws["theta"])
    closed_form = 15 / 24
    assert abs(posterior["mean"] - closed_form) < 0.01


def test_poisson_rate_reproduces_the_conjugate_posterior():
    """Gamma(2,2) prior + 5 events in 3 months has posterior Gamma(7, 5).

    Same calibration logic as the beta-binomial: the sampler must land on
    the closed form, mean (a + y) / (b + t) = 7/5 = 1.4 events/month.
    """
    fit = run_model(
        "poisson_rate",
        {"y": 5, "exposure_months": 3.0, "prior_a": 2.0, "prior_b": 2.0},
    )
    assert fit.trusted, (fit.rhat_max, fit.ess_min, fit.divergences)
    posterior = summarise_draws(fit.draws["lambda"])
    # Gamma(7,5) has sd ≈ 0.53, so Monte-Carlo error on the mean is ~0.015
    # at this ESS — the tolerance is ~3 MCSE, not the beta model's 0.01
    # (whose posterior is far narrower).
    assert abs(posterior["mean"] - 1.4) < 0.05


def test_hierarchical_model_pools_thin_modes_toward_the_practice():
    """Pooling is the point of the hierarchy.

    A mode with 2 observations shrinks toward the practice mean; one with 200
    stays close to its own data.
    """
    fit = run_model(
        "adherence_hierarchical",
        {"M": 2, "n": [200, 2], "k": [160, 0]},
    )
    assert fit.trusted
    strong = summarise_draws(fit.draws["theta"][:, 0])
    thin = summarise_draws(fit.draws["theta"][:, 1])
    assert abs(strong["mean"] - 0.8) < 0.05
    # raw rate is 0.0; pooling must pull it visibly toward the practice level
    assert thin["mean"] > 0.05


def test_todays_posterior_snapshot_is_in_the_graph():
    from flow_analysis.graph import loaders

    frame = loaders.posteriors()
    assert not frame.is_empty()
    last = frame.filter(frame["day"] == frame["day"].max())
    measures = set(last["measure"].to_list())
    assert "adherence:practice" in measures
    assert any(m.startswith("contract:") for m in measures)
    # every row carries its diagnostics
    assert last["rhat_max"].null_count() == 0
    assert last["trusted"].null_count() == 0
