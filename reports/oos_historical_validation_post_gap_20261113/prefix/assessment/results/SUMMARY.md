# Baseline and HRP evaluation

Evaluation: 2009-04–2012-12; 2 bps ordinary trading costs and 10% trading bands.
Both portfolios start flat; the final month includes liquidation. Cash income is zero.
The return/volatility ratio uses a zero rate. Execution is an idealized prior-endpoint proxy; lag two is not a next-session fill.

Data provenance and prior access have not been independently verified by this runner.

| Information lag | Portfolio | Annual net mean | Volatility | Zero-rate ratio | Max drawdown | Annual turnover |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | baseline | 2.35% | 9.45% | 0.248 | -9.07% | 8.72× |
| 1 | enhanced | 2.83% | 6.62% | 0.428 | -5.60% | 12.61× |
| 2 | baseline | 2.75% | 9.14% | 0.301 | -8.21% | 8.62× |
| 2 | enhanced | 1.41% | 7.03% | 0.201 | -7.91% | 12.43× |

Annualized paired mean differences, HRP minus baseline (bps of NAV/year):

| Information lag | Gross change | Cost savings | Net change |
| --- | ---: | ---: | ---: |
| 1 | +56.48 | -7.80 | +48.68 |
| 2 | -125.98 | -7.63 | -133.61 |

These are arithmetic mean differences, not differences in CAGR.
Lag 1 is primary; lag 2 is the declared information-delay sensitivity.
Pre-evaluation nonflat shadow observations: {'1': 37, '2': 36}.
Data provenance is declared in `preparation.json`; the preparation timestamp does not independently certify preregistration or point-in-time vendor history.
