import pytest
from versioning import parse_version, get_active_version


def test_parse_version_standard():
    assert parse_version("[v0.1] Basic arena scene") == (0, 1)


def test_parse_version_higher():
    assert parse_version("[v1.2] Some feature") == (1, 2)


def test_parse_version_bootstrap():
    assert parse_version("[bootstrap] Project scaffold") == (0, 0)


def test_parse_version_no_tag():
    assert parse_version("Fix bug in player scene") is None


def test_parse_version_malformed():
    assert parse_version("[vX.Y] Bad version") is None


def test_get_active_version_bootstrap_first():
    issues = [
        {"title": "[bootstrap] Setup", "status": "ai-ready"},
        {"title": "[v0.1] Feature A", "status": "ai-ready"},
    ]
    assert get_active_version(issues) == (0, 0)


def test_get_active_version_skips_done():
    issues = [
        {"title": "[v0.1] Feature A", "status": "Done"},
        {"title": "[v0.2] Feature B", "status": "ai-ready"},
    ]
    assert get_active_version(issues) == (0, 2)


def test_get_active_version_blocked_holds_version():
    issues = [
        {"title": "[v0.1] Feature A", "status": "Done"},
        {"title": "[v0.1] Feature B", "status": "ai-blocked"},
        {"title": "[v0.2] Feature C", "status": "ai-ready"},
    ]
    assert get_active_version(issues) == (0, 1)


def test_get_active_version_all_done():
    issues = [
        {"title": "[v0.1] Feature A", "status": "Done"},
        {"title": "[v0.1] Feature B", "status": "Done"},
    ]
    assert get_active_version(issues) is None


def test_get_active_version_no_versioned_issues():
    issues = [
        {"title": "Unversioned task", "status": "ai-ready"},
    ]
    assert get_active_version(issues) is None
