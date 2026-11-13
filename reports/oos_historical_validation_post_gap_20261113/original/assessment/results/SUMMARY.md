# Baseline and HRP evaluation

Evaluation: 2009-04–2014-12; 2 bps ordinary trading costs and 10% trading bands.
Both portfolios start flat; the final month includes liquidation. Cash income is zero.
The return/volatility ratio uses a zero rate. Execution is an idealized prior-endpoint proxy; lag two is not a next-session fill.

Data provenance and prior access have not been independently verified by this runner.

| Information lag | Portfolio | Annual net mean | Volatility | Zero-rate ratio | Max drawdown | Annual turnover |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | baseline | 5.31% | 8.28% | 0.641 | -9.07% | 9.36× |
| 1 | enhanced | 4.87% | 5.89% | 0.827 | -5.60% | 13.66× |
| 2 | baseline | 5.37% | 8.19% | 0.655 | -8.21% | 9.39× |
| 2 | enhanced | 3.94% | 6.47% | 0.609 | -7.91% | 13.55× |

Annualized paired mean differences, HRP minus baseline (bps of NAV/year):

| Information lag | Gross change | Cost savings | Net change |
| --- | ---: | ---: | ---: |
| 1 | -35.00 | -8.61 | -43.61 |
| 2 | -134.02 | -8.32 | -142.35 |

These are arithmetic mean differences, not differences in CAGR.
Lag 1 is primary; lag 2 is the declared information-delay sensitivity.
Pre-evaluation nonflat shadow observations: {'1': 37, '2': 36}.
Data provenance is declared in `preparation.json`; the preparation timestamp does not independently certify preregistration or point-in-time vendor history.
