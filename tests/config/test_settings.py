"""Tests for repo-provisioning settings."""

from baloo.config.settings import Settings


def test_repo_cache_enabled_defaults_to_true():
    assert Settings().repo_cache_enabled is True


def test_repo_cache_root_default():
    assert Settings().repo_cache_root == "/tmp/baloo-repo-cache"


def test_repo_cache_max_disk_gb_default():
    assert Settings().repo_cache_max_disk_gb == 10


def test_repo_cache_enabled_reads_env(monkeypatch):
    monkeypatch.setenv("REPO_CACHE_ENABLED", "false")
    assert Settings().repo_cache_enabled is False


def test_repo_sandbox_mode_defaults_to_bwrap():
    assert Settings().repo_sandbox_mode == "bwrap"


def test_repo_sandbox_mode_reads_env(monkeypatch):
    monkeypatch.setenv("REPO_SANDBOX_MODE", "off")
    assert Settings().repo_sandbox_mode == "off"


def test_documentation_drift_settings_defaults():
    s = Settings()
    assert s.documentation_drift_enabled is False
    assert s.documentation_drift_catalog_path == ".baloo/documentation-catalog.json"
    assert s.documentation_drift_model == "sonnet"
