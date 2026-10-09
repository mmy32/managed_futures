"""Write the monthly-return correlation matrix and per-market data counts."""

from src.config import (
    DUPLICATE_MIN_OVERLAP,
    PROCESSED_DATA_DIR,
)
from src.data_loader import load_asset_map, load_monthly_returns


def main() -> None:
    returns = load_monthly_returns()
    asset_map = load_asset_map()
    PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)

    corr = returns.corr(min_periods=DUPLICATE_MIN_OVERLAP)
    corr.to_csv(PROCESSED_DATA_DIR / "correlation_matrix.csv")

    valid = returns.notna()
    counts = returns.agg(["count"]).T.rename(columns={"count": "n_obs"})
    counts["first_date"] = [returns[m].first_valid_index() for m in returns]
    counts["last_date"] = [returns[m].last_valid_index() for m in returns]
    counts["zero_share"] = (returns == 0).sum() / counts["n_obs"]
    counts["asset_class"] = asset_map["AssetClass"].reindex(counts.index)
    counts.sort_values("n_obs").to_csv(PROCESSED_DATA_DIR / "data_counts.csv")

    overlap = valid.astype(int).T @ valid.astype(int)
    overlap.to_csv(PROCESSED_DATA_DIR / "pairwise_overlap.csv")
    print(counts.sort_values("n_obs").to_string())


if __name__ == "__main__":
    main()
