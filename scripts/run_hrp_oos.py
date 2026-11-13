"""Prepare, then assess, a declared matched HRP comparison."""

import argparse
from pathlib import Path

from src.backtest.oos_runner import prepare, run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    preflight = commands.add_parser("prepare", help="Validate and lock inputs without scoring")
    preflight.add_argument("--declaration", type=Path, required=True)
    preflight.add_argument("--prices-dir", type=Path, required=True)
    preflight.add_argument("--asset-map", type=Path, required=True)
    preflight.add_argument("--output", type=Path, required=True)
    evaluate = commands.add_parser("run", help="Run an unchanged prepared comparison")
    evaluate.add_argument("--prepared", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.declaration, args.prices_dir, args.asset_map, args.output)
        print(f"Prepared without scoring: {args.output}")
    else:
        print(f"Results: {run(args.prepared)}")


if __name__ == "__main__":
    main()
