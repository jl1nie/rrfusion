from rrfusion.fusion import (
    aggregate_code_freqs,
    apply_code_boosts,
    compute_frontier,
    compute_relevance_flags,
    compute_rrf_scores,
    sort_scores,
)


def test_rrf_scores_with_code_boosts():
    lanes = {
        "fulltext": [("A", 1.0), ("B", 0.9)],
        "semantic": [("A", 0.95), ("C", 0.5)],
    }
    weights = {"recall": 1.0, "semantic": 0.5, "code": 0.3}
    scores, contrib = compute_rrf_scores(lanes, rrf_k=60, weights=weights)
    assert scores["A"] > scores["B"] > 0

    doc_codes = {
        "A": {"ipc": ["H04L"], "cpc": ["H04L9/32"], "fi": ["H04L1/00"], "ft": ["432"]},
        "B": {"ipc": ["G06F"], "cpc": [], "fi": [], "ft": ["562"]},
        "C": {"ipc": ["H04L"], "cpc": [], "fi": ["H04W24/00"], "ft": []},
    }
    target_profile = {"ipc": {"H04L": 1.0}}
    boosted = apply_code_boosts(scores, contrib, doc_codes, target_profile, weights)
    assert boosted["A"] > boosted["B"]
    assert "code" in contrib["A"]


def test_frontier_and_freqs():
    doc_meta = {
        "A": {
            "ipc_codes": ["H04L"],
            "cpc_codes": ["H04L9/32"],
            "fi_codes": ["H04L1/00"],
            "ft_codes": ["432"],
        },
        "B": {
            "ipc_codes": ["G06F"],
            "cpc_codes": [],
            "fi_codes": [],
            "ft_codes": ["562"],
        },
        "C": {
            "ipc_codes": ["H04L"],
            "cpc_codes": [],
            "fi_codes": ["H04W24/00"],
            "ft_codes": [],
        },
    }
    target_profile = {"ipc": {"H04L": 1.0}}
    flags = compute_relevance_flags(doc_meta, target_profile)
    ordered = ["A", "B", "C"]
    frontier = compute_frontier(ordered, [1, 2, 3], flags, beta=1.0)
    assert frontier[0].P_star == 1.0
    freqs = aggregate_code_freqs(doc_meta, ordered[:2])
    assert freqs["ipc"]["H04L"] == 1
    assert freqs["fi"]["H04L1/00"] == 1
    assert freqs["ft"]["432"] == 1


def test_aggregate_code_freqs_includes_fi_ft():
    doc_meta = {
        "A": {
            "ipc_codes": ["H04L"],
            "cpc_codes": ["H04L9/32"],
            "fi_codes": ["H04L1/00", "H04W24/00"],
            "ft_codes": ["432"],
        },
        "B": {
            "ipc_codes": ["G06F"],
            "cpc_codes": ["G06F3/00"],
            "fi_codes": ["H04L1/00"],
            "ft_codes": ["562"],
        },
    }
    freqs = aggregate_code_freqs(doc_meta, list(doc_meta))
    assert freqs["fi"]["H04L1/00"] == 2
    assert freqs["ft"]["562"] == 1


def test_sort_scores_orders_desc():
    scores = {"A": 0.5, "B": 0.8, "C": 0.1}
    ordered = sort_scores(scores)
    assert ordered[0][0] == "B"
