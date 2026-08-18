// Time-to-start within the flow day, right-censored at the drain.
//
// A card that was never started is not a missing latency — it is a latency
// that exceeded the day. Treating it as censored is what makes the survival
// plateau equal the allocation-failure probability, and what the conditional
// medians the grid stores cannot do (they condition on having started).
//
// Pre-registered priors (2026-08-18):
//   alpha ~ gamma(2, 1)               shape, weakly informative around 1-2
//   sigma ~ lognormal(log(240), 1)    scale centred on four hours, wide
data {
  int<lower=0> N_obs;                  // started: minutes to first touch
  int<lower=0> N_cens;                 // never started: censored at t_max
  vector<lower=0>[N_obs] t_obs;
  real<lower=0> t_max;                 // minutes from refill to drain
}
parameters {
  real<lower=0> alpha;                 // Weibull shape
  real<lower=0> sigma;                 // Weibull scale
}
model {
  alpha ~ gamma(2, 1);
  sigma ~ lognormal(log(240), 1);
  if (N_obs > 0) {
    t_obs ~ weibull(alpha, sigma);
  }
  // Each censored day contributes P(T > t_max).
  target += N_cens * weibull_lccdf(t_max | alpha, sigma);
}
generated quantities {
  real median_minutes = sigma * pow(log(2), inv(alpha));
  real p_never_started = exp(weibull_lccdf(t_max | alpha, sigma));
}
