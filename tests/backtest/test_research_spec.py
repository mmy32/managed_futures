"""Primary reporting must work without any historical 5 bps result."""

import json

import numpy as np
import pandas as pd
import pytest

import research_report as report
import run_risk_research
from run_risk_research import evaluate
from src.backtest.attribution import class_attribution
from src.backtest.performance import performance
from src.backtest.qps_baseline import build_forecasts, eligibility
from src.backtest.research_spec import (
    primary_key,
    run_key,
    select_results,
    validate_research_settings,
)
from src.backtest.sample_diagnostics import (
    class_portfolios,
    rank_autocorrelation,
    sample_audit,
    stability_summary,
)
from src.config import CONFIG_DIR
from tests.risk_model.test_risk_model import data


def config():
    settings = json.loads((CONFIG_DIR / "risk_config.json").read_text())
    return dict(
        settings,
        bands=[0, 0.05],
        primary_band=0.05,
        cost_scenarios_bps=[1, 2],
        risk_model={"type": "rolling"},
    )


def test_risk_research_records_missing_rescale_shadow_and_stops(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "risk_config.json").write_text(json.dumps(config()))
    (config_dir / "baseline_config.json").write_text(
        json.dumps({"start": "2000-01", "end": "2000-01"})
    )
    monkeypatch.setattr(run_risk_research, "ROOT", tmp_path)
    monkeypatch.setattr(run_risk_research, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(run_risk_research, "QPS_OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(run_risk_research, "QPS_REPORT_DIR", tmp_path / "reports")
    monkeypatch.setattr(run_risk_research, "RAW_DATA_DIR", tmp_path / "raw")
    monkeypatch.setattr(run_risk_research, "archive_previous_outputs", lambda *args: None)
    index = pd.period_range("2000-01", periods=1, freq="M")
    returns = pd.DataFrame({"A": [0.01]}, index=index)
    monkeypatch.setattr(
        run_risk_research, "load_returns", lambda *args: (returns, None, None, None, None, None)
    )
    monkeypatch.setattr(run_risk_research, "load_asset_map", lambda: None)

    def missing(*args):
        raise ValueError("Missing held return at 2000-01: ['A']")

    monkeypatch.setattr(run_risk_research, "risk_inputs", missing)
    assert run_risk_research.main() == 2
    status = json.loads((tmp_path / "output" / "risk" / "run_status.json").read_text())
    assert status["status"] == "blocked_missing_held_returns"
    assert status["stage"] == "risk_rescale_shadow"
    assert status["full_period_comparison_published"] is False
    assert "2000-01" in status["error"]


@pytest.mark.parametrize(
    "change",
    [
        {"primary_cost_bps": 5},
        {"primary_band": 0.1},
        {"cost_scenarios_bps": [1, 2, 2]},
        {"bands": [0, float("nan")]},
        {"cost_scenarios_bps": [-1, 2]},
        {"models": ["diagonal"]},
    ],
)
def test_invalid_primary_specification_is_rejected(change):
    with pytest.raises(ValueError):
        validate_research_settings(dict(config(), **change))


def test_keys_preserve_legacy_names_and_handle_numeric_types_and_fractional_bands():
    assert run_key(0.1, 5, "trend") == "correlated_band10_5bps_trend"
    assert run_key(0.1, 2.0, "trend") == run_key(0.1, 2, "trend")
    assert run_key(0.055, 2, "trend") != run_key(0.05, 2, "trend")
    validate_research_settings(json.loads((CONFIG_DIR / "risk_config.json").read_text()))


def test_missing_and_duplicate_results_fail_instead_of_falling_back():
    frame = pd.DataFrame(
        [
            dict(model="correlated", band=0.05, cost_bps=2, strategy="trend"),
            dict(model="correlated", band=0.05, cost_bps=2, strategy="static"),
        ]
    )
    with pytest.raises(ValueError, match="Missing"):
        select_results(frame, config(), cost_bps=1)
    with pytest.raises(ValueError, match="Ambiguous"):
        select_results(pd.concat([frame, frame]), config())
    with pytest.raises(ValueError, match="TREND and one STATIC"):
        report._main_metrics(frame.iloc[:1], config())


def test_one_and_two_bps_pipeline_reporting_and_stability(tmp_path, monkeypatch):
    settings = config()
    validate_research_settings(settings)
    _, meta, base = data()
    base = dict(base, start="1976-01", end="2014-12")
    index = pd.period_range("1971-01", "2014-12", freq="M")
    rng = np.random.default_rng(24)
    returns = pd.DataFrame(
        rng.normal(0.002, 0.025, (len(index), 8)), index=index, columns=meta.index
    )
    targets, covariance, _ = build_forecasts(returns, meta, base, settings)
    sample = returns.loc[base["start"] : base["end"]]
    source = pd.DataFrame({a: a for a in sample}, index=sample.index)
    known = pd.Series(sample.index.to_timestamp() - pd.Timedelta(days=1), index=sample.index)
    metrics, alphas, ledgers, details, gross, failures = evaluate(
        sample,
        source,
        known,
        targets,
        covariance,
        settings,
        tmp_path,
    )
    assert not failures and len(metrics) == 8 and len(alphas) == 12
    assert all("5bps" not in key for key in ledgers)
    attribution = {}
    for name, ledger in ledgers.items():
        np.testing.assert_allclose(ledger.net_return, ledger.gross_return - ledger.cost)
        assert not ledger.gross_limit_breach.any() and not ledger.risk_limit_breach.any()
        _, _, _, summary = class_attribution(ledger, gross[name], details[name], covariance, meta)
        assert summary.net_mean_ann.sum() == pytest.approx(ledger.net_return.mean() * 12)
        if name == primary_key(settings, "trend"):
            attribution["trend"] = summary
    stability = stability_summary(ledgers, settings)
    recent = stability.query("strategy == 'trend' and period == '2005–2014'").iloc[0]
    assert recent.cost_bps == 2 and recent.band == 0.05
    assert recent.cagr == pytest.approx(
        performance(ledgers[primary_key(settings, "trend")].loc["2005":"2014"])["cagr"]
    )
    allowed = eligibility(returns, meta, base, settings)
    classes, counts, stats = class_portfolios(returns, allowed, meta, sample.index)
    autocorr = rank_autocorrelation(classes)
    audit = dict(
        sample_audit(returns, allowed, base), retained_columns=8, source_switch_month="none"
    )
    _check_report_and_charts(
        tmp_path,
        monkeypatch,
        settings,
        metrics,
        alphas,
        ledgers,
        stability,
        attribution,
        classes,
        counts,
        stats,
        autocorr,
        audit,
        base,
    )


def _check_report_and_charts(
    out,
    monkeypatch,
    settings,
    metrics,
    alphas,
    ledgers,
    stability,
    attribution,
    classes,
    counts,
    stats,
    autocorr,
    audit,
    base,
):
    monkeypatch.setattr(report, "validation_summary", lambda: "Synthetic regression test")
    monkeypatch.setattr(report, "QPS_REPORT_DIR", out)
    report.write_report(
        metrics,
        alphas,
        stats,
        autocorr,
        attribution,
        audit,
        settings,
        base,
        out=out,
        report_path=out / "report.md",
        stability=stability,
    )
    text = (out / "report.md").read_text()
    assert "**2 bps per unit of one-way" in text and "±5% bands" in text
    assert "5 bps" not in text and "±10%" not in text
    alpha = select_results(alphas, settings, hac_lags=6).iloc[0]
    assert f"regression alpha is {alpha.alpha_ann:.2%}" in text
    captured = {}
    save = report.save

    def capture(fig, name, directory):
        captured[name] = fig
        save(fig, name, directory)

    monkeypatch.setattr(report, "save", capture)
    report.make_charts(classes, counts, autocorr, ledgers, settings, out)
    fig = captured["performance"]
    assert "2 bps trading costs • ±5% bands" in fig._suptitle.get_text()
    np.testing.assert_allclose(
        fig.axes[0].lines[0].get_ydata(), ledgers[primary_key(settings, "trend")].nav_end - 1
    )
    assert len(list(out.glob("*.png"))) == 5
