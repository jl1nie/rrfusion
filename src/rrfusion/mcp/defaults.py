"""Canonical defaults for MCP fusion tuning."""

from __future__ import annotations

from typing import Dict, List

FUSION_DEFAULT_WEIGHTS: Dict[str, float] = {
    "fulltext": 1.0,
    "semantic": 0.7,
    "code": 0.5,
}

FUSION_DEFAULT_RRF_K = 80
FUSION_DEFAULT_BETA_FUSE = 1.5

FUSION_DEFAULT_TOP_M_PER_LANE: Dict[str, int] = {
    "fulltext": 10000,
    "semantic": 10000,
}

FUSION_DEFAULT_K_GRID: List[int] = [10, 20, 30, 40, 50, 80, 100]
