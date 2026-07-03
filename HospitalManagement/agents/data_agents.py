"""
Data-retrieval agents — run independently and in parallel.

- ``PatientHistoryAgent``: fetches patient record + existing data.
- ``DoctorSearchAgent``: finds doctors by specialization.
- ``LabReportCheckAgent``: checks for existing lab reports and
  optionally schedules missing ones.
"""

from __future__ import annotations

import logging
from typing import Any

from HospitalManagement.agents.base import BaseAgent
from HospitalManagement.core.state import SharedState, Task

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────
# Patient History Agent
# ──────────────────────────────────────────────────────────────────

class PatientHistoryAgent(BaseAgent):
    """Retrieves the patient's record, appointments, and lab reports."""

    name = "PatientHistoryAgent"

    def execute(self, task: Task, state: SharedState) -> Any:
        pid = task.params.get("patient_id", state.patient_id)
        patient = state.db.get_patient(pid)

        if patient is None:
            raise ValueError(f"Patient '{pid}' not found in the database")

        labs = state.db.get_lab_reports(pid)

        state.post_message(
            sender=self.name,
            receiver="*",
            content=f"Retrieved history for {patient['name']} (ID: {pid})",
            data={
                "patient": patient,
                "existing_labs": [r["test_name"] for r in labs],
            },
        )

        state.metadata["patient"] = patient
        state.metadata["existing_labs"] = [r["test_name"] for r in labs]

        return {
            "patient_name": patient["name"],
            "age": patient["age"],
            "existing_appointments": patient.get("appointments", []),
            "existing_lab_reports": [r["test_name"] for r in labs],
        }


# ──────────────────────────────────────────────────────────────────
# Doctor Search Agent
# ──────────────────────────────────────────────────────────────────

class DoctorSearchAgent(BaseAgent):
    """Searches for doctors by specialization."""

    name = "DoctorSearchAgent"

    def execute(self, task: Task, state: SharedState) -> Any:
        spec = task.params.get("specialization")
        doctors = state.db.find_doctors(spec)

        if not doctors:
            raise ValueError(
                f"No doctors found for specialization '{spec}'"
            )

        state.post_message(
            sender=self.name,
            receiver="SlotAvailabilityAgent",
            content=f"Found {len(doctors)} doctor(s) for '{spec}'",
            data={"doctors": doctors},
        )

        # Store in metadata for downstream agents
        state.metadata["candidate_doctors"] = doctors

        return {
            "specialization": spec,
            "doctors": [
                {"id": d["doctor_id"], "name": d["name"]}
                for d in doctors
            ],
        }


# ──────────────────────────────────────────────────────────────────
# Lab Report Check Agent
# ──────────────────────────────────────────────────────────────────

class LabReportCheckAgent(BaseAgent):
    """
    Checks if a patient has an existing lab report.

    If ``schedule_if_missing`` is True and the report doesn't exist,
    schedules the lab test automatically (dynamic decision making).
    """

    name = "LabReportCheckAgent"

    def execute(self, task: Task, state: SharedState) -> Any:
        test_name: str = task.params["test_name"]
        schedule_if_missing: bool = task.params.get("schedule_if_missing", False)

        exists = state.db.has_lab_report(state.patient_id, test_name)

        if exists:
            state.post_message(
                sender=self.name,
                receiver="*",
                content=f"Lab report '{test_name}' already exists for patient {state.patient_id}",
            )
            status = f"{test_name} report already exists"
            state.output["lab_test_status"] = status
            return {"test": test_name, "exists": True, "action": "none"}

        # Report does not exist
        if schedule_if_missing:
            # Dynamic decision: schedule the test
            try:
                record = state.db.schedule_lab_test(state.patient_id, test_name)
                state.post_message(
                    sender=self.name,
                    receiver="NotificationAgent",
                    content=f"Scheduled lab test '{test_name}' for patient {state.patient_id}",
                    data={"lab_record": record},
                )
                status = f"{test_name} test scheduled (ID: {record['lab_id']})"
                state.output["lab_test_status"] = status
                return {
                    "test": test_name,
                    "exists": False,
                    "action": "scheduled",
                    "lab_id": record["lab_id"],
                }
            except Exception as exc:
                logger.error("Failed to schedule %s: %s", test_name, exc)
                state.output["lab_test_status"] = f"Failed to schedule {test_name}: {exc}"
                raise
        else:
            status = f"{test_name} report not found (not scheduled per request)"
            state.output["lab_test_status"] = status
            return {"test": test_name, "exists": False, "action": "none"}
