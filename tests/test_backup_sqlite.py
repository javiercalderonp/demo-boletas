from pathlib import Path
from unittest.mock import patch

from scripts.backup_sqlite import build_backup_path


def test_build_backup_path_uses_timestamp_and_source_name():
    with patch("scripts.backup_sqlite.datetime") as datetime_mock:
        datetime_mock.now.return_value.strftime.return_value = "20260710T120000Z"

        path = build_backup_path(Path("data/expense_agent.sqlite3"), Path("backups"))

    assert path == Path("backups/expense_agent-20260710T120000Z.sqlite3")
