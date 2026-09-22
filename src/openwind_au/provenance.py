# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 Elandu and contributors

"""Source and licence provenance for OpenWind-AU."""

from __future__ import annotations

import json
import os
from importlib.metadata import PackageNotFoundError, distribution

SOURCE_URL = "https://github.com/Elandu/OpenWind-AU"
LICENSE_ID = "AGPL-3.0-only"


def source_revision() -> str:
    """Return the deployed/package VCS revision when available."""

    configured = os.environ.get("OPENWIND_SOURCE_REVISION", "").strip()
    if configured:
        return configured

    try:
        installed = distribution("openwind-au")
    except PackageNotFoundError:
        return "unknown"

    direct_url_text = installed.read_text("direct_url.json")
    if not direct_url_text:
        return "unknown"

    try:
        direct_url = json.loads(direct_url_text)
    except json.JSONDecodeError:
        return "unknown"

    vcs_info = direct_url.get("vcs_info")
    if not isinstance(vcs_info, dict):
        return "unknown"

    commit_id = vcs_info.get("commit_id")
    return str(commit_id) if commit_id else "unknown"
