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


def compute_code_scores(
    doc_meta: dict[str, dict[str, list[str]]],
    target_profile: dict[str, dict[str, float]],
) -> dict[str, float]:
    """Compute normalized code overlap scores (0-1) per document."""
    if not target_profile:
        return {doc_id: 1.0 for doc_id in doc_meta.keys()}

    raw_scores: dict[str, float] = {}
    max_score = 0.0
    for doc_id, meta in doc_meta.items():
        score = 0.0
        for taxonomy in ("ipc", "cpc", "fi", "ft"):
            desired = target_profile.get(taxonomy, {})
            for code in meta.get(f"{taxonomy}_codes", []):
                score += desired.get(code, 0.0)
        raw_scores[doc_id] = score
        max_score = max(max_score, score)

    if max_score <= 0:
        return {doc_id: 1.0 for doc_id in doc_meta.keys()}
    return {doc_id: score / max_score for doc_id, score in raw_scores.items()}


def compute_facet_score(
    doc_meta: dict[str, dict[str, str]],
    facet_terms: dict[str, Sequence[str]],
    facet_weights: dict[str, float] | None = None,
) -> dict[str, float]:
    """Compute coverage scores for A/B/C components using claim/abst/desc text."""
    if not facet_terms:
        return {doc_id: 1.0 for doc_id in doc_meta.keys()}

    field_weights = {"claim": 0.5, "abst": 0.3, "desc": 0.2}
    normalized_weights = {}
    total_weight = 0.0
    for comp in facet_terms:
        weight = facet_weights.get(comp, 1.0) if facet_weights else 1.0
        normalized_weights[comp] = max(weight, 0.0)
        total_weight += normalized_weights[comp]
    if total_weight == 0:
        total_weight = float(len(facet_terms))

    facet_scores: dict[str, float] = {}
    for doc_id, meta in doc_meta.items():
        score = 0.0
        for comp, terms in facet_terms.items():
            comp_score = 0.0
            for field, weight in field_weights.items():
                text = meta.get(field, "").lower()
                if not text:
                    continue
                for term in terms:
                    if term.lower() in text:
                        comp_score += weight
                        break
            score += normalized_weights.get(comp, 1.0) * comp_score
        facet_scores[doc_id] = min(score / total_weight, 1.0)
    return facet_scores


def compute_lane_consistency(
    lane_ranks: dict[str, dict[str, int]],
    lane_weights: dict[str, float],
) -> dict[str, float]:
    """Reward documents that rank highly across multiple lanes."""
    consistency: dict[str, float] = {}
    max_score = 0.0
    for doc_id, ranks in lane_ranks.items():
        score = 0.0
        for lane, rank in ranks.items():
            weight = lane_weights.get(lane, 1.0)
            score += weight / (rank + 1)
        consistency[doc_id] = score
        max_score = max(max_score, score)
    if max_score == 0:
        return {doc_id: 0.0 for doc_id in lane_ranks.keys()}
    return {doc_id: score / max_score for doc_id, score in consistency.items()}


def compute_pi_scores(
    doc_meta: dict[str, dict[str, str]],
    target_profile: dict[str, dict[str, float]],
    facet_terms: dict[str, Sequence[str]],
    facet_weights: dict[str, float],
    lane_ranks: dict[str, dict[str, int]],
    lane_weights: dict[str, float],
    pi_weights: dict[str, float],
) -> dict[str, float]:
    """Combine code/facet/lane signals into a normalized π'(d)."""
    code_scores = compute_code_scores(doc_meta, target_profile)
    facet_scores = compute_facet_score(doc_meta, facet_terms, facet_weights)
    consistency_scores = compute_lane_consistency(lane_ranks, lane_weights)

    pi_scores: dict[str, float] = {}
    for doc_id in doc_meta.keys():
        raw = (
            pi_weights.get("code", 0.0) * code_scores.get(doc_id, 0.0)
            + pi_weights.get("facet", 0.0) * facet_scores.get(doc_id, 0.0)
            + pi_weights.get("lane", 0.0) * consistency_scores.get(doc_id, 0.0)
        )
        pi_scores[doc_id] = 1 / (1 + pow(2.71828, -raw))
    return pi_scores


def compute_lane_ranks(lane_docs: dict[str, Sequence[tuple[str, float]]]) -> dict[str, dict[str, int]]:
    ranks: dict[str, dict[str, int]] = defaultdict(dict)
    for lane, docs in lane_docs.items():
        for idx, (doc_id, _) in enumerate(docs, start=1):
            ranks[doc_id][lane] = idx
    return ranks


def compute_frontier(
    ordered_docs: list[str],
    k_grid: Sequence[int],
    pi_scores: dict[str, float],
    beta_fuse: float,
) -> list[BlendFrontierEntry]:
    """Estimate precision/recall/Fβ frontier using π'(d) scores."""
    if not ordered_docs:
        return []

    total_score = sum(pi_scores.get(doc_id, 0.0) for doc_id in ordered_docs)
    if total_score <= 0.0:
        # evenly distribute if all scores zero
        total_score = float(len(ordered_docs))
        uniform = {doc_id: 1.0 for doc_id in ordered_docs}
    else:
        uniform = {doc_id: pi_scores.get(doc_id, 0.0) for doc_id in ordered_docs}

    frontier: list[BlendFrontierEntry] = []
    beta_sq = beta_fuse * beta_fuse
    for k in k_grid:
        if k <= 0:
            continue
        subset = ordered_docs[: min(k, len(ordered_docs))]
        if not subset:
            continue
        sum_top = sum(uniform.get(doc_id, 0.0) for doc_id in subset)
        precision = sum_top / len(subset)
        recall = sum_top / total_score if total_score > 0 else 0.0
        if precision == 0.0 and recall == 0.0:
            f_beta = 0.0
        else:
            f_beta = (1 + beta_sq) * precision * recall / (beta_sq * precision + recall)
        frontier.append(
            BlendFrontierEntry(
                k=len(subset),
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
    TAXONOMIES = ("ipc", "cpc", "fi", "ft")
    freqs: dict[str, dict[str, int]] = {
        taxonomy: defaultdict(int) for taxonomy in TAXONOMIES  # type: ignore[assignment]
    }
    for doc_id in doc_ids:
        meta = doc_meta.get(doc_id)
        if not meta:
            continue
        for taxonomy in TAXONOMIES:
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
    "compute_code_scores",
    "compute_facet_score",
    "compute_frontier",
    "compute_lane_consistency",
    "compute_lane_ranks",
    "compute_pi_scores",
    "aggregate_code_freqs",
    "compute_relevance_flags",
]
