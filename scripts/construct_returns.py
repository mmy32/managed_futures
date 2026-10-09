"""Reproduce supplied monthly returns and publish separately logged research edits."""

import hashlib
import json
from decimal import Decimal

import numpy as np
import pandas as pd

from src.config import MONTHLY_RETURNS_PATH, PROJECT_ROOT, QPS_OUTPUT_DIR, RAW_DATA_DIR
from src.data_loader import load_daily_prices, load_monthly_returns
from src.data_processing.endpoints import close_frames, endpoints

ROOT = PROJECT_ROOT
OUT = QPS_OUTPUT_DIR / "construction"


def read_inputs():
    raw = close_frames(load_daily_prices())
    supplied = load_monthly_returns()
    supplied.index = supplied.index.to_period("M")
    return raw, supplied


def assemble(raw, months, columns, calendar_corrections=False):
    e = {a: endpoints(d, months) for a, d in raw.items()}
    overrides = []
    if calendar_corrections:
        cases = [
            (
                "HS",
                "2006-01",
                "2006-01-27",
                "Verified Lunar New Year closure; actual final session",
                "https://www.info.gov.hk/gia/general/200504/15/04150111.htm",
            )
        ]
        cases += [
            (
                a,
                "2014-12",
                "2014-12-30",
                "Verified Eurex Dec 31 closure; extend final month target",
                "https://deutsche-boerse.com/resource/blob/249120/6fadad3fe12a3cc3fa392442532d4414/tradingcalendar_2014_en-data.pdf",
            )
            for a in ["AX", "DT", "UB", "UZ", "XU", "XX"]
        ]
        for a, month, date, why, url in cases:
            m, date = pd.Period(month, "M"), pd.Timestamp(date)
            assert date in raw[a].index and date.to_period("M") == m
            assert raw[a].loc[str(m)].index[-1] == date
            e[a].loc[m, "endpoint_close"] = raw[a].loc[date, "Close"]
            e[a].loc[m, "endpoint_accepted"] = True
            overrides.append(
                {
                    "ID": a,
                    "month": month,
                    "selected_date": str(date.date()),
                    "reason": why,
                    "source": url,
                }
            )
    ratios = {a: x.endpoint_close / x.endpoint_close.shift(1) - 1 for a, x in e.items()}
    result = pd.DataFrame({a: ratios[a] for a in columns}, index=months)
    source = pd.DataFrame({a: pd.Series(a, index=months).where(result[a].notna()) for a in columns})
    # Priority is empirical. Use within-source returns, never cross-source price ratios.
    fallback = result.RL.isna() & ratios["ER"].notna()
    result.loc[fallback, "RL"] = ratios["ER"].loc[fallback]
    source.loc[fallback, "RL"] = "ER"
    return result, source, overrides


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    files = sorted(RAW_DATA_DIR.rglob("*"))
    hashes = {
        str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in files
        if p.is_file()
    }
    raw, supplied = read_inputs()
    replica, _provenance, _ = assemble(raw, supplied.index, supplied.columns)
    # Loaders return floats; the stored decimal strings set the comparison tolerance.
    tokens = pd.read_csv(MONTHLY_RETURNS_PATH, index_col=0, dtype=str)
    tokens.index = supplied.index
    assert replica.notna().equals(supplied.notna())
    rows = []
    for a in supplied:
        delta = replica[a] - supplied[a]
        for m in supplied.index[supplied[a].notna()]:
            token = tokens.loc[m, a]
            tol = (
                min(5e-8, 0.5 * 10.0 ** Decimal(token).as_tuple().exponent) + 1e-12
                if float(token)
                else 1e-12
            )
            assert abs(delta.loc[m]) <= tol, (a, m, delta.loc[m], tol)
        rows.append(
            {
                "ID": a,
                "observed": int(supplied[a].count()),
                "matching_missingness": True,
                "max_abs_difference": float(delta.abs().max()),
            }
        )
    research, research_source, overrides = assemble(raw, supplied.index, supplied.columns, True)
    changed = replica.isna() & research.notna()
    assert int(changed.sum().sum()) == 8
    assert np.allclose(research.where(replica.notna()), replica, equal_nan=True)
    changes = []
    for m, a in changed.stack().loc[lambda s: s].index:
        changes.append(
            {
                "month": str(m),
                "ID": a,
                "old_return": np.nan,
                "new_return": research.loc[m, a],
                "reason": "HS January endpoint correction propagates to both adjacent returns"
                if a == "HS"
                else "Eurex final-month endpoint correction",
            }
        )
    for name, frame in [
        ("monthly_returns_reproduced", replica),
        ("monthly_returns_research", research),
        ("return_source", research_source),
    ]:
        frame.to_csv(OUT / f"{name}.csv", float_format="%.17g", index_label="month")
    pd.DataFrame(rows).to_csv(OUT / "reconciliation.csv", index=False)
    pd.DataFrame(changes).to_csv(OUT / "return_changes.csv", index=False)
    pd.DataFrame(overrides).to_csv(OUT / "endpoint_overrides.csv", index=False)
    decisions = [
        (
            "RL;ER",
            "RL",
            "Prefer RL monthly returns; fill missing RL from independently calculated ER monthly returns.",
            "73 ER months from 2008-12 through 2014-12",
        ),
        (
            "ND;EN",
            "ND",
            "Retain ND; no averaging, price splicing, or double counting.",
            "ND alone reconciles supplied retained column",
        ),
        (
            "SP;ES;SC",
            "SP",
            "Retain SP; no averaging, price splicing, or double counting.",
            "SP alone reconciles supplied retained column",
        ),
        (
            "ZD;YM",
            "ZD",
            "Reproduction and EDA retain both; strategy drops YM as overlapping Dow exposure.",
            "Economic exposure decision; no claim that contract specifications are identical",
        ),
        (
            "EC",
            "",
            "EDA retains supplied FX class; strategy excludes pending identity verification.",
            "No invented metadata correction",
        ),
        (
            "BC;BG;FF;ZH",
            "",
            "Absent from raw inputs and retained monthly data; no synthetic reconstruction.",
            "Unobserved sources remain unavailable",
        ),
    ]
    pd.DataFrame(
        decisions, columns=["source_IDs", "research_representative", "rule", "evidence"]
    ).to_csv(OUT / "instrument_rules.csv", index=False)
    pending = [
        (
            "AP",
            "2014-07-04;2014-07-25;2014-07-28;2014-07-29",
            "Missing daily sessions; endpoints valid",
            "Retain monthly ratio; no invented daily prices",
        ),
        (
            "SS",
            "1991-1998 year-end",
            "Unresolved vendor coverage",
            "Retain missing endpoints and resulting monthly gaps",
        ),
        (
            "DT;GS;LX;SS",
            "1997-03;1997-04",
            "Exact historical venue calendar not verified",
            "Do not apply calendar corrections",
        ),
        (
            "FN;DA;UZ",
            "seven repeated-OHLC runs",
            "Vendor prices unverified",
            "Retain values; strategy sensitivity excludes entire affected instruments",
        ),
        (
            "ER",
            "2012-05-28",
            "Consistent with settlement carryforward; vendor field meaning unconfirmed",
            "Retain interior row; no monthly endpoint impact",
        ),
        (
            "ALL",
            "all history",
            "Lecture 4 p14 confirms already rolled; exact adjustment method, contract multipliers and collateral/FX conversion conventions remain unspecified",
            "Results are price-return proxy research, not certified tradable P&L",
        ),
    ]
    pd.DataFrame(pending, columns=["IDs", "dates", "unresolved", "treatment"]).to_csv(
        OUT / "unresolved_issues.csv", index=False
    )
    assert all(hashlib.sha256((ROOT / p).read_bytes()).hexdigest() == h for p, h in hashes.items())
    pd.DataFrame([{"path": p, "sha256": h} for p, h in hashes.items()]).to_csv(
        OUT / "source_manifest.csv", index=False
    )
    summary = {
        "observed_returns": int(supplied.count().sum()),
        "matching_blanks": int(supplied.isna().sum().sum()),
        "max_abs_difference": float((replica - supplied).abs().max().max()),
        "all_match_stored_precision": True,
        "research_returns_added": 8,
        "raw_sources_unchanged": True,
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print("Construction:", summary)
    return research


if __name__ == "__main__":
    main()
