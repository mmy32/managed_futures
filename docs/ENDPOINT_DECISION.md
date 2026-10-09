# March 1997 endpoint decision — 8 October 2026

A separate conditional sensitivity now completes the requested 1976–2014 comparison. **The preserved primary data policy is unchanged and its backtest still stops on missing held returns.** The sensitivity is a way to inspect the proposed assumption, not a certification of the missing venue evidence.

## Evidence and remaining uncertainty

DT, GS, LX and SS each have an observed close on **27 March 1997**, and no later March observation in the supplied files. The last weekday of that month is 31 March. Under the preserved rule, the four-calendar-day age exceeds the three-day freshness limit, making both the March and April returns missing. In March, DT, GS and LX are held; SS is ineligible because of earlier history gaps. Both trend and STATIC therefore fail explicitly.

A contemporaneous public record confirms the Easter timing: East Ayrshire Council's 13 June 1996 minutes list **28 and 31 March 1997** as Easter holidays in Appendix 10, PDF page 13 / printed page 944. This is evidence about the council holiday calendar, **not the LIFFE or DTB trading calendar**. [Original council minutes and calendar](https://docs.east-ayrshire.gov.uk/crpadmmin/JUNE96/JUNE%2096/POLICY%20AND%20RESOURCES%20COMMITTEE%20-%2013%20JUNE%201996.pdf).

The follow-up search covered historical LIFFE/DTB calendars, 1997 Easter trading notices and contemporaneous records. It did not establish the exact venue closures or vendor series identity. Inferring that March 27 was the final relevant trading session is plausible from the holiday pattern and supplied observations, but remains an **explicit research assumption**. General modern exchange calendars or cash-market closure reports do not certify the 1997 futures venues.

## Narrow assumption evaluated

For these four instruments only, use the actual observed closes on:

- 28 February 1997 as the preceding endpoint;
- 27 March 1997 as the assumed March endpoint;
- 30 April 1997 as the following endpoint.

March return is March 27 close / February 28 close − 1; April return is April 30 close / March 27 close − 1. This adds exactly eight previously missing monthly cells. [Exact prices and return changes](../reports/qps_baseline/output/endpoint_sensitivity/endpoint_changes.csv) are exported with `applied_to_primary=False` and `applied_to_sensitivity=True`.

The implementation does not alter the input data, relax freshness globally, interpolate prices, fill an unknown return with zero, remove a held instrument based on its current return, or change strategy/risk settings. It refuses to overwrite existing observed returns or substitute a neighboring date when a declared exact price is missing. Configuration is in [endpoint_sensitivity.json](../config/endpoint_sensitivity.json).

The modified returns affect subsequent eligibility, signals and covariance as well as the March/April P&L. The entire strategy is rerun through December 2014; this is not a patch to a completed ledger. The independent RL/ER schedule, duplicate/identity exclusions, trading bands, all costs and after-cost limits are shared with the preserved run.

## Results and interpretation

The [conditional report](../reports/qps_baseline/ENDPOINT_SENSITIVITY.md) and [standalone HTML](../reports/qps_baseline/ENDPOINT_SENSITIVITY.html) contain all 12 comparisons, four-class statistics, rank/HAC diagnostics, alpha, risk plots and class attribution. All 468 months are retained; the unchanged ten-instrument minimum makes January 1976 flat. Results explicitly identify the unverified endpoint assumption.

The scenario enables an internally consistent research calculation. It does not prove the original monthly blanks were mistakes or establish performance under the unresolved primary data policy. The 2000–2014 regression replay remains based on the preserved inputs; it validates the refactor independently of this sensitivity.

To adopt a calendar correction as verified, obtain the contemporaneous relevant venue calendar and vendor contract/venue identity, or vendor-certified endpoint returns, for these series. Without that evidence, the scenario may be used only as labeled conditional research unless an explicit policy decision adopts the assumption. No email or external request has been sent.

## Reproduce

```sh
python scripts/run_research.py --endpoint-sensitivity
```

The command validates code, refreshes the preserved primary attempt and its report, then independently generates `ENDPOINT_SENSITIVITY.md` / `.html` and `output/endpoint_sensitivity/`. Exit code 0 means the requested sensitivity completed; `output/risk/run_status.json` still records the primary data blocker. A normal `python scripts/run_research.py` continues to enforce the preserved policy and returns code 2 on this data blocker. Add `--full` to rebuild the source audits too.
