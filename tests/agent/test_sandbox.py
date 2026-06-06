"""Tests for the agent filesystem sandbox command builder."""

from baloo.agent import sandbox


def test_off_mode_returns_empty_prefix():
    assert sandbox.build_sandbox_prefix("off", "/work/tree") == []


def test_bwrap_prefix_binds_only_the_worktree_and_chdirs(tmp_path):
    wt = tmp_path / "wt"
    wt.mkdir()
    prefix = sandbox.build_sandbox_prefix("bwrap", str(wt))

    assert prefix[0] == "bwrap"
    assert prefix[-1] == "--"  # command follows the prefix
    # worktree is bound read-only at its own path and is the working dir
    assert "--ro-bind" in prefix
    assert str(wt.resolve()) in prefix
    chdir_idx = prefix.index("--chdir")
    assert prefix[chdir_idx + 1] == str(wt.resolve())
    # /tmp is a fresh tmpfs so the cache root (also under /tmp) is hidden
    assert "--tmpfs" in prefix and "/tmp" in prefix


def test_bwrap_prefix_shares_network(tmp_path):
    # The agent must reach the model API; network namespace must NOT be unshared.
    prefix = sandbox.build_sandbox_prefix("bwrap", str(tmp_path))
    assert "--unshare-net" not in prefix


def test_probe_cmd_mirrors_real_prefix_privileged_ops():
    # A weak probe (e.g. `bwrap --ro-bind / / -- true`) passes on hardened
    # platforms where the real prefix's `--proc`/`--unshare-pid` then fail —
    # a false positive that crashes reviews instead of degrading. Lock the
    # probe to the operations that actually fail.
    assert "--proc" in sandbox._PROBE_CMD
    assert "--unshare-pid" in sandbox._PROBE_CMD
    # dynamic loader must be available or exec fails misleadingly
    assert "/lib" in sandbox._PROBE_CMD


def test_sandbox_available_off_is_false():
    assert sandbox.sandbox_available("off") is False


def test_sandbox_available_false_when_binary_missing(monkeypatch):
    monkeypatch.setattr(sandbox, "_bwrap_works", None)
    monkeypatch.setattr(sandbox.shutil, "which", lambda name: None)
    assert sandbox.sandbox_available("bwrap") is False


def test_sandbox_available_probes_runtime_when_binary_present(monkeypatch):
    # Binary present but the runtime probe decides whether it actually works.
    monkeypatch.setattr(sandbox, "_bwrap_works", None)
    monkeypatch.setattr(sandbox.shutil, "which", lambda name: "/usr/bin/bwrap")

    ok = type("P", (), {"returncode": 0})()
    monkeypatch.setattr(sandbox.subprocess, "run", lambda *a, **k: ok)
    assert sandbox.sandbox_available("bwrap") is True

    # Binary present but userns blocked → probe returns non-zero → unavailable.
    monkeypatch.setattr(sandbox, "_bwrap_works", None)
    bad = type("P", (), {"returncode": 1})()
    monkeypatch.setattr(sandbox.subprocess, "run", lambda *a, **k: bad)
    assert sandbox.sandbox_available("bwrap") is False


def test_sandbox_available_probe_result_is_cached(monkeypatch):
    # After the first probe, the result is reused without re-running bwrap.
    monkeypatch.setattr(sandbox, "_bwrap_works", None)
    monkeypatch.setattr(sandbox.shutil, "which", lambda name: "/usr/bin/bwrap")
    calls = {"n": 0}

    def fake_run(*a, **k):
        calls["n"] += 1
        return type("P", (), {"returncode": 0})()

    monkeypatch.setattr(sandbox.subprocess, "run", fake_run)
    assert sandbox.sandbox_available("bwrap") is True
    assert sandbox.sandbox_available("bwrap") is True
    assert calls["n"] == 1


def test_build_subprocess_env_drops_secrets_keeps_runtime(monkeypatch):
    base = {
        "PATH": "/usr/bin",
        "HOME": "/root",
        "LANG": "C.UTF-8",
        "ANTHROPIC_API_KEY": "sk-keep",
        "GEMINI_API_KEY": "g-keep",
        "OPENAI_API_KEY": "oa-keep",
        "HTTPS_PROXY": "http://proxy.corp:8080",
        "https_proxy": "http://proxy.corp:8080",
        "NO_PROXY": "localhost",
        "GITHUB_PRIVATE_KEY": "SECRET",
        "GITHUB_WEBHOOK_SECRET": "SECRET",
        "DATABASE_URL": "postgres://SECRET",
        "POSTGRES_PASSWORD": "SECRET",
        "DASHBOARD_PASSWORD": "SECRET",
    }
    env = sandbox.build_subprocess_env(base)

    # Model + runtime + proxy vars survive (proxy required in enterprise networks).
    assert env["ANTHROPIC_API_KEY"] == "sk-keep"
    assert env["GEMINI_API_KEY"] == "g-keep"
    assert env["OPENAI_API_KEY"] == "oa-keep"
    assert env["HTTPS_PROXY"] == "http://proxy.corp:8080"
    assert env["https_proxy"] == "http://proxy.corp:8080"
    assert env["NO_PROXY"] == "localhost"
    assert env["PATH"] == "/usr/bin"
    assert env["HOME"] == "/root"
    # No baloo secret leaks through.
    for leaked in (
        "GITHUB_PRIVATE_KEY",
        "GITHUB_WEBHOOK_SECRET",
        "DATABASE_URL",
        "POSTGRES_PASSWORD",
        "DASHBOARD_PASSWORD",
    ):
        assert leaked not in env
