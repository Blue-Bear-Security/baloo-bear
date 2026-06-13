"""Load documentation drift catalogs from a provisioned repository."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from pydantic import ValidationError

from baloo.documentation.models import DocumentationCatalog

logger = logging.getLogger(__name__)


def load_documentation_catalog(
    repo_path: str | None,
    catalog_path: str,
) -> DocumentationCatalog | None:
    """Load and validate a repo-owned documentation drift catalog."""
    if repo_path is None:
        return None

    repo_root = Path(repo_path).resolve()
    catalog_requested = Path(catalog_path)
    if catalog_requested.is_absolute():
        logger.warning("Ignoring absolute documentation catalog path: %s", catalog_path)
        return None

    catalog_resolved = (repo_root / catalog_requested).resolve()
    if not catalog_resolved.is_relative_to(repo_root):
        logger.warning("Ignoring documentation catalog outside repo: %s", catalog_path)
        return None

    if not catalog_resolved.exists():
        return None

    try:
        data = json.loads(catalog_resolved.read_text(encoding="utf-8"))
        return DocumentationCatalog.model_validate(data)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        logger.warning("Invalid documentation catalog at %s: %s", catalog_path, exc)
        return None
