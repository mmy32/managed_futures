# Preserved data policy: status and endpoint issue

**The 1976–2014 comparison stops on missing held returns.** The simulator preserves the existing endpoint rules and fails explicitly; full-period portfolio metrics are unavailable under this policy.

For the completed, clearly labeled conditional research, read [ENDPOINT_SENSITIVITY.md](../reports/qps_baseline/ENDPOINT_SENSITIVITY.md) or [offline HTML](../reports/qps_baseline/ENDPOINT_SENSITIVITY.html). That report uses March 27 as an unverified March 1997 endpoint for four instruments.

## What blocks evaluation

| Portfolio | Simulator failure |
| --- | ---: |
| TREND | Missing held return at 1997-03: ['DT', 'GS', 'LX'] |
| STATIC | Missing held return at 1997-03: ['DT', 'GS', 'LX'] |

DT, GS and LX are held in March 1997. Their last March observation is March 27, four calendar days before the March 31 target. The preserved three-day freshness rule rejects it, leaving March and April returns missing. SS has the same gap but is ineligible then. Historical venue closure and vendor identity remain unverified.

The [candidate return table](../reports/qps_baseline/output/risk/proposed_endpoint_returns.csv) contains the eight implied March/April returns. They are not applied to primary inputs. The separate sensitivity uses exact observed closes in a copy of the return matrix, then recomputes the full trading path. [Evidence and decision note](ENDPOINT_DECISION.md).

## Sample and validation

The requested 468 months remain January 1976–December 2014. January 1976 has 7 eligible instruments versus the required 10, so it is flat. First trading month: 1976-02.

85 tests pass. The archived 2000–2014 refactor replay is independent of the endpoint sensitivity. [Validation record](../reports/qps_baseline/output/risk/validation.json) · [Sample audit](../reports/qps_baseline/output/risk/sample_audit.json) · [Run status](../reports/qps_baseline/output/risk/run_status.json).

## Reproduce

- `python scripts/run_research.py`: preserves the data policy, refreshes this status report, and exits with code 2 on missing held returns.
- `python scripts/run_research.py --endpoint-sensitivity`: also runs the conditional scenario and refreshes its report; exits with code 0 when that requested scenario completes.
- `python scripts/run_research.py --validate`: runs synthetic checks without course data.

Start with [README.md](../README.md) for the files to review and share. Detailed data audits remain in `docs/`; raw inputs stay local.
