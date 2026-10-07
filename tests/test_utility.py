"""Pure transforms, local paths, cache identity and HTTP-derived values."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
import requests

import utility


@pytest.mark.parametrize("seconds,expected", [(0, (0, 0, 0)), (59, (0, 0, 59)), (60, (0, 1, 0)), (3661, (1, 1, 1)), (90061, (25, 1, 1)), (1.6, (0, 0, 2))])
def test_seconds_convert_to_hours_minutes_seconds(seconds, expected):
    assert utility.getHMS(seconds) == expected


@pytest.mark.parametrize("timer,expected", [
    ("00:00:00", True), ("23:59:59", True), ("24:00:00", False),
    ("00:60:00", False), ("00:00:60", False), ("1:02:03", False),
    ("01:02:03 trailing", False), ("-1:00:00", False), ("", False),
])
def test_timer_format_requires_valid_clock_time(timer, expected):
    assert utility.checkTimerFormat(timer) is expected


def test_discord_countdown_preserves_epoch_seconds():
    assert utility.getHammerCountdown(np.datetime64("1970-01-01T00:16:40")) == "<t:1000:R>"


def test_resource_path_supports_development_and_bundle(monkeypatch, tmp_path):
    monkeypatch.delattr(utility.sys, "_MEIPASS", raising=False)
    assert Path(utility.getResourcePath("VERSION")) == Path(utility.__file__).resolve().parent / "VERSION"
    monkeypatch.setattr(utility.sys, "_MEIPASS", str(tmp_path), raising=False)
    assert Path(utility.getResourcePath("VERSION")) == tmp_path / "VERSION"


def test_current_version_reads_bundled_resource(monkeypatch, tmp_path):
    (tmp_path / "VERSION").write_text("1.2.3\n", encoding="utf-8")
    monkeypatch.setattr(utility.sys, "_MEIPASS", str(tmp_path), raising=False)
    assert utility.getCurrentVersion() == "1.2.3"


@pytest.mark.parametrize("platform,expected_parts", [
    ("win32", ("Saved Games", "Frontier Developments", "Elite Dangerous")),
    ("linux", (".local", "share", "Steam", "steamapps", "compatdata", "359320")),
])
def test_journal_path_selects_platform_layout(monkeypatch, tmp_path, platform, expected_parts):
    monkeypatch.setattr(utility.sys, "platform", platform)
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr(utility.os.path, "expanduser", lambda value: str(tmp_path))
    path = Path(utility.getJournalPath())
    assert str(path).startswith(str(tmp_path))
    assert all(part in path.parts for part in expected_parts)


def test_unsupported_journal_platform_has_no_default(monkeypatch):
    monkeypatch.setattr(utility.sys, "platform", "unsupported")
    assert utility.getJournalPath() is None


def test_local_settings_and_cache_paths_stay_in_app_dir(tmp_path):
    settings = Path(utility.getSettingsPath())
    assert settings.parent == Path(utility.getSettingsDir())
    assert Path(utility.getConfigSettingsPath()).parent == settings.parent
    first = utility.getCachePath("1", ["journal-one", "journal-two"])
    assert first == utility.getCachePath("1", ["journal-one", "journal-two"])
    assert first != utility.getCachePath("2", ["journal-one", "journal-two"])
    assert first != utility.getCachePath("1", ["journal-three"])
    assert Path(first).is_relative_to(Path(utility.getAppDir()))


@pytest.mark.parametrize("current,stable,prerelease,expected", [
    ("1.2.0", "1.2.1", None, True), ("1.2.0", "1.2.0", None, False),
    ("1.2.0", None, None, False), ("1.2.0rc1", "1.1.9", "1.2.0rc2", True),
    ("1.2.0", "1.1.9", "1.3.0rc1", False),
])
def test_update_selection_obeys_stable_and_prerelease_channels(monkeypatch, current, stable, prerelease, expected):
    monkeypatch.setattr(utility, "getCurrentVersion", lambda: current)
    monkeypatch.setattr(utility, "getLatestVersion", lambda: stable)
    monkeypatch.setattr(utility, "getLatestPrereleaseVersion", lambda: prerelease)
    assert utility.isUpdateAvailable() is expected


def test_prerelease_selection_filters_minor_and_invalid_names(monkeypatch):
    response = Mock()
    response.json.return_value = [
        {"prerelease": True, "name": "EDMT 1.2.0rc1"},
        {"prerelease": True, "name": "1.2.0rc3"},
        {"prerelease": True, "name": "EDMT 1.3.0rc9"},
        {"prerelease": True, "name": "not-a-version"},
        {"prerelease": False, "name": "EDMT 1.2.0"},
    ]
    monkeypatch.setattr(utility, "HTTP_SESSION", SimpleNamespace(get=Mock(return_value=response)))
    monkeypatch.setattr(utility, "getCurrentVersion", lambda: "1.2.0rc1")
    assert utility.getLatestPrereleaseVersion() == "1.2.0rc3"


@pytest.mark.parametrize("stable,prerelease,expected", [
    ("1.2.0", "1.2.0rc2", "1.2.0"), (None, "1.2.0rc2", "1.2.0rc2"),
    ("1.2.0", None, "1.2.0"), (None, None, None),
])
def test_prerelease_update_candidate_uses_highest_version(monkeypatch, stable, prerelease, expected):
    monkeypatch.setattr(utility, "getLatestVersion", lambda: stable)
    monkeypatch.setattr(utility, "getLatestPrereleaseVersion", lambda: prerelease)
    assert utility.getPrereleaseUpdateVersion() == expected


def test_latest_release_name_is_parsed(monkeypatch):
    response = Mock()
    response.json.return_value = {"name": "EDMT 1.2.3"}
    monkeypatch.setattr(utility, "HTTP_SESSION", SimpleNamespace(get=Mock(return_value=response)))
    assert utility.getLatestVersion() == "1.2.3"
    response.raise_for_status.assert_called_once_with()


@pytest.mark.parametrize("function", [utility.getLatestVersion, utility.getLatestPrereleaseVersion])
@pytest.mark.parametrize("failure", [requests.Timeout("timeout"), requests.HTTPError("503")])
def test_update_request_failure_returns_no_version(monkeypatch, function, failure):
    monkeypatch.setattr(utility, "HTTP_SESSION", SimpleNamespace(get=Mock(side_effect=failure)))
    assert function() is None
