# Required local inputs

Copy the original supplied files into this layout without renaming columns or editing prices:

```text
data/raw/
├── AssetMapCsv.csv
├── MonthlyReturns.csv
├── Lecture3_livedata.xlsx
└── futures_underlying/
    ├── AN.csv
    ├── ... (all 62 supplied daily instrument files)
    └── ZZ.csv
```

Paths are set in `src/config/__init__.py`. `AssetMapCsv.csv` identifies instruments and asset classes. `MonthlyReturns.csv` is the supplied monthly series used for reconciliation. `Lecture3_livedata.xlsx` provides benchmark/factor returns. The daily files support endpoint reconstruction and price audits.

The inputs are excluded by `.gitignore`; obtain them from the group's course data source. Lecture 4/5 PDFs are reference material and are not needed by the code. Run `python scripts/run_research.py --full` from the repository root to recreate the research outputs. Tests alone need no data: `python scripts/run_research.py --validate`.
