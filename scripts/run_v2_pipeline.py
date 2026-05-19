"""
SSO vs SFSP Texas Capstone
run_v2_pipeline.py

Wrapper that runs the four v2 scripts in order:
  09 -> 10 -> 11 -> 12

Stops on the first failure. Prints a clear section header before each
step and a final summary with the key output paths the Streamlit app
depends on.

Usage (from repo root):
    python scripts/run_v2_pipeline.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
SCRIPTS_DIR = os.path.join(REPO_ROOT, "scripts")

STEPS = [
    ("09", "Build 5-year TDA dataset registry",
     "09_build_5yr_dataset_registry.py"),
    ("10", "Ingest all v2 datasets from TX Open Data",
     "10_ingest_5yr_tda_datasets.py"),
    ("11", "Build five canonical 5-year master tables",
     "11_build_5yr_canonical_tables.py"),
    ("12", "Build v2 CE/Site lookup + validation report",
     "12_build_ce_site_lookup_v2.py"),
]

KEY_OUTPUTS = [
    "data/lookup_v2/ce_site_search_master_v2.csv",
    "data/audit/tda_5yr_pipeline_validation_report.md",
]


def banner(title: str) -> None:
    line = "=" * 80
    print(f"\n{line}\n{title}\n{line}", flush=True)


def main() -> int:
    started = datetime.now()
    banner(f"v2 pipeline start  -  {started.isoformat(timespec='seconds')}")

    for num, label, script in STEPS:
        banner(f"STEP {num}: {label}\n  {script}")
        script_path = os.path.join(SCRIPTS_DIR, script)
        if not os.path.exists(script_path):
            print(f"ERROR: script not found at {script_path}")
            return 2
        try:
            subprocess.run(
                [sys.executable, script_path],
                check=True,
                cwd=REPO_ROOT,
            )
        except subprocess.CalledProcessError as exc:
            print(f"\nERROR: step {num} ({script}) failed with exit code "
                  f"{exc.returncode}. Stopping the pipeline.")
            return exc.returncode

    ended = datetime.now()
    elapsed = (ended - started).total_seconds()
    banner(f"v2 pipeline complete in {elapsed:.0f}s")
    print("Key outputs the dashboard depends on:")
    for p in KEY_OUTPUTS:
        full = os.path.join(REPO_ROOT, p)
        present = "OK " if os.path.exists(full) else "MISSING"
        print(f"  [{present}] {p}")
    print("\nNext step:")
    print("  streamlit run app.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
