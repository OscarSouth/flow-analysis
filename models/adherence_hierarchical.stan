// Per-mode completion with partial pooling.
//
// Five modes at small N is exactly what pooling is for: each mode's rate is
// drawn from a practice-level distribution, so a mode with thin data shrinks
// toward the practice mean instead of swinging on a handful of days — and
// "is this mode genuinely different?" gets an honest posterior answer.
//
// Pre-registered priors (2026-08-18):
//   mu    ~ beta(2, 2)        practice-level completion, weakly informative,
//                             centred on 1/2, vanishing at the impossible edges
//   kappa ~ gamma(2, 0.1)     pooling strength, wide — the data decides
data {
  int<lower=1> M;              // modes (five, but not hard-coded)
  array[M] int<lower=0> n;     // observed days per mode
  array[M] int<lower=0> k;     // completions per mode
}
parameters {
  real<lower=0, upper=1> mu;   // practice-level completion
  real<lower=0> kappa;         // concentration: how alike the modes are
  vector<lower=0, upper=1>[M] theta;  // per-mode completion
}
model {
  mu ~ beta(2, 2);
  kappa ~ gamma(2, 0.1);
  theta ~ beta(mu * kappa, (1 - mu) * kappa);
  k ~ binomial(n, theta);
}
generated quantities {
  // Which mode is currently weakest, as a posterior quantity rather than a
  // point-estimate ranking that flips on one day's data.
  int<lower=1, upper=M> weakest = 1;
  {
    real lowest = theta[1];
    for (m in 2:M) {
      if (theta[m] < lowest) {
        lowest = theta[m];
        weakest = m;
      }
    }
  }
}
