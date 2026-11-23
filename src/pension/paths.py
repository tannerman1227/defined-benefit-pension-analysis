"""Repository paths. Data files live next to the source tree, not inside it."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW_DATA = ROOT / "data" / "raw"
OUTPUT_DATA = ROOT / "data" / "output"
FIGURES = ROOT / "reports" / "figures"
REPORTS = ROOT / "reports"
SQL_DIR = Path(__file__).resolve().parent / "sql"
