// Gamma-Poisson event rate, for the publication-cadence contract (c9).
// Pre-registered 2026-08-19: lambda ~ Gamma(2, 2) on the *monthly* rate —
// mean 1.0/month, weakly informative — with exposure measured in months so
// the posterior reads directly against the "at least one per month" floor.
//
// Conjugacy is the calibration hook: with prior Gamma(a, b) and y events in
// exposure t, the posterior is exactly Gamma(a + y, b + t), so the sampler's
// posterior mean must match (a + y) / (b + t) — an integration test holds
// Stan to the algebra, mirroring beta_binomial.stan.
data {
  int<lower=0> y;              // events in the window
  real<lower=0> exposure_months; // window length, months
  real<lower=0> prior_a;       // pre-registered Gamma prior (shape)
  real<lower=0> prior_b;       // pre-registered Gamma prior (rate)
}
parameters {
  real<lower=0> lambda;        // events per month
}
model {
  lambda ~ gamma(prior_a, prior_b);
  y ~ poisson(lambda * exposure_months);
}
