# Baseline and HRP evaluation

Evaluation: 2009-04–2014-12; 2 bps ordinary trading costs and 10% trading bands.
Both portfolios start flat; the final month includes liquidation. Cash income is zero.
The return/volatility ratio uses a zero rate. Execution is an idealized prior-endpoint proxy; lag two is not a next-session fill.

Data provenance and prior access have not been independently verified by this runner.

| Information lag | Portfolio | Annual net mean | Volatility | Zero-rate ratio | Max drawdown | Annual turnover |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | baseline | -0.88% | 9.12% | -0.096 | -23.30% | 12.26× |
| 1 | enhanced | -3.16% | 7.73% | -0.408 | -28.69% | 17.65× |
| 2 | baseline | -6.63% | 9.43% | -0.703 | -42.01% | 12.24× |
| 2 | enhanced | -8.52% | 8.16% | -1.045 | -45.63% | 17.31× |

Annualized paired mean differences, HRP minus baseline (bps of NAV/year):

| Information lag | Gross change | Cost savings | Net change |
| --- | ---: | ---: | ---: |
| 1 | -217.15 | -10.76 | -227.91 |
| 2 | -178.86 | -10.14 | -189.00 |

These are arithmetic mean differences, not differences in CAGR.
Lag 1 is primary; lag 2 is the declared information-delay sensitivity.
Pre-evaluation nonflat shadow observations: {'1': 37, '2': 36}.
Data provenance is declared in `preparation.json`; the preparation timestamp does not independently certify preregistration or point-in-time vendor history.
