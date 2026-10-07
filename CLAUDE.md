# CLAUDE.md

Project-level instructions. These extend the global rules in `~/.claude/CLAUDE.md` (think before coding, simplicity first, surgical changes, goal-driven execution), which still apply.

## Project Layout

Model components under `src/`: `alpha_model` (forecasts), `risk_model` (risk measurement and control), `transaction_cost_model`, `portfolio_construction`, `backtest`, `feedback_loop`. Data lives in `data/` (gitignored; `data/raw/` is immutable). See `README.md`.

## Design Principles

Apply these principles in all application code under `src/`.

### Single Responsibility
Every module, class, and function does exactly one thing. If you cannot describe its purpose in one sentence without "and", split it.

### Don't Repeat Yourself (DRY)
Extract shared logic into a single source of truth. If the same pattern appears in two places, refactor it into a reusable function or module. Duplicated code is duplicated bugs.

### Dependency Inversion
Depend on abstractions, not concrete implementations. Pass dependencies in (constructor, function argument) rather than hardcoding them. This makes testing trivial — swap a real DB client for a mock by injecting a different object.

### Fail Fast
Validate inputs at boundaries. Raise errors immediately on invalid state instead of silently propagating bad data downstream. The earlier a bug surfaces, the cheaper it is to fix.

### Configuration over Hardcoding
No magic numbers, hardcoded paths, or inline credentials. Externalize settings to `src/config/`, environment variables, or config files. One place to change a value, not twenty.

### YAGNI (You Aren't Gonna Need It)
Do not build for hypothetical future requirements. Write the code you need today. Speculative abstractions are tech debt with no offsetting value.

### Immutability by Default
Prefer immutable data structures. Mutate explicitly and locally. In data pipelines, accidental in-place mutation causes subtle, hard-to-trace bugs.

### Encapsulation
Hide internal state. Expose behavior through public methods. Keep fields private; provide access only where needed.

### Abstraction
Expose only what consumers need. Hide implementation complexity behind clear interfaces. A caller should not need to understand internals to use a class.

### Inheritance
Use inheritance for genuine "is-a" relationships. Prefer composition over inheritance when the relationship is "has-a" or "uses-a". Avoid deep inheritance hierarchies (≤ 2 levels unless strongly justified).

### Polymorphism
Program to interfaces, not implementations. Use method overriding and duck typing (or generics) so components are interchangeable without conditionals checking concrete types.

## Verifier Commands

- Tests: `pytest`
- Lint: `ruff check .`
- Types: `mypy src`
