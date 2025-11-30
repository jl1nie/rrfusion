#!/usr/bin/env python3
"""Remove representative review workflow from SystemPrompt_v1_5.yaml"""

import re
from pathlib import Path

def remove_representatives():
    prompt_path = Path(__file__).parent.parent / "prompts" / "SystemPrompt_v1_5.yaml"
    content = prompt_path.read_text()

    # 1. Update header comment
    content = content.replace(
        "#   Phase1: Representative hunting (20-50 representative patents)",
        "#   Phase1: Feature extraction + code profiling + fusion"
    )

    # 2. Update agent.role description
    content = content.replace(
        "    You follow a three-phase pipeline: Phase0 (profiling), Phase1 (representative hunting),",
        "    You follow a three-phase pipeline: Phase0 (profiling), Phase1 (precision fusion),"
    )

    # 3. Remove representatives tool from agent_tools
    content = re.sub(
        r'\s+representatives:.*\n',
        '\n',
        content
    )

    # 4. Update Phase1 description in global_policies
    content = content.replace(
        "    - Phase1: Find 20-50 representative patents using rrf_search_fulltext_raw (precision query).",
        "    - Phase1: Extract features, profile codes, and create initial fusion with target_profile + facet_terms."
    )

    # 5. Update Phase2 semantic description
    content = content.replace(
        "    - In Phase2, semantic lanes MUST use HyDE summaries generated from Phase1 representative terms, NOT raw user text.",
        "    - In Phase2, semantic lanes MUST use HyDE summaries generated from Phase1 vocabulary, NOT raw user text."
    )

    # 6. Remove representative_review_confirmation section (will need to find exact lines)
    content = re.sub(
        r'  representative_review_confirmation:.*?\n(?=  \w|\n# |\Z)',
        '',
        content,
        flags=re.DOTALL
    )

    # 7. Update phase1_representative_hunting section
    content = re.sub(
        r'  phase1_representative_hunting:.*?(?=\n  \w|\Z)',
        '''  phase1_precision_fusion:
    description: "Extract features, profile codes, and create precision fusion"
    steps:
      - "Extract A/A'/A''/B/C elements from invention disclosure"
      - "Profile FI/FT codes using code_profiling"
      - "User confirms target_profile + facet_terms"
      - "Execute rrf_blend_frontier with confirmed parameters"
      - "Review results with peek_snippets"
    completion_criteria:
      - "Fusion run created with target_profile + facet_terms"
      - "F_proxy ≥ 0.5 indicates healthy frontier"
      - "Code coverage includes expected technical elements"''',
        content,
        flags=re.DOTALL
    )

    # 8. Remove register_representatives from tool_usage
    content = re.sub(
        r'  register_representatives:.*?\n(?=  \w|\n# |\Z)',
        '',
        content,
        flags=re.DOTALL
    )

    # 9. Update references to "representative" in workflow sections
    content = re.sub(
        r'representative patents',
        'precision candidates',
        content,
        flags=re.IGNORECASE
    )

    content = re.sub(
        r'(\d+)-(\d+) representative',
        r'\1-\2 precision',
        content
    )

    # 10. Update any references to A/B/C labeling
    content = re.sub(
        r'A/B/C representatives',
        'facet_terms classification',
        content
    )

    # Write back
    prompt_path.write_text(content)
    print(f"✅ Updated {prompt_path}")

if __name__ == "__main__":
    remove_representatives()
