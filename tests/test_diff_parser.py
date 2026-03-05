"""Tests for git diff parser."""

from __future__ import annotations

from codebase_cortex.git.diff_parser import parse_diff


def test_parse_diff_modified_file(sample_diff: str):
    files = parse_diff(sample_diff)
    main_py = next(f for f in files if f["path"] == "src/main.py")
    assert main_py["status"] == "modified"
    assert main_py["additions"] == 3  # +import sys, +print("hello world"), +return 0
    assert main_py["deletions"] == 1  # -print("hello")


def test_parse_diff_new_file(sample_diff: str):
    files = parse_diff(sample_diff)
    utils = next(f for f in files if f["path"] == "src/utils.py")
    assert utils["status"] == "added"
    assert utils["additions"] == 3
    assert utils["deletions"] == 0


def test_parse_diff_deleted_file(sample_diff: str):
    files = parse_diff(sample_diff)
    old = next(f for f in files if f["path"] == "old_file.py")
    assert old["status"] == "deleted"
    assert old["deletions"] == 2


def test_parse_diff_count(sample_diff: str):
    files = parse_diff(sample_diff)
    assert len(files) == 3


def test_parse_empty_diff():
    assert parse_diff("") == []
    assert parse_diff("   ") == []
