"""
Gemini-backed NLU extractor — uses the Gemini API for
intent extraction with structured JSON output.

Falls back to rule-based NLU if the API key is not set or
if the API call fails.

Set ``GEMINI_API_KEY`` environment variable to enable.
"""

from __future__ import annotations

import json
import logging
import os
from typing import List, Optional

from dotenv import load_dotenv
load_dotenv()

from HospitalManagement.nlu.base import NLUResult

logger = logging.getLogger(__name__)


# Prompt template for Gemini
_SYSTEM_PROMPT = """\
You are a medical NLU system. Given a patient query, extract structured
intents as JSON.  Return ONLY valid JSON (no markdown fences).

Available medical specializations in the hospital: {specializations}

Return this exact schema:
{{
  "wants_booking": true/false,
  "specialization": "Cardiology" | null,
  "lab_tests_to_check": ["ECG", ...],
  "schedule_if_missing": ["ECG", ...],
  "wants_notification": true/false,
  "symptoms": ["chest pain", ...],
  "urgency": "normal" | "urgent",
  "raw_intents": ["book_appointment", "check_lab_ECG", ...]
}}

Rules:
- specialization must be one of the available specializations listed
  above, or null if unclear.  If a related synonym is mentioned
  (e.g. "heart" → Cardiology), map it to the correct specialization.
  If the specialization is not available, set it to the closest
  canonical name (e.g. "Dermatology") even if not in the list.
- lab_tests_to_check: tests the patient wants to check/verify.
- schedule_if_missing: tests to schedule ONLY IF they don't exist.
- Be conservative: only set true/non-null when clearly expressed.
"""


class GeminiNLU:
    """
    LLM-backed NLU using Google's Gemini API.

    Implements ``NLUExtractor`` protocol.  Lazily imports
    ``google.generativeai`` to avoid hard dependency.
    """

    def __init__(self, api_key: Optional[str] = None, model: str = "gemini-2.0-flash"):
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY")
        self._model_name = model
        self._client = None

    def _get_client(self):
        """Lazily initialize the Gemini client."""
        if self._client is None:
            try:
                from google import genai
                self._client = genai.Client(api_key=self._api_key)
            except ImportError:
                raise ImportError(
                    "google-genai package required for GeminiNLU. "
                    "Install with: pip install google-genai"
                )
        return self._client

    def extract(
        self,
        query: str,
        available_specializations: List[str],
    ) -> NLUResult:
        """Parse query via Gemini and return NLUResult."""
        if not self._api_key:
            raise RuntimeError("GEMINI_API_KEY not set")

        client = self._get_client()
        prompt = _SYSTEM_PROMPT.format(
            specializations=", ".join(available_specializations) or "None"
        )

        try:
            response = client.models.generate_content(
                model=self._model_name,
                contents=[
                    {"role": "user", "parts": [{"text": f"{prompt}\n\nPatient query: {query}"}]}
                ],
            )
            raw = response.text.strip()

            # Strip markdown fences if present
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
                if raw.endswith("```"):
                    raw = raw[:-3]
                raw = raw.strip()

            data = json.loads(raw)
            return NLUResult(
                wants_booking=data.get("wants_booking", False),
                specialization=data.get("specialization"),
                lab_tests_to_check=[
                    t.lower() for t in data.get("lab_tests_to_check", [])
                ],
                schedule_if_missing=[
                    t.lower() for t in data.get("schedule_if_missing", [])
                ],
                wants_notification=data.get("wants_notification", False),
                raw_intents=data.get("raw_intents", []),
                symptoms=data.get("symptoms", []),
                urgency=data.get("urgency", "normal"),
            )
        except Exception as exc:
            logger.warning("Gemini NLU failed (%s), falling back to rule-based", exc)
            from HospitalManagement.nlu.rule_based import RuleBasedNLU
            return RuleBasedNLU().extract(query, available_specializations)
