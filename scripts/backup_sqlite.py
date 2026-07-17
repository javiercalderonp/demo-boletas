from __future__ import annotations

import argparse
import shutil
from datetime import datetime, timezone
from pathlib import Path


def build_backup_path(source: Path, backup_dir: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return backup_dir / f"{source.stem}-{timestamp}{source.suffix or '.sqlite3'}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a timestamped SQLite database backup.")
    parser.add_argument(
        "--source",
        default="./data/expense_agent.sqlite3",
        help="Path to the SQLite database file.",
    )
    parser.add_argument(
        "--backup-dir",
        default="./backups",
        help="Directory where the backup copy will be written.",
    )
    args = parser.parse_args()

    source = Path(args.source)
    if not source.exists() or not source.is_file():
        raise SystemExit(f"SQLite database not found: {source}")

    backup_dir = Path(args.backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = build_backup_path(source, backup_dir)
    shutil.copy2(source, backup_path)
    print(str(backup_path))


if __name__ == "__main__":
    main()
