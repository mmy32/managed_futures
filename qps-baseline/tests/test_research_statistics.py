"""Verify definitions that affect the extended-period presentation."""
import numpy as np
import pandas as pd
import pytest
from scipy.stats import spearmanr
import statsmodels.api as sm
from statsmodels.stats.sandwich_covariance import cov_hac
from backtest import simulate, sharpe_ratio, performance
from research_statistics import (class_portfolios, rank_autocorrelation, class_attribution,
                                 eligibility, sample_audit, risk_diagnostics)
from risk_model import build_forecasts, BandPolicy
from test_risk_model import data, settings


def test_class_statistics_use_portfolio_series_and_keep_absent_class_missing():
    index = pd.period_range('2000-01', periods=5, freq='M')
    returns = pd.DataFrame({'A': [.1, -.1, .2, -.2, .1], 'B': [-.1, .1, -.1, .1, -.1]}, index=index)
    meta = pd.DataFrame({'AssetClass': ['EQ', 'EQ']}, index=returns.columns)
    allowed = returns.notna()
    allowed.loc[index[0], 'B'] = False
    series, counts, stats = class_portfolios(returns, allowed, meta, index)
    expected = pd.Series([.1, 0, .05, -.05, 0], index=index)
    np.testing.assert_allclose(series.EQ, expected)
    row = stats.set_index('asset_class').loc['EQ']
    assert row.vol_ann == pytest.approx(expected.std(ddof=1)*np.sqrt(12))
    assert row.instrument_observations == 9
    assert series.FI.isna().all() and counts.FI.eq(0).all()
    assert row.sharpe == pytest.approx(sharpe_ratio(expected))


def test_current_missingness_does_not_silently_reweight_descriptive_class():
    r, meta, base = data()
    allowed = eligibility(r, meta, base, settings())
    month = pd.Period('2000-01', 'M')
    r.loc[month, 'A'] = np.nan
    series, _, stats = class_portfolios(r, allowed, meta, pd.period_range(month, month, freq='M'))
    assert pd.isna(series.loc[month, 'EQ'])
    assert stats.set_index('asset_class').loc['EQ', 'missing_eligible_observations'] == 1


def test_exclusions_and_future_mutations_preserve_past_class_universe():
    r, meta, base = data()
    base['exclude_from_strategy'] = {'A': 'duplicate'}
    allowed = eligibility(r, meta, base, settings())
    month = pd.Period('2000-06', 'M')
    modified = r.copy(); modified.loc[month:] = np.nan
    altered = eligibility(modified, meta, base, settings())
    assert not allowed.A.any()
    pd.testing.assert_frame_equal(allowed.loc[:month], altered.loc[:month])


def test_autocorrelation_shifts_calendar_before_dropping_missing_pairs():
    rng = np.random.default_rng(89)
    index = pd.period_range('1976-01', periods=100, freq='M')
    s = pd.Series(rng.normal(size=100), index=index)
    s.iloc[[2, 4, 15, 60]] = np.nan
    q = rank_autocorrelation(s.to_frame('EQ'))
    for row in q.itertuples():
        pairs = pd.concat([s, s.shift(row.lag)], axis=1).dropna()
        assert row.matched_months == len(pairs)
        assert row.rho == pytest.approx(spearmanr(pairs.iloc[:, 0], pairs.iloc[:, 1]).statistic)
    compressed = s.dropna()
    assert q.iloc[0].matched_months != len(compressed)-1
    with pytest.raises(ValueError, match='intact monthly calendar'):
        rank_autocorrelation(s.to_frame('EQ').drop(index[2]))


def test_rank_hac_matches_direct_sandwich_for_contiguous_pairs():
    rng = np.random.default_rng(93)
    s = pd.Series(rng.normal(size=120), index=pd.period_range('1976-01', periods=120, freq='M'))
    q = rank_autocorrelation(s.to_frame('EQ'))
    for row in q.itertuples():
        pair = pd.concat([s.rename('y'), s.shift(row.lag).rename('x')], axis=1).dropna().rank()
        z = (pair-pair.mean())/pair.std(ddof=1)
        fit = sm.OLS(z.y, sm.add_constant(z.x)).fit()
        expected = np.sqrt(cov_hac(fit, nlags=row.lag, use_correction=True)[1, 1])
        assert row.se == pytest.approx(expected)


def test_rank_hac_keeps_calendar_gaps_in_score_lags():
    rng = np.random.default_rng(6)
    s = pd.Series(rng.normal(size=120), index=pd.period_range('1976-01', periods=120, freq='M'))
    s.iloc[::4] = np.nan
    row = rank_autocorrelation(s.to_frame('EQ'), lags=[1]).iloc[0]
    # Valid pairs occur in runs of two separated by gaps; calendar HAC differs from compressed HAC.
    pair = pd.concat([s.rename('y'), s.shift(1).rename('x')], axis=1).dropna().rank()
    z = (pair-pair.mean())/pair.std(ddof=1)
    fit = sm.OLS(z.y, sm.add_constant(z.x)).fit()
    compressed_se = np.sqrt(cov_hac(fit, nlags=1, use_correction=True)[1, 1])
    assert abs(row.se-compressed_se) > 1e-5


def test_actual_source_trades_and_liquidation_costs_reconcile_by_class():
    index = pd.period_range('2000-01', periods=3, freq='M')
    r = pd.DataFrame({'A': [.1, -.1, .02], 'B': [-.02, .04, .01]}, index=index)
    target = r*0 + [.5, -.2]
    source = pd.DataFrame({'A': ['RL', 'ER', 'ER'], 'B': ['B', 'B', 'B']}, index=index)
    details = {}
    ledger, gross = simulate(r, target, 10, source, instrument_details=details)
    # Second month A closes the drifted RL notional and opens the ER target.
    prior = .5*1.1/(1+ledger.net_return.iloc[0])
    assert details['cost'].A.iloc[1] == pytest.approx(.001*(prior+.5))
    final_rebalance = abs(.5 - .5*.9/(1+ledger.net_return.iloc[1]))
    assert details['cost'].A.iloc[-1] == pytest.approx(.001*(final_rebalance+.5*1.02))
    np.testing.assert_allclose(details['cost'].sum(axis=1), ledger.cost)
    meta = pd.DataFrame({'AssetClass': ['EQ', 'FI']}, index=r.columns)
    covariance = {month: np.eye(2)*.04 for month in index}
    ledger['forecast_vol_annual'] = np.sqrt(.04*(.5**2+.2**2))
    net, exposure, risk, summary = class_attribution(ledger, gross, details, covariance, meta)
    np.testing.assert_allclose(net.sum(axis=1), ledger.net_return)
    np.testing.assert_allclose(risk.sum(axis=1), ledger.forecast_vol_annual)
    assert summary.linked_cumulative_contribution.sum() == pytest.approx(ledger.nav_end.iloc[-1]-1)


def test_funded_sharpe_subtracts_matching_rf_exactly_once():
    index = pd.period_range('2000-01', periods=4, freq='M')
    rf = pd.Series([.002, .003, .001, .004], index=index)
    excess = pd.Series([.01, -.02, .03, .04], index=index)
    assert sharpe_ratio(excess+rf, rf) == pytest.approx(excess.mean()/excess.std(ddof=1)*np.sqrt(12))
    assert sharpe_ratio(excess) == pytest.approx(sharpe_ratio(excess+rf, rf))
    with pytest.raises(ValueError, match='Missing matching'):
        sharpe_ratio(excess+rf, rf.iloc[1:])


def test_insufficient_start_breadth_preserves_dates_and_flat_positions():
    r, meta, base = data()
    base['minimum_instruments'] = 10
    allowed = eligibility(r, meta, base, settings())
    audit = sample_audit(r, allowed, base)
    assert not audit['start_ready'] and audit['eligible_at_start'] == 8
    assert audit['first_investable_month'] is None
    targets, covariance, _ = build_forecasts(r, meta, base, settings())
    assert targets['trend'].eq(0).all().all()
    assert str(targets['trend'].index[0]) == base['start']


def test_trailing_risk_uses_forecasts_for_same_36_months():
    r, meta, base = data()
    targets, covariance, _ = build_forecasts(r, meta, base, settings())
    ledger, _ = simulate(r.loc[base['start']:base['end']], targets['trend'], 5,
                         position_policy=BandPolicy(covariance, settings(), .1))
    timeline, summary = risk_diagnostics(ledger)
    assert timeline.forecast_rms_36m.iloc[:35].isna().all()
    assert timeline.forecast_rms_36m.iloc[35] == pytest.approx(np.sqrt(ledger.forecast_vol_annual.iloc[:36].pow(2).mean()))
    assert timeline.realized_gross_vol_36m.iloc[35] == pytest.approx(ledger.gross_return.iloc[:36].std(ddof=1)*np.sqrt(12))
    assert performance(ledger)['sharpe'] == pytest.approx(sharpe_ratio(ledger.net_return))


def test_comparison_runner_exports_all_frozen_pairs_and_reconciles(tmp_path, monkeypatch):
    import run_risk_research as runner
    r, meta, base = data()
    config = dict(settings(), bands=[0., .1], cost_scenarios_bps=[0, 5, 10])
    targets, covariance, _ = build_forecasts(r, meta, base, config)
    sample = r.loc[base['start']:base['end']]
    source = pd.DataFrame({a: a for a in sample}, index=sample.index)
    known = pd.Series(sample.index.to_timestamp()-pd.Timedelta(days=1), index=sample.index)
    monkeypatch.setattr(runner, 'OUT', tmp_path)
    metrics, alphas, ledgers, details, gross, failures = runner.evaluate(sample, source, known, targets, covariance, config)
    assert len(metrics) == 12 and len(alphas) == 18 and not failures
    for name, ledger in ledgers.items():
        _, _, _, summary = class_attribution(ledger, gross[name], details[name], covariance, meta)
        assert summary.net_mean_ann.sum() == pytest.approx(ledger.net_return.mean()*12)
        assert not ledger.gross_limit_breach.any() and not ledger.risk_limit_breach.any()


def test_comparison_runner_reports_blocked_pairs_without_partial_performance(tmp_path, monkeypatch):
    import run_risk_research as runner
    r, meta, base = data()
    config = dict(settings(), bands=[0., .1], cost_scenarios_bps=[0, 5, 10])
    targets, covariance, _ = build_forecasts(r, meta, base, config)
    sample = r.loc[base['start']:base['end']].copy()
    sample.iloc[0] = np.nan
    source = pd.DataFrame({a: a for a in sample}, index=sample.index)
    known = pd.Series(sample.index.to_timestamp()-pd.Timedelta(days=1), index=sample.index)
    monkeypatch.setattr(runner, 'OUT', tmp_path)
    metrics, alphas, ledgers, _, _, failures = runner.evaluate(sample, source, known, targets, covariance, config)
    assert len(failures) == 12 and metrics.empty and alphas.empty and not ledgers
    assert (tmp_path/'blocked_holdings.csv').is_file()
    assert not list(tmp_path.glob('*_ledger.csv'))
