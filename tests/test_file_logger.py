#!/usr/bin/env python3
"""Tests for File_Logger.update_existing_file in utils.py

Two scenarios tested:
  1. New data has *fewer* columns than the existing file:
     - file must be continued (no backup), header unchanged,
     - missing columns written as blank.
  2. New data has *additional* columns not in the existing file:
     - old file is backed up to <path>_previous_data,
     - new file gets a merged header (union of old + new columns),
     - old rows are copied into the new file with blank values for new columns.
"""

import csv
import os
import tempfile
import unittest
from datetime import datetime
from types import SimpleNamespace

import pytz

from utils import File_Logger


def make_config():
    return SimpleNamespace(
        date_format="%y-%m-%d",
        time_format="%H:%M:%S",
        tz="Europe/Berlin",
        logger_skip_no_changes=True,
        round_digits=4,
    )


def write_csv(filepath, fieldnames, rows):
    with open(filepath, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def read_csv(filepath):
    with open(filepath, newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames)
        rows = list(reader)
    return fieldnames, rows


class TestFileLoggerFewerColumns(unittest.TestCase):
    """Existing file has more columns than the new data."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.config = make_config()
        tz = pytz.timezone(self.config.tz)
        self.t_now = datetime(2026, 3, 12, 10, 0, 0, tzinfo=tz)

        path_structure = os.path.join(self.tmpdir.name, "log_{date_str}.csv")
        self.logger = File_Logger(path_structure, self.config)
        self.filepath = self.logger.get_output_file_path(self.t_now)

        write_csv(
            self.filepath,
            fieldnames=["time", "col_a", "col_b", "col_c"],
            rows=[
                {"time": "09:00:00", "col_a": "1.0", "col_b": "2.0", "col_c": "3.0"},
                {"time": "09:05:00", "col_a": "1.1", "col_b": "2.1", "col_c": "3.1"},
            ],
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_no_backup_created(self):
        """File must be continued – no _previous_data backup."""
        self.logger.update_existing_file(self.t_now, {"col_a": 1.2, "col_b": 2.2})
        self.assertFalse(os.path.exists(self.filepath + "_previous_data"))

    def test_header_unchanged(self):
        """Existing header must be preserved including the missing column."""
        self.logger.update_existing_file(self.t_now, {"col_a": 1.2, "col_b": 2.2})
        fieldnames, _ = read_csv(self.filepath)
        self.assertEqual(fieldnames, ["time", "col_a", "col_b", "col_c"])

    def test_fieldnames_attribute_includes_missing_column(self):
        """logger.fieldnames must reflect the existing file's columns."""
        self.logger.update_existing_file(self.t_now, {"col_a": 1.2, "col_b": 2.2})
        self.assertIn("col_c", self.logger.fieldnames)

    def test_new_row_written_with_blank_for_missing_column(self):
        """After log_step, the new row should have a blank value for col_c."""
        self.logger.log_step(self.t_now, {"col_a": 1.2, "col_b": 2.2})
        fieldnames, rows = read_csv(self.filepath)
        self.assertEqual(len(rows), 3, "Expected 2 original rows + 1 new row")
        new_row = rows[2]
        self.assertEqual(new_row["col_a"], "1.2")
        self.assertEqual(new_row["col_b"], "2.2")
        self.assertEqual(new_row["col_c"], "", "Missing column must be written as blank")


class TestFileLoggerAdditionalColumns(unittest.TestCase):
    """New data has columns not present in the existing file."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.config = make_config()
        tz = pytz.timezone(self.config.tz)
        self.t_now = datetime(2026, 3, 12, 10, 0, 0, tzinfo=tz)

        path_structure = os.path.join(self.tmpdir.name, "log_{date_str}.csv")
        self.logger = File_Logger(path_structure, self.config)
        self.filepath = self.logger.get_output_file_path(self.t_now)

        self.original_rows = [
            {"time": "09:00:00", "col_a": "1.0", "col_b": "2.0"},
            {"time": "09:05:00", "col_a": "1.1", "col_b": "2.1"},
        ]
        write_csv(
            self.filepath,
            fieldnames=["time", "col_a", "col_b"],
            rows=self.original_rows,
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_backup_created(self):
        """Old file must be moved to _previous_data."""
        self.logger.update_existing_file(
            self.t_now, {"col_a": 1.2, "col_b": 2.2, "col_c": 3.2}
        )
        self.assertTrue(os.path.exists(self.filepath + "_previous_data"))

    def test_new_header_contains_all_columns(self):
        """New file header must include both old and new columns."""
        self.logger.update_existing_file(
            self.t_now, {"col_a": 1.2, "col_b": 2.2, "col_c": 3.2}
        )
        fieldnames, _ = read_csv(self.filepath)
        for col in ["time", "col_a", "col_b", "col_c"]:
            self.assertIn(col, fieldnames)

    def test_old_data_copied_to_new_file(self):
        """Old rows must be present in the new file with blank for the new column."""
        self.logger.update_existing_file(
            self.t_now, {"col_a": 1.2, "col_b": 2.2, "col_c": 3.2}
        )
        _, rows = read_csv(self.filepath)
        self.assertGreaterEqual(len(rows), 2, "Old rows must be copied to new file")
        self.assertEqual(rows[0]["col_a"], "1.0")
        self.assertEqual(rows[0]["col_b"], "2.0")
        self.assertEqual(rows[0]["col_c"], "", "New column must be blank for old rows")

    def test_new_row_written_with_new_column(self):
        """After log_step, the appended row must include the new column value."""
        self.logger.log_step(self.t_now, {"col_a": 1.2, "col_b": 2.2, "col_c": 3.2})
        _, rows = read_csv(self.filepath)
        # original 2 rows + 1 new
        self.assertEqual(len(rows), 3)
        new_row = rows[2]
        self.assertEqual(new_row["col_a"], "1.2")
        self.assertEqual(new_row["col_b"], "2.2")
        self.assertEqual(new_row["col_c"], "3.2")


if __name__ == "__main__":
    unittest.main()
