# Stan models — pre-registered commitments

Each file is the declarative form of one inference: data block, priors,
likelihood, generated quantities. **Priors here are pre-registered** — they are
written before the data that tests them and recorded as `(:Meta:Hypothesis)`
entities; changing one is an E-transformation and rides a Transformation record.

Diagnostics (R-hat, ESS, divergences) are stored on every `(:Fct:Posterior)`
node; a posterior that fails them is marked `trusted: false` and never quietly
used.

| model | question | doctrine guardrail |
|---|---|---|
| `beta_binomial.stan` | single completion rate; also the calibration model — its posterior mean must match the conjugate closed form | — |
| `adherence_hierarchical.stan` | per-mode completion with partial pooling — is this mode different? | pooling is the honest answer to 5 modes × small N |
| `latency_survival.stan` | time-to-start within the day, censored at the drain | the survival plateau IS the allocation-failure probability |
| `cumulative_cascade.stan` | count intensity over long windows against cumulative history | practice→production allowed with the confounding caveat; production→reception **cumulative horizons only**, never event-lag |
