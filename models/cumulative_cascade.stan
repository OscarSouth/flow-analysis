// Count intensity over long windows, against cumulative upstream history.
//
// The cascade doctrine (docs/06-diagnostics.md, extension 7): stages link
// through CUMULATIVE intensities at long horizons, never event lags. Run as
//   production windows ~ cumulative adherence   (confounded — say so, always)
//   reception  windows ~ cumulative production  (cumulative horizons only)
//
// Negative binomial rather than Poisson: reception especially is bursty, and
// a Poisson would manufacture false certainty out of overdispersion.
//
// Pre-registered priors (2026-08-18):
//   beta0 ~ normal(0, 2)     baseline log-intensity, wide
//   beta1 ~ normal(0, 1)     effect of standardised cumulative history
//   phi   ~ gamma(2, 0.5)    overdispersion, weakly informative
data {
  int<lower=1> W;                      // windows
  array[W] int<lower=0> y;             // events in each window
  vector<lower=0>[W] exposure_days;    // window lengths
  vector[W] cum_history;               // standardised cumulative upstream
}
parameters {
  real beta0;
  real beta1;
  real<lower=0> phi;
}
model {
  beta0 ~ normal(0, 2);
  beta1 ~ normal(0, 1);
  phi ~ gamma(2, 0.5);
  y ~ neg_binomial_2_log(beta0 + beta1 * cum_history + log(exposure_days), phi);
}
