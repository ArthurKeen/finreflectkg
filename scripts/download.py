"""Download the domyn/FinReflectKG parquet shards to data/raw/ (resumable).

Usage: .venv/bin/python scripts/download.py
"""

import pathlib

from huggingface_hub import snapshot_download

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEST = ROOT / "data" / "raw"

path = snapshot_download(
    repo_id="domyn/FinReflectKG",
    repo_type="dataset",
    local_dir=DEST,
    allow_patterns=["data/*.parquet", "README.md"],
    max_workers=4,
)
n = len(list((DEST / "data").glob("train-*.parquet")))
print(f"downloaded to {path}: {n}/103 shards")
assert n == 103, "incomplete download — re-run to resume"
