"""
NLU (Natural Language Understanding) — base types.

Provides the ``NLUResult`` data class and ``NLUExtractor`` protocol
that all NLU backends must implement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Protocol


@dataclass
class NLUResult:
    """
    Structured extraction from a patient's free-text query.

    Fields
    ------
    wants_booking : bool
        True if the patient wants an appointment booked.
    specialization : str | None
        Detected medical specialization (e.g. ``"Cardiology"``).
    lab_tests_to_check : list[str]
        Lab test names the patient asked about (e.g. ``["ECG"]``).
    schedule_if_missing : list[str]
        Lab tests that should be scheduled if they don't already exist.
    wants_notification : bool
        True if the patient asked to be notified.
    raw_intents : list[str]
        Human-readable list of detected intents (for debugging).
    symptoms : list[str]
        Symptoms mentioned by the patient.
    urgency : str
        Estimated urgency: ``"normal"`` or ``"urgent"``.
    """

    wants_booking: bool = False
    specialization: Optional[str] = None
    lab_tests_to_check: List[str] = field(default_factory=list)
    schedule_if_missing: List[str] = field(default_factory=list)
    wants_notification: bool = False
    raw_intents: List[str] = field(default_factory=list)
    symptoms: List[str] = field(default_factory=list)
    urgency: str = "normal"


class NLUExtractor(Protocol):
    """Protocol that NLU backends must satisfy."""

    def extract(self, query: str, available_specializations: List[str]) -> NLUResult:
        """Parse ``query`` and return structured intents."""
        ...
