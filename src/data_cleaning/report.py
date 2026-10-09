"""Record of what the cleaning step removed and merged."""

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CleaningReport:
    excluded: dict[str, str]  # market ID -> reason
    merged: dict[str, list[str]]  # representative ID -> member IDs

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"excluded": self.excluded, "merged": self.merged}, indent=2))
