"""Lightweight Poisson helpers shared by the goals model and Monte Carlo engine."""
import math


def poisson_pmf(k, lam):
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def poisson_sample(rng, lam):
    """Knuth's algorithm."""
    L = math.exp(-lam)
    k, p = 0, 1.0
    while True:
        k += 1
        p *= rng.random()
        if p <= L:
            return k - 1
