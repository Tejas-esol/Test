"""
Confirmation Agent — final step of the booking chain.

Produces a human-readable confirmation of the booked appointment
and posts it to the message bus for downstream agents.
"""

from __future__ import annotations

from typing import Any

from HospitalManagement.agents.base import BaseAgent
from HospitalManagement.core.state import SharedState, Task


class ConfirmationAgent(BaseAgent):
    """Generates a structured booking confirmation."""

    name = "ConfirmationAgent"

    def execute(self, task: Task, state: SharedState) -> Any:
        appt = state.metadata.get("booked_appointment")
        doctor = state.metadata.get("selected_doctor", {})

        if not appt:
            raise ValueError("No booking record found to confirm")

        confirmation = {
            "appointment_id": appt["appointment_id"],
            "patient_id": appt["patient_id"],
            "doctor_name": doctor.get("name", "Unknown"),
            "specialization": doctor.get("specialization", "Unknown"),
            "slot": appt["slot"],
            "status": "Confirmed",
        }

        state.post_message(
            sender=self.name,
            receiver="*",
            content=(
                f"Appointment {appt['appointment_id']} confirmed: "
                f"{doctor.get('name', '?')} at {appt['slot']}"
            ),
            data={"confirmation": confirmation},
        )

        state.metadata["booking_confirmation"] = confirmation
        return confirmation
