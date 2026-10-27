"""Supplemental same-month direction check; pass an experiment output directory."""
import sys
from pathlib import Path
import pandas as pd
out = Path(sys.argv[1])
target = pd.read_csv(out / "trend_targets.csv", index_col=0)
events = (target * target.shift(1)).lt(0)
rows = []
for file in sorted(out.glob("*_trend_exposure.csv")):
    exposure = pd.read_csv(file, index_col=0)
    mismatches = int((events & (exposure * target).le(0)).to_numpy().sum())
    assert mismatches == 0
    count = int(events.to_numpy().sum())
    rows.append(dict(run=file.name.removesuffix("_exposure.csv"), target_reversals=count,
                     same_month_direction_matches=count-mismatches, direction_mismatches=mismatches))
pd.DataFrame(rows).to_csv(out / "reversal_execution.csv", index=False)
