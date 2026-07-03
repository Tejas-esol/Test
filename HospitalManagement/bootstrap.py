"""
Bootstrap — wires all agents and NLU backend into a ready-to-use
Orchestrator instance.

Usage::

    from HospitalManagement.bootstrap import create_orchestrator, run_query
    result = run_query("P002", "Book a cardiologist appointment...")
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, Optional

from HospitalManagement.agents.base import BaseAgent
from HospitalManagement.agents.booking_agents import (
    AppointmentBookingAgent,
    SlotAvailabilityAgent,
)
from HospitalManagement.agents.confirmation_agent import ConfirmationAgent
from HospitalManagement.agents.data_agents import (
    DoctorSearchAgent,
    LabReportCheckAgent,
    PatientHistoryAgent,
)
from HospitalManagement.agents.intent_agent import IntentAgent
from HospitalManagement.agents.notification_agent import NotificationAgent
from HospitalManagement.agents.validation_agent import ValidationAgent
from HospitalManagement.core.hospital_db import HospitalDB
from HospitalManagement.core.logger import setup_logging
from HospitalManagement.core.orchestrator import Orchestrator
from HospitalManagement.core.state import SharedState
from HospitalManagement.nlu.rule_based import RuleBasedNLU

logger = logging.getLogger(__name__)


def _build_nlu():
    """
    Select NLU backend.

    Uses Gemini if GEMINI_API_KEY is set, otherwise falls back
    to the deterministic rule-based extractor.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if api_key:
        try:
            from HospitalManagement.nlu.gemini_nlu import GeminiNLU
            logger.info("Using Gemini NLU backend")
            return GeminiNLU(api_key=api_key)
        except Exception as exc:
            logger.warning("Gemini NLU init failed (%s), using rule-based", exc)
    return RuleBasedNLU()


def create_orchestrator(max_retries: int = 2) -> Orchestrator:
    """Wire all agents and return a configured Orchestrator."""
    nlu = _build_nlu()

    agents: Dict[str, BaseAgent] = {
        "IntentAgent": IntentAgent(nlu=nlu),
        "PatientHistoryAgent": PatientHistoryAgent(),
        "DoctorSearchAgent": DoctorSearchAgent(),
        "SlotAvailabilityAgent": SlotAvailabilityAgent(),
        "AppointmentBookingAgent": AppointmentBookingAgent(),
        "ConfirmationAgent": ConfirmationAgent(),
        "LabReportCheckAgent": LabReportCheckAgent(),
        "NotificationAgent": NotificationAgent(),
        "ValidationAgent": ValidationAgent(),
    }

    return Orchestrator(agents=agents, max_retries=max_retries)


def run_query(
    patient_id: str,
    user_query: str,
    db: Optional[HospitalDB] = None,
    max_retries: int = 2,
) -> Dict[str, Any]:
    """
    Convenience function: create orchestrator, build state, run, return result.

    Parameters
    ----------
    patient_id : str
        The patient making the request.
    user_query : str
        Free-text request from the patient.
    db : HospitalDB, optional
        Database instance.  If None, an ephemeral in-memory DB is used
        (safe for testing).  Pass a persistent DB for production use.
    max_retries : int
        Maximum validation retry attempts.
    """
    # Ensure logging is set up
    setup_logging()

    orchestrator = create_orchestrator(max_retries=max_retries)
    state = SharedState(
        patient_id=patient_id,
        user_query=user_query,
        db=db if db is not None else HospitalDB.from_memory(),
    )

    # Handle event loop
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("closed")
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop.run_until_complete(orchestrator.run_async(state))
