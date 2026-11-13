# Historical validation only — not an out-of-sample assessment

These files use previously inspected 2009–2014 development data. The diagnostic period starts after a known 2006 HS endpoint gap; it is not a performance sample. A temporary clone changes only the development-end guard to 2009-03 for this validation. All strategy, cost and risk settings are unchanged. Run `scripts/validate_oos_history.py` with a new output path to reproduce; mutated prices are temporary and can be regenerated.
