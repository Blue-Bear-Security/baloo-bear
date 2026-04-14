"""Version and build information for Baloo."""

import os

# These will be set by the Docker build process
# If not set (local dev), fallback to environment or 'dev'
VERSION = os.getenv("BALOO_VERSION", "dev")
COMMIT_SHA = os.getenv("BALOO_COMMIT_SHA", "unknown")
BUILD_DATE = os.getenv("BALOO_BUILD_DATE", "unknown")


def get_version_info() -> str:
    """Get formatted version information string."""
    if VERSION == "dev":
        return f"Baloo v{VERSION} (local development)"

    # Only truncate if it's a real SHA (not 'unknown', 'dev', or empty)
    commit_display = COMMIT_SHA[:8] if COMMIT_SHA not in ('unknown', 'dev', '') and len(COMMIT_SHA) >= 8 else COMMIT_SHA
    return f"Baloo v{VERSION} (commit: {commit_display}, built: {BUILD_DATE})"
