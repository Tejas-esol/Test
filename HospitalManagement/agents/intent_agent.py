"""
Intent Understanding Agent — Requirement 1: Task Understanding.

Runs NLU on the patient query and builds the dynamic task DAG
based on extracted intents.  This is the *only* place where the
task graph is constructed, making the workflow fully data-driven.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, List

from HospitalManagement.agents.base import BaseAgent
from HospitalManagement.core.state import SharedState, Task
from HospitalManagement.nlu.base import NLUExtractor, NLUResult

logger = logging.getLogger(__name__)


class IntentAgent(BaseAgent):
    """
    Analyses the user query and builds the task DAG dynamically.

    After execution, ``state.tasks`` contains the full execution
    plan with dependencies, and ``state.metadata["nlu"]`` holds
    the raw ``NLUResult``.
    """

    name = "IntentAgent"

    def __init__(self, nlu: NLUExtractor):
        self._nlu = nlu

    def execute(self, task: Task, state: SharedState) -> Any:
        # ── 1. Run NLU ──────────────────────────────────────────
        available_specs = state.db.all_specializations()
        nlu_result: NLUResult = self._nlu.extract(state.user_query, available_specs)
        state.metadata["nlu"] = nlu_result
        state.metadata["specialization"] = nlu_result.specialization

        state.post_message(
            sender=self.name,
            receiver="*",
            content=f"Parsed intents: {nlu_result.raw_intents}",
            data={
                "specialization": nlu_result.specialization,
                "wants_booking": nlu_result.wants_booking,
                "lab_tests_to_check": nlu_result.lab_tests_to_check,
                "schedule_if_missing": nlu_result.schedule_if_missing,
                "wants_notification": nlu_result.wants_notification,
                "symptoms": nlu_result.symptoms,
                "urgency": nlu_result.urgency,
            },
        )

        # ── 2. Build dynamic task DAG ────────────────────────────
        # Independent data-retrieval tasks (can run in parallel)
        fetch_patient = state.add_task(Task(
            kind="FETCH_PATIENT",
            agent_name="PatientHistoryAgent",
            params={"patient_id": state.patient_id},
        ))

        created_tasks = [fetch_patient]

        # Booking pipeline (multi-step dependent chain)
        if nlu_result.wants_booking:
            search = state.add_task(Task(
                kind="SEARCH_DOCTORS",
                agent_name="DoctorSearchAgent",
                params={"specialization": nlu_result.specialization},
            ))
            slots = state.add_task(Task(
                kind="CHECK_SLOTS",
                agent_name="SlotAvailabilityAgent",
                depends_on_success={search.id},
            ))
            book = state.add_task(Task(
                kind="BOOK_APPOINTMENT",
                agent_name="AppointmentBookingAgent",
                depends_on_success={slots.id},
            ))
            confirm = state.add_task(Task(
                kind="CONFIRM_BOOKING",
                agent_name="ConfirmationAgent",
                depends_on_success={book.id},
            ))
            created_tasks.extend([search, slots, book, confirm])

        # Lab report checks (parallel with booking pipeline)
        lab_deps: List[str] = []
        for test in nlu_result.lab_tests_to_check:
            check_lab = state.add_task(Task(
                kind=f"CHECK_LAB_{test.upper().replace(' ', '_')}",
                agent_name="LabReportCheckAgent",
                params={
                    "test_name": test,
                    "schedule_if_missing": test in nlu_result.schedule_if_missing,
                },
            ))
            created_tasks.append(check_lab)
            lab_deps.append(check_lab.id)

        # Notification (depends on all other tasks completing)
        if nlu_result.wants_notification:
            all_deps = set()
            for t in created_tasks:
                if t.kind != "FETCH_PATIENT":  # patient fetch is informational
                    all_deps.add(t.id)
            notify = state.add_task(Task(
                kind="SEND_NOTIFICATION",
                agent_name="NotificationAgent",
                depends_on_success=all_deps,
            ))
            created_tasks.append(notify)

        # Validation (runs last — depends on everything else)
        all_ids = {t.id for t in created_tasks}
        state.add_task(Task(
            kind="VALIDATE",
            agent_name="ValidationAgent",
            depends_on_success=all_ids,
        ))

        task_summary = [t.kind for t in created_tasks]
        logger.info("IntentAgent built task DAG: %s", task_summary)

        return {
            "intents": nlu_result.raw_intents,
            "task_count": len(created_tasks) + 1,  # +1 for validation
            "task_kinds": task_summary,
        }
