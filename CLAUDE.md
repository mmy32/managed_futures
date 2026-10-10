# CLAUDE.md

Project-level instructions. Extends global rules in `~/.claude/CLAUDE.md` (think first, simplicity first, surgical changes, goal-driven execution).

## Project Layout

- `src/`: Core pipeline components (`alpha_model`, `risk_model`, `transaction_cost_model`, `portfolio_construction`, `backtest`, `feedback_loop`).
- `data/`: Gitignored. **`data/raw/` is strictly immutable.**
- `scripts/`: Reporting and execution scripts.
- `reports/`: Generated results and visual outputs.
- `config/*.json`: Strategy & risk parameters (accessed via `src.config.CONFIG_DIR`).

## Engineering Guidelines

- **Surgical & YAGNI:** Make minimal, targeted modifications. Do not build speculative abstractions or add unneeded configuration parameters. Edit existing modules directly rather than adding wrapper layers.
- **Dependency Injection:** Pass models, parameters, and data handles via constructors or arguments to keep pipeline stages unit-testable.
- **Fail Fast:** Validate data schema, shapes, and date ranges at pipeline boundaries; raise explicit errors immediately.
- **Zero Magic Numbers:** Externalize thresholds and paths to `src/config/` or `config/*.json`.
- **Data Immutability:** Never mutate input DataFrames or arrays in-place; return transformed copies.
- **Clean Interfaces:** Prefer composition over inheritance. Keep classes focused on one task (forecast, risk measure, execution).

- **SRP:** Split any function over ~40 lines or any class doing both data fetching/parsing and mathematical computation.
- **OCP:** Add new alpha/risk signals by registering a new class against the base protocol/interface, without modifying existing model code.
- **LSP:** Never override a base class method with `pass`, `raise NotImplementedError`, or a different return type.
- **ISP:** Keep interfaces minimal (<4 public methods). Never force a model to implement execution hooks if it only computes scores.
- **DIP:** No direct instantiation of IO or DB clients inside calculation classes; pass data or protocols into `__init__`.

## Verifier Commands

- Tests: `pytest`
- Lint: `ruff check .`
- Types: `mypy src`