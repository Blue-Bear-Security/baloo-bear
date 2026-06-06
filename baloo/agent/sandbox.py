"""Filesystem sandbox for the agent subprocess.

Builds a `bwrap` (bubblewrap) argv prefix that limits the agent's filesystem
view to a single worktree, read-only. This enforces the multi-tenant boundary:
even a prompt-injected agent reading absolute paths cannot reach another
tenant's repo cache.

Network is intentionally left shared — the agent must call the model API. Only
the filesystem is restricted.

When the sandbox engages, the subprocess is also spawned with a scrubbed,
allowlisted environment (`build_subprocess_env`) so baloo's secrets (GitHub
key, DB creds, etc.) are not exposed to a potentially prompt-injected agent
that has open network access — filesystem isolation alone does not address
exfiltration.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

_bwrap_works: bool | None = None  # cached runtime-probe result


def sandbox_available(mode: str) -> bool:
    """Return True if the sandbox for `mode` is present AND actually runnable.

    `which bwrap` is not enough: bubblewrap needs unprivileged user namespaces,
    which hardened platforms (some k8s/seccomp/AppArmor/gVisor setups) block. If
    we only checked for the binary, every review would crash at the bwrap layer
    on such platforms with no fallback. So we probe once (cached) by actually
    running a trivial bwrap invocation.
    """
    global _bwrap_works
    if mode != "bwrap":
        return False
    if shutil.which("bwrap") is None:
        return False
    if _bwrap_works is None:
        try:
            proc = subprocess.run(
                ["bwrap", "--ro-bind", "/", "/", "--", "true"],
                capture_output=True,
                timeout=5,
            )
            _bwrap_works = proc.returncode == 0
        except Exception:
            _bwrap_works = False
    return _bwrap_works


def build_sandbox_prefix(mode: str, worktree: str) -> list[str]:
    """Return the argv prefix to wrap a tool-using pi command.

    The returned list ends with "--"; append the real command after it.
    Returns [] for any mode other than 'bwrap'.
    """
    if mode != "bwrap":
        return []

    wt = str(Path(worktree).resolve())
    return [
        "bwrap",
        # Minimal runtime: system dirs needed for node/pi to run.
        "--ro-bind",
        "/usr",
        "/usr",
        "--ro-bind",
        "/bin",
        "/bin",
        "--ro-bind",
        "/lib",
        "/lib",
        "--ro-bind-try",
        "/lib64",
        "/lib64",
        "--ro-bind-try",
        "/opt",
        "/opt",
        # DNS: glibc getaddrinfo reads nsswitch.conf + hosts, not just resolv.conf.
        # Without these, resolving api.anthropic.com can fail despite resolv.conf.
        "--ro-bind-try",
        "/etc/resolv.conf",
        "/etc/resolv.conf",
        "--ro-bind-try",
        "/etc/nsswitch.conf",
        "/etc/nsswitch.conf",
        "--ro-bind-try",
        "/etc/hosts",
        "/etc/hosts",
        "--ro-bind-try",
        "/etc/ssl",
        "/etc/ssl",
        "--ro-bind-try",
        "/etc/ca-certificates",
        "/etc/ca-certificates",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        # Fresh /tmp hides the repo cache (which lives under /tmp); the worktree
        # is bound afterwards so it overlays the tmpfs at its real path.
        "--tmpfs",
        "/tmp",
        "--ro-bind",
        wt,
        wt,
        "--chdir",
        wt,
        "--unshare-pid",
        "--unshare-ipc",
        "--unshare-uts",
        "--die-with-parent",
        "--",
    ]


# Env vars the sandboxed agent legitimately needs. Everything else (notably
# baloo's GitHub/DB/dashboard secrets) is dropped so a prompt-injected agent
# cannot read them from /proc/self/environ and exfiltrate over the open network.
_ENV_ALLOWLIST = frozenset(
    {
        "PATH",
        "HOME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TZ",
        "TERM",
        # Model providers (only the one in use is present; all listed for safety).
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "OPENAI_API_KEY",
        # Corporate proxy config — REQUIRED in enterprise networks or the agent
        # cannot reach the model API and every review fails. Both cases since some
        # tools read upper- and others lower-case.
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "no_proxy",
        "all_proxy",
        # CA bundle location if the image sets it explicitly.
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "NODE_EXTRA_CA_CERTS",
        "REQUESTS_CA_BUNDLE",
    }
)


def build_subprocess_env(base_env: dict[str, str]) -> dict[str, str]:
    """Return a minimal env (allowlist only) for the sandboxed subprocess.

    Defaults HOME to /tmp so node/pi have a writable home inside the tmpfs even
    if the inherited HOME points at a path the sandbox does not bind writable.
    """
    env = {k: v for k, v in base_env.items() if k in _ENV_ALLOWLIST}
    env.setdefault("HOME", "/tmp")
    return env
