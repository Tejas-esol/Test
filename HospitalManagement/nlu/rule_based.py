"""
Rule-based NLU extractor — zero external dependencies.

Uses keyword matching, synonym tables, and heuristics to parse
patient queries into structured ``NLUResult`` objects.  Designed
to be fast, deterministic, and work offline as the default backend.
"""

from __future__ import annotations

import re
from typing import List, Optional

from HospitalManagement.nlu.base import NLUResult


# ──────────────────────────────────────────────────────────────────
# Keyword tables
# ──────────────────────────────────────────────────────────────────

BOOKING_KEYWORDS = [
    "book", "appointment", "schedule an appointment", "earliest",
    "available", "see a doctor", "doctor", "consult", "visit",
    "reserve", "slot",
]

NOTIFICATION_KEYWORDS = [
    "notify", "notification", "alert", "inform", "let me know",
    "send me", "update me", "message me", "confirm", "tell me",
    "finally",
]

LAB_TEST_NAMES = [
    "ecg", "blood test", "x-ray", "mri", "ct scan", "cbc",
    "urine test", "ultrasound", "eeg", "lipid panel",
    "thyroid panel", "liver function", "kidney function",
]

SYMPTOM_KEYWORDS = [
    "chest pain", "headache", "fever", "cough", "breathlessness",
    "dizziness", "nausea", "fatigue", "pain", "swelling",
    "fracture", "broken", "sprain", "rash", "itching",
    "joint pain", "back pain", "abdominal pain",
]

URGENT_KEYWORDS = [
    "urgent", "emergency", "severe", "immediately", "asap",
    "critical", "life-threatening",
]

# Maps canonical specialization → synonyms / related terms.
# The canonical name itself is also included for direct matching.
SPECIALIZATION_SYNONYMS = {
    "cardiology": [
        "cardiology", "cardiologist", "heart", "cardiac",
        "chest pain", "ecg", "electrocardiogram",
    ],
    "orthopedics": [
        "orthopedics", "orthopedic", "orthopaedic", "bone",
        "fracture", "joint", "spine", "knee", "hip",
    ],
    "dermatology": [
        "dermatology", "dermatologist", "skin", "rash",
    ],
    "neurology": [
        "neurology", "neurologist", "brain", "nerve", "seizure", "eeg",
    ],
    "gastroenterology": [
        "gastroenterology", "gastroenterologist", "stomach",
        "digestive", "liver", "gut",
    ],
    "pulmonology": [
        "pulmonology", "pulmonologist", "lung", "respiratory",
        "breathing", "asthma",
    ],
    "oncology": [
        "oncology", "oncologist", "cancer", "tumor", "tumour",
    ],
    "pediatrics": [
        "pediatrics", "pediatrician", "child", "infant", "baby",
    ],
    "ophthalmology": [
        "ophthalmology", "ophthalmologist", "eye", "vision",
    ],
    "ent": [
        "ent", "otolaryngology", "ear", "nose", "throat",
    ],
    "general medicine": [
        "general medicine", "general practitioner", "gp",
        "family medicine", "internal medicine", "physician",
    ],
}


# ──────────────────────────────────────────────────────────────────
# Rule-based extractor
# ──────────────────────────────────────────────────────────────────

class RuleBasedNLU:
    """
    Deterministic, dependency-free, data-driven NLU.

    Implements ``NLUExtractor`` protocol.
    """

    def extract(
        self,
        query: str,
        available_specializations: List[str],
    ) -> NLUResult:
        q = query.lower()
        result = NLUResult()

        # ── 1. Symptoms ─────────────────────────────────────────
        result.symptoms = [s for s in SYMPTOM_KEYWORDS if s in q]

        # ── 2. Urgency ──────────────────────────────────────────
        if any(kw in q for kw in URGENT_KEYWORDS):
            result.urgency = "urgent"

        # ── 3. Specialization detection ─────────────────────────
        result.specialization = self._detect_specialization(
            q, available_specializations
        )

        # ── 4. Booking intent ───────────────────────────────────
        if any(kw in q for kw in BOOKING_KEYWORDS):
            result.wants_booking = True
            result.raw_intents.append("book_appointment")

        # ── 5. Lab test mentions ────────────────────────────────
        mentioned_tests = [t for t in LAB_TEST_NAMES if t in q]

        # Detect "check whether I have <test>" pattern
        check_pattern = re.compile(
            r"check\s+(?:whether|if)\s+.*?\b("
            + "|".join(re.escape(t) for t in LAB_TEST_NAMES)
            + r")\b",
            re.IGNORECASE,
        )
        for m in check_pattern.finditer(query):
            test = m.group(1).lower()
            if test not in result.lab_tests_to_check:
                result.lab_tests_to_check.append(test)
                result.raw_intents.append(f"check_lab_{test}")

        # Detect "if no <test>, schedule" pattern
        schedule_pattern = re.compile(
            r"(?:if\s+(?:no|not|no\s+\w+)\s+.*?|if\s+\w+\s+(?:does\s*n[o']t|doesn['\u2019]t)\s+exist)"
            r".*?(?:schedule|book|order)\s+.*?\b("
            + "|".join(re.escape(t) for t in LAB_TEST_NAMES)
            + r")\b",
            re.IGNORECASE,
        )
        for m in schedule_pattern.finditer(query):
            test = m.group(1).lower()
            if test not in result.schedule_if_missing:
                result.schedule_if_missing.append(test)
                result.raw_intents.append(f"schedule_lab_{test}_if_missing")

        # Fallback: if a test is mentioned + "schedule" nearby but
        # not captured by the regex, still detect it.
        if not result.schedule_if_missing and mentioned_tests:
            if re.search(r"\bschedule\b", q):
                for test in mentioned_tests:
                    if test not in result.lab_tests_to_check:
                        result.lab_tests_to_check.append(test)
                    if test not in result.schedule_if_missing:
                        result.schedule_if_missing.append(test)
                        result.raw_intents.append(
                            f"schedule_lab_{test}_if_missing"
                        )

        # If tests mentioned but only "check" intent detected, add
        # them to check list (idempotent).
        for test in mentioned_tests:
            if test not in result.lab_tests_to_check:
                result.lab_tests_to_check.append(test)

        # ── 6. Notification intent ──────────────────────────────
        if any(kw in q for kw in NOTIFICATION_KEYWORDS):
            result.wants_notification = True
            result.raw_intents.append("send_notification")

        return result

    # ── specialization resolution ────────────────────────────────

    @staticmethod
    def _detect_specialization(
        q: str,
        available_specializations: List[str],
    ) -> Optional[str]:
        """
        Detect a medical specialization from the query.

        Strategy:
        1. Direct mention of an available specialization name.
        2. Synonym table lookup → map to canonical, then match
           to available specializations.
        3. If a synonym matches a canonical *not* in the available
           list, return it anyway (the downstream agent will see
           "no doctors for X" and can fail gracefully).
        """
        avail_lower = {s.lower(): s for s in available_specializations}

        # Pass 1: direct mention of available specializations
        for spec_lower, spec_original in avail_lower.items():
            if spec_lower in q:
                return spec_original

        # Pass 2: synonym table
        best_canonical: Optional[str] = None
        for canonical, synonyms in SPECIALIZATION_SYNONYMS.items():
            for syn in synonyms:
                if syn in q:
                    # Found a synonym match
                    if canonical in avail_lower:
                        # Canonical is available — return it immediately
                        return avail_lower[canonical]
                    else:
                        # Canonical is NOT available — remember it so we
                        # can surface it for a graceful failure message
                        if best_canonical is None:
                            best_canonical = canonical
                    break  # one synonym match per canonical is enough

        # Return unmatched canonical (title-cased) so downstream can
        # report "no doctors for Dermatology" rather than silently
        # defaulting to an unrelated specialty.
        if best_canonical:
            return best_canonical.title()

        return None
