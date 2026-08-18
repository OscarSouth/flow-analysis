// Single-rate Beta-Binomial. Two jobs:
//   1. the calibration model: with prior Beta(a, b) the posterior is exactly
//      Beta(a + k, b + n - k), so the sampler's posterior mean must match
//      (a + k) / (a + b + n) — an integration test holds Stan to the algebra;
//   2. the workhorse for simple conditional contrasts (completion of mode m on
//      days another mode was done vs missed), run once per arm.
data {
  int<lower=0> n;              // trials
  int<lower=0, upper=n> k;     // successes
  real<lower=0> prior_a;       // pre-registered Beta prior
  real<lower=0> prior_b;
}
parameters {
  real<lower=0, upper=1> theta;
}
model {
  theta ~ beta(prior_a, prior_b);
  k ~ binomial(n, theta);
}
