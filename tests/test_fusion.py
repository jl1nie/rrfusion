from rrfusion.fusion import (
    aggregate_code_freqs,
    apply_code_boosts,
    compute_code_scores,
    compute_facet_score,
    compute_frontier,
    compute_lane_consistency,
    compute_pi_scores,
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
    scores = compute_code_scores(doc_meta, target_profile)
    ordered = ["A", "B", "C"]
    frontier = compute_frontier(ordered, [1, 2, 3], scores, beta_fuse=1.0)
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


def test_compute_facet_score_honors_synonyms():
    doc_meta = {
        "A": {"claim": "顔認証装置とマスク検出", "abst": "", "desc": ""},
        "B": {"claim": "マスク検出を含む制御", "abst": "", "desc": ""},
        "C": {"claim": "照準制御", "abst": "", "desc": ""},
    }
    facet_terms = {
        "A": ["顔認証", "face recognition"],
        "B": ["マスク検出", "mask detection"],
    }
    scores = compute_facet_score(doc_meta, facet_terms)
    assert scores["A"] > 0.0
    assert scores["B"] > 0.0
    assert scores["C"] == 0.0


def test_compute_lane_consistency_prefers_multi_lane_documents():
    lane_ranks = {
        "A": {"fulltext": 1, "semantic": 2},
        "B": {"fulltext": 1},
        "C": {"semantic": 1},
    }
    lane_weights = {"fulltext": 1.0, "semantic": 0.5}
    consistency = compute_lane_consistency(lane_ranks, lane_weights)
    assert consistency["A"] == 1.0
    assert consistency["B"] < 1.0
    assert consistency["C"] < consistency["A"]


def test_compute_pi_scores_combines_signals():
    doc_meta = {
        "A": {
            "claim": "顔認証装置",
            "abst": "mask aware authentication",
            "desc": "",
            "ipc_codes": ["H04L"],
            "cpc_codes": [],
            "fi_codes": [],
            "ft_codes": [],
        },
        "B": {
            "claim": "照準装置",
            "abst": "",
            "desc": "",
            "ipc_codes": ["G06F"],
            "cpc_codes": [],
            "fi_codes": [],
            "ft_codes": [],
        },
    }
    target_profile = {"ipc": {"H04L": 1.0}}
    facet_terms = {"A": ["顔認証", "mask aware"], "B": ["照準"]}
    lane_ranks = {"A": {"fulltext": 1}, "B": {"fulltext": 5}}
    lane_weights = {"fulltext": 1.0}
    pi_weights = {"code": 0.4, "facet": 0.4, "lane": 0.2}
    scores = compute_pi_scores(
        doc_meta,
        target_profile,
        facet_terms,
        facet_weights={"A": 0.5, "B": 0.5},
        lane_ranks=lane_ranks,
        lane_weights=lane_weights,
        pi_weights=pi_weights,
    )
    assert scores["A"] > scores["B"]


def test_compute_frontier_uses_pi_scores_for_precision():
    ordered_docs = ["A", "B"]
    pi_scores = {"A": 0.9, "B": 0.1}
    frontier = compute_frontier(ordered_docs, [1, 2], pi_scores, beta_fuse=1.0)
    assert frontier[0].P_star == 0.9
    assert frontier[1].P_star < frontier[0].P_star
