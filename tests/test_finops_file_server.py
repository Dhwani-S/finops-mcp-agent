"""Tests for finops_file_server — focused on _safe_path security boundary."""

import os
import pytest
from pathlib import Path

from mcp_servers.finops_file_server import (
    _safe_path, write_file, read_file, list_files, delete_file, export_csv, SANDBOX
)


# ── _safe_path: valid paths ──────────────────────────────────────

class TestSafePathValid:
    def test_simple_filename(self):
        result = _safe_path("report.md")
        assert result == (SANDBOX / "report.md").resolve()

    def test_nested_path(self):
        result = _safe_path("subdir/report.md")
        assert result == (SANDBOX / "subdir" / "report.md").resolve()

    def test_rejects_leading_slash(self):
        """Leading slash looks absolute — reject, don't silently strip."""
        with pytest.raises(ValueError):
            _safe_path("/report.md")

    def test_strips_trailing_slash(self):
        result = _safe_path("subdir/")
        assert result == (SANDBOX / "subdir").resolve()


# ── _safe_path: must reject ──────────────────────────────────────

class TestSafePathReject:
    def test_traversal(self):
        with pytest.raises(ValueError):
            _safe_path("../../etc/passwd")

    def test_empty_string(self):
        with pytest.raises(ValueError):
            _safe_path("")

    def test_bare_dot(self):
        with pytest.raises(ValueError):
            _safe_path(".")

    def test_absolute_windows(self):
        with pytest.raises(ValueError):
            _safe_path("C:/Windows/system32/file.txt")

    def test_absolute_unix(self):
        with pytest.raises(ValueError):
            _safe_path("/etc/passwd")

    def test_unc_path(self):
        with pytest.raises(ValueError):
            _safe_path("\\\\server\\share\\file.txt")

    def test_backslash_traversal(self):
        with pytest.raises(ValueError):
            _safe_path("..\\..\\secrets\\key.pem")


# ── Integration: tool happy path ─────────────────────────────────

class TestToolIntegration:
    """Write → read → list → delete cycle."""

    TEST_FILE = "test_integration.md"

    def teardown_method(self):
        """Clean up test file if it exists."""
        path = SANDBOX / self.TEST_FILE
        if path.exists():
            path.unlink()

    def test_write_read_list_delete(self):
        # Write
        result = write_file(self.TEST_FILE, "Hello FinOps!")
        assert "Written" in result

        # Read
        result = read_file(self.TEST_FILE)
        assert result == "Hello FinOps!"

        # List
        result = list_files("")
        assert self.TEST_FILE in result

        # Delete
        result = delete_file(self.TEST_FILE)
        assert "Deleted" in result

        # Verify deleted
        result = read_file(self.TEST_FILE)
        assert "Error" in result

    def test_export_csv_union_keys(self):
        """Rows with different keys should produce union of all columns."""
        import json
        data = json.dumps([
            {"service": "EC2", "cost": 100},
            {"service": "S3", "cost": 50, "region": "us-east-1"}
        ])
        result = export_csv("test_union.csv", data)
        assert "3 columns" in result  # service, cost, region

        content = read_file("test_union.csv")
        assert "region" in content

        # Clean up
        delete_file("test_union.csv")