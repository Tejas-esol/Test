"""
Booking pipeline agents — multi-step dependent chain.

Doctor Search → Slot Availability → Appointment Booking

These agents demonstrate Requirement 5 (Multi-step Execution)
and Requirement 7 (Failure Recovery) with automatic retries
and alternate doctor fallback.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from HospitalManagement.agents.base import BaseAgent
from HospitalManagement.core.state import SharedState, Task

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────
# Slot Availability Agent
# ──────────────────────────────────────────────────────────────────

class SlotAvailabilityAgent(BaseAgent):
    """
    Checks available slots for candidate doctors.

    Reads ``state.metadata["candidate_doctors"]`` (populated by
    DoctorSearchAgent) and finds the earliest available slot
    across all candidates.  Implements failure recovery by trying
    multiple doctors if the first has no slots.
    """

    name = "SlotAvailabilityAgent"

    def execute(self, task: Task, state: SharedState) -> Any:
        candidates: List[Dict] = state.metadata.get("candidate_doctors", [])
        if not candidates:
            raise ValueError("No candidate doctors available to check slots")

        # Try each doctor until we find one with available slots
        for doctor in candidates:
            doc_id = doctor["doctor_id"]
            slots = state.db.available_slots(doc_id)

            if slots:
                # Sort chronologically and pick the earliest
                slots.sort()
                chosen_slot = slots[0]

                state.post_message(
                    sender=self.name,
                    receiver="AppointmentBookingAgent",
                    content=(
                        f"Earliest slot: {chosen_slot} with "
                        f"{doctor['name']} ({doc_id})"
                    ),
                    data={
                        "doctor_id": doc_id,
                        "doctor_name": doctor["name"],
                        "slot": chosen_slot,
                        "all_slots": slots,
                    },
                )

                # Store selected doctor+slot for booking agent
                state.metadata["selected_doctor"] = doctor
                state.metadata["selected_slot"] = chosen_slot

                return {
                    "doctor_id": doc_id,
                    "doctor_name": doctor["name"],
                    "slot": chosen_slot,
                    "total_available": len(slots),
                }

            logger.info(
                "No slots for %s (%s), trying next candidate...",
                doctor["name"], doc_id,
            )

        # All doctors exhausted — failure
        raise ValueError("No available slots found for any candidate doctor")


# ──────────────────────────────────────────────────────────────────
# Appointment Booking Agent
# ──────────────────────────────────────────────────────────────────

class AppointmentBookingAgent(BaseAgent):
    """
    Books the appointment using the slot selected by SlotAvailabilityAgent.

    Implements failure recovery: if booking fails (e.g. race condition),
    tries the next available slot with the same or alternate doctor.
    """

    name = "AppointmentBookingAgent"

    def execute(self, task: Task, state: SharedState) -> Any:
        doctor = state.metadata.get("selected_doctor")
        slot = state.metadata.get("selected_slot")

        if not doctor or not slot:
            raise ValueError(
                "No doctor/slot selected — upstream agent may have failed"
            )

        # Attempt booking
        try:
            record = state.db.book_appointment(
                patient_id=state.patient_id,
                doctor_id=doctor["doctor_id"],
                slot=slot,
            )
        except ValueError as exc:
            # Failure recovery: try alternate slots/doctors
            logger.warning("Primary booking failed: %s — attempting recovery", exc)
            record = self._attempt_recovery(state, doctor)
            if record is None:
                state.output["appointment_status"] = (
                    "Failed - No confirmed slot was available to book"
                )
                raise ValueError("All booking attempts exhausted") from exc

        # Success
        state.post_message(
            sender=self.name,
            receiver="ConfirmationAgent",
            content=f"Booked appointment {record['appointment_id']}",
            data={"appointment": record},
        )

        state.metadata["booked_appointment"] = record
        state.output["appointment_status"] = (
            f"Booked — {record['appointment_id']} with "
            f"{doctor['name']} on {record['slot']}"
        )

        return record

    def _attempt_recovery(
        self,
        state: SharedState,
        failed_doctor: Dict,
    ) -> Optional[Dict]:
        """Try alternate slots/doctors as failure recovery."""
        candidates = state.metadata.get("candidate_doctors", [])

        for doctor in candidates:
            doc_id = doctor["doctor_id"]
            slots = state.db.available_slots(doc_id)
            for slot in sorted(slots):
                try:
                    record = state.db.book_appointment(
                        patient_id=state.patient_id,
                        doctor_id=doc_id,
                        slot=slot,
                    )
                    state.post_message(
                        sender=self.name,
                        receiver="*",
                        content=(
                            f"Recovery: booked alternate slot {slot} "
                            f"with {doctor['name']}"
                        ),
                    )
                    state.metadata["selected_doctor"] = doctor
                    state.metadata["selected_slot"] = slot
                    return record
                except ValueError:
                    continue

        return None
