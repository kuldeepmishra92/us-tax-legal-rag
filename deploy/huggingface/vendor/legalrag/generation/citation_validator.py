#!/usr/bin/env python3
"""
citation_validator.py — the hallucination guard for Phase 5.

The LLM is instructed to cite every factual claim with a [N] marker pointing
at one of the numbered source excerpts it was given. This module verifies,
deterministically (no LLM, no network), that:
  - every [N] the answer used actually corresponds to a source that was
    provided (a marker outside the provided range = a fabricated citation)
  - a substantive answer carries at least one citation (uncited claims in a
    legal answer are exactly what we must not ship)
  - a proper "not in the sources" refusal is recognized as validly grounded
    (refusing when the answer isn't in the corpus is correct behavior, not a
    failure)

This is a structural/traceability guarantee — it proves each citation points
at a real retrieved source. Semantic faithfulness (does the cited text
actually support the claim) is the harder, LLM-judged check that Phase 8's
RAGAS evaluation handles; here we lock down the part that can be proven exactly.
"""
import re

REFUSAL_MARKER = "could not find the answer in the provided legal sources"

def extract_markers(answer_text):
    """Return the sorted unique set of citation numbers used in the answer.
    Handles all the formats LLMs actually emit: [1], [1][2], and comma/space
    separated groups like [1, 5] or [1,5] — a plain \\[(\\d+)\\] regex would
    silently miss the grouped forms and wrongly flag a cited answer as uncited."""
    markers = set()
    for group in re.findall(r"\[([\d,\s]+)\]", answer_text):
        for num in re.findall(r"\d+", group):
            markers.add(int(num))
    return sorted(markers)

def is_refusal(answer_text):
    return REFUSAL_MARKER in answer_text.lower()

def validate(answer_text, sources):
    """sources: list of dicts each with a 'marker' int (1-based) and metadata.
    Returns a dict describing whether the answer is properly grounded."""
    valid_markers = {s["marker"] for s in sources}
    used = extract_markers(answer_text)
    invalid = [m for m in used if m not in valid_markers]
    refusal = is_refusal(answer_text)
    has_citation = len(used) > 0

    # grounded when: no fabricated markers, AND (it cited something OR it
    # properly refused because the answer wasn't in the sources)
    grounded = (len(invalid) == 0) and (has_citation or refusal)

    resolved = [s for s in sources if s["marker"] in used]
    return {
        "grounded": grounded,
        "used_markers": used,
        "invalid_markers": invalid,   # non-empty => fabricated citation(s)
        "has_citation": has_citation,
        "is_refusal": refusal,
        "resolved_citations": resolved,
    }
