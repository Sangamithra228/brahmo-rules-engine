"""
Derivability scoring - deterministic, offline, ZERO LLM.

The question the assessment poses: how do you decide that "Paracetamol is an
analgesic" is a waste of tokens while "Supra uses Paracetamol 650mg QDS as
first-line post-TKR pain" is not, without asking a model?

Observation: those two sentences are not distinguished by their TOPIC. Both
are about paracetamol. They are distinguished by whether the sentence contains
anything that could only be true at THIS organisation. A general-knowledge
statement is one that would appear in a textbook unchanged. An organisational
statement carries a fingerprint - a hospital name, a named clinician, a rupee
figure, a local incident, a policy verb, a specific patient.

So the score is built from two opposing signal families:

  GENERIC signals push the score UP (more derivable):
    - definitional phrasing: "X is a ...", "Also called ...", "Normal ... are"
    - textbook framing: "Risk factors:", "Symptoms:", "Mechanism:"
    - a title that reads like an encyclopaedia entry: "What is ..."
    - unattributed physiological ranges

  SPECIFIC signals push the score DOWN (less derivable):
    - the organisation's own name
    - named people, named vendors, named assays
    - currency amounts, dates, board resolution numbers
    - local incident references ("Past incident", "Supra incident 2024")
    - policy/mandate verbs ("Supra policy", "mandatory", "NEVER", "MUST")
    - patient identifiers

This runs as a BATCH PRE-COMPUTATION at seed/ingest time and writes a number
to the column. At query time the check is `derivability_score < threshold` -
one indexed numeric compare. Nothing here executes inside the request path,
which is what keeps the Rules Engine honest about being zero-LLM and under
budget.

`validate_against_seed()` compares this scorer's output against the scores
shipped in the seed data. It is a calibration harness, not a test of truth -
the point is to show the heuristic is defensible, and to surface where it
disagrees.
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

ORG_NAMES = ("supra",)

GENERIC_PATTERNS: List[Tuple[str, float, str]] = [
    (r"\b(?:is|are)\s+(?:a|an|the)\s+\w+", 0.22, "definitional phrasing"),
    (r"\balso\s+called\b", 0.18, "names a synonym"),
    (r"\brisk\s+factors\s*:", 0.16, "textbook risk-factor list"),
    (r"\bsymptoms\s*:", 0.16, "textbook symptom list"),
    (r"\bmechanism\s*:", 0.18, "pharmacology textbook framing"),
    (r"\bnormal\s+(?:adult\s+)?\w+\s+(?:signs|ranges|values)\b", 0.24,
     "quotes standard physiological ranges"),
    (r"\bmost\s+common\s+form\b", 0.14, "epidemiological generality"),
    (r"\bstandard\s+(?:adult\s+)?dose\b", 0.20, "standard dosing, not local"),
    (r"\busually\s+in\s+the\b", 0.10, "generalised anatomy"),
    (r"\bwhat\s+is\b", 0.20, "encyclopaedia-style title"),
]

SPECIFIC_PATTERNS: List[Tuple[str, float, str]] = [
    (r"\bsupra\b", 0.30, "names the organisation"),
    (r"\bdr\.?\s+[A-Z]\w+", 0.22, "attributed to a named clinician"),
    (r"\b(?:rs\.?|inr|₹)\s?\d", 0.20, "carries a monetary figure"),
    (r"\b(?:past|previous)\s+incident\b", 0.26, "references a local incident"),
    (r"\bincident\s+20\d\d\b", 0.26, "references a dated local incident"),
    (r"\bpolicy\s*:", 0.22, "states local policy"),
    (r"\bprotocol\b", 0.12, "names a local protocol"),
    (r"\b(?:never|must|mandatory|absolute|strictly|do not)\b", 0.14,
     "mandate language - a rule, not a fact"),
    (r"\bdecision\s+by\b", 0.24, "records who decided"),
    (r"\bboard\s+resolution\b", 0.26, "governance artefact"),
    (r"\b(?:zimmer|smith\s*&\s*nephew|abbott|calpol|dolo|omez|glycomet)\b",
     0.20, "names a specific vendor or brand"),
    (r"\b(?:target|current)\s*:\s*\d", 0.18, "local performance figure"),
    (r"\b\d{1,3}\s*(?:beds|%)\b", 0.10, "local capacity or metric"),
    (r"\bward\b", 0.10, "ward-level operational detail"),
    (r"\b(?:patient|pt)\s+[A-Z]\w+", 0.28, "names an individual patient"),
    (r"\bv[23]\b|\bversion\s+[23]\b", 0.16, "locally versioned document"),
    (r"\b20\d\d\b", 0.08, "carries a specific year"),
]

BASELINE = 0.50  # "could go either way" before evidence


@dataclass
class Explanation:
    node_id: str
    score: float
    generic_hits: List[str] = field(default_factory=list)
    specific_hits: List[str] = field(default_factory=list)


def score_text(title: str, content: str, node_id: str = "") -> Explanation:
    """Return a derivability score in [0,1] with the reasons behind it."""
    blob = f"{title}\n{content}"
    lowered = blob.lower()

    score = BASELINE
    exp = Explanation(node_id=node_id, score=BASELINE)

    for pattern, weight, why in GENERIC_PATTERNS:
        if re.search(pattern, lowered, flags=re.IGNORECASE):
            score += weight
            exp.generic_hits.append(why)

    for pattern, weight, why in SPECIFIC_PATTERNS:
        # Case-sensitive patterns (named people, named patients) are matched
        # against the original text, not the lowered copy.
        target = blob if any(c.isupper() for c in pattern) else lowered
        if re.search(pattern, target, flags=0 if target is blob else re.IGNORECASE):
            score -= weight
            exp.specific_hits.append(why)

    score = max(0.0, min(1.0, score))
    exp.score = round(score, 2)
    return exp


def rescore_all(nodes) -> Dict[str, Explanation]:
    """Batch pass. This is the job that would run on ingest, not at query."""
    return {
        n[0]: score_text(title=n[3], content=n[4], node_id=n[0])
        for n in nodes
    }


def validate_against_seed(nodes, threshold: float = 0.7) -> Dict[str, object]:
    """Compare computed scores with the scores shipped in the seed data.

    The metric that matters is not absolute agreement - it is whether the
    scorer puts the same nodes on the same SIDE of the threshold, because that
    is the only thing check 5 actually consumes.
    """
    computed = rescore_all(nodes)
    agree, disagree = [], []
    for n in nodes:
        nid, seeded = n[0], float(n[8])
        got = computed[nid].score
        same_side = (seeded >= threshold) == (got >= threshold)
        (agree if same_side else disagree).append(
            {"id": nid, "title": n[3], "seeded": seeded, "computed": got}
        )
    total = len(nodes)
    return {
        "threshold": threshold,
        "total": total,
        "agreement": round(len(agree) / total, 3) if total else 0.0,
        "disagreements": disagree,
        "explanations": computed,
    }
