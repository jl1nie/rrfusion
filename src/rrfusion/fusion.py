"""RRF fusion and frontier helpers."""

from __future__ import annotations

from collections import defaultdict
from typing import Sequence

from .models import BlendFrontierEntry


def compute_rrf_scores(
    lanes: dict[str, Sequence[tuple[str, float]]],
    rrf_k: int,
    weights: dict[str, float],
) -> tuple[dict[str, float], dict[str, dict[str, float]]]:
    total_scores: dict[str, float] = defaultdict(float)
    contributions: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))

    for lane, docs in lanes.items():
        lane_weight = weights.get(lane, weights.get("recall" if lane == "fulltext" else "semantic", 1.0))
        for rank, (doc_id, _original) in enumerate(docs, start=1):
            score = lane_weight / (rrf_k + rank)
            total_scores[doc_id] += score
            key = "recall" if lane == "fulltext" else "semantic"
            contributions[doc_id][key] += score
    return total_scores, contributions


def apply_code_boosts(
    scores: dict[str, float],
    contributions: dict[str, dict[str, float]],
    doc_codes: dict[str, dict[str, list[str]]],
    target_profile: dict[str, dict[str, float]],
    weights: dict[str, float],
) -> dict[str, float]:
    code_weight = weights.get("code", 0.0)
    if not code_weight or not target_profile:
        return scores

    for doc_id, tax_map in doc_codes.items():
        boost = 0.0
        for taxonomy, codes in tax_map.items():
            desired = target_profile.get(taxonomy, {})
            for code in codes:
                boost += desired.get(code, 0.0)
        if boost <= 0:
            continue
        boost_score = boost * code_weight
        scores[doc_id] += boost_score
        contributions[doc_id]["code"] = contributions[doc_id].get("code", 0.0) + boost_score
    return scores


def sort_scores(scores: dict[str, float]) -> list[tuple[str, float]]:
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)


def compute_frontier(
    ordered_docs: list[str],
    k_grid: Sequence[int],
    relevant_flags: dict[str, bool],
    beta_fuse: float,
) -> list[BlendFrontierEntry]:
    total_relevant = sum(1 for flag in relevant_flags.values() if flag)
    if total_relevant == 0:
        total_relevant = max(1, len(ordered_docs))

    frontier: list[BlendFrontierEntry] = []
    for k in k_grid:
        if k <= 0 or not ordered_docs:
            continue
        top_subset = ordered_docs[: min(k, len(ordered_docs))]
        relevant_found = sum(1 for doc_id in top_subset if relevant_flags.get(doc_id))
        precision = relevant_found / len(top_subset)
        recall = relevant_found / total_relevant
        beta_sq = beta_fuse * beta_fuse
        if precision == 0 and recall == 0:
            f_beta = 0.0
        else:
            f_beta = (1 + beta_sq) * precision * recall / (beta_sq * precision + recall)
        frontier.append(
            BlendFrontierEntry(
                k=len(top_subset),
                P_star=round(precision, 3),
                R_star=round(recall, 3),
                F_beta_star=round(f_beta, 3),
            )
        )
    return frontier


def aggregate_code_freqs(
    doc_meta: dict[str, dict[str, list[str]]],
    doc_ids: Sequence[str],
) -> dict[str, dict[str, int]]:
    freqs: dict[str, dict[str, int]] = {"ipc": defaultdict(int), "cpc": defaultdict(int)}  # type: ignore[assignment]
    for doc_id in doc_ids:
        meta = doc_meta.get(doc_id)
        if not meta:
            continue
        for taxonomy in ("ipc", "cpc"):
            for code in meta.get(f"{taxonomy}_codes", []):
                freqs[taxonomy][code] += 1
    return {
        taxonomy: dict(sorted(values.items(), key=lambda x: x[1], reverse=True))
        for taxonomy, values in freqs.items()
    }


def compute_relevance_flags(
    doc_meta: dict[str, dict[str, list[str]]],
    target_profile: dict[str, dict[str, float]],
) -> dict[str, bool]:
    if not target_profile:
        return {doc_id: True for doc_id in doc_meta.keys()}
    flags: dict[str, bool] = {}
    for doc_id, meta in doc_meta.items():
        score = 0.0
        for taxonomy, codes in meta.items():
            if not taxonomy.endswith("_codes"):
                continue
            tax = taxonomy.replace("_codes", "")
            desired = target_profile.get(tax, {})
            for code in codes:
                score += desired.get(code, 0.0)
        flags[doc_id] = score > 0
    return flags


__all__ = [
    "compute_rrf_scores",
    "apply_code_boosts",
    "sort_scores",
    "compute_frontier",
    "aggregate_code_freqs",
    "compute_relevance_flags",
]
