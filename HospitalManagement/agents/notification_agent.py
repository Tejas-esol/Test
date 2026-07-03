"""
Notification Agent — with multi-channel failure recovery.

Attempts notification via primary channel, falls back to
alternate channels if the primary fails (Requirement 7).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from HospitalManagement.agents.base import BaseAgent
from HospitalManagement.core.state import SharedState, Task, TaskStatus

logger = logging.getLogger(__name__)

# Preferred notification channel order
_CHANNELS = ["sms", "email", "push", "in_app"]


class NotificationAgent(BaseAgent):
    """
    Sends a summary notification to the patient.

    Assembles a human-readable summary from all completed tasks
    and attempts delivery through multiple channels (failure recovery).
    """

    name = "NotificationAgent"

    def execute(self, task: Task, state: SharedState) -> Any:
        summary_lines = self._build_summary(state)
        message = "\n".join(summary_lines)

        # Try channels in priority order
        last_error = None
        for channel in _CHANNELS:
            try:
                record = state.db.send_notification(
                    patient_id=state.patient_id,
                    channel=channel,
                    message=message,
                )
                state.post_message(
                    sender=self.name,
                    receiver="*",
                    content=f"Notification sent via {channel}",
                    data={"notification": record},
                )
                state.output["notification_status"] = f"Sent via {channel}"
                return {
                    "channel": channel,
                    "notification_id": record["notification_id"],
                    "message": message,
                }
            except Exception as exc:
                logger.warning("Notification via %s failed: %s", channel, exc)
                last_error = exc
                continue

        # All channels failed
        state.output["notification_status"] = "Failed - all channels exhausted"
        raise RuntimeError(
            f"All notification channels failed. Last error: {last_error}"
        )

    def _build_summary(self, state: SharedState) -> List[str]:
        """Build a patient-facing summary from completed tasks."""
        lines = [
            f"📋 Summary for Patient {state.patient_id}",
            "=" * 40,
        ]

        # Appointment info
        appt_status = state.output.get("appointment_status", "N/A")
        lines.append(f"🏥 Appointment: {appt_status}")

        # Lab test info
        lab_status = state.output.get("lab_test_status", "N/A")
        lines.append(f"🔬 Lab Test: {lab_status}")

        # Booking confirmation details
        confirmation = state.metadata.get("booking_confirmation")
        if confirmation:
            lines.extend([
                "",
                "📅 Appointment Details:",
                f"   Doctor: {confirmation.get('doctor_name', 'N/A')}",
                f"   Specialization: {confirmation.get('specialization', 'N/A')}",
                f"   Time: {confirmation.get('slot', 'N/A')}",
                f"   ID: {confirmation.get('appointment_id', 'N/A')}",
            ])

        # Symptoms recorded
        nlu = state.metadata.get("nlu")
        if nlu and nlu.symptoms:
            lines.append(f"\n⚠️  Symptoms noted: {', '.join(nlu.symptoms)}")

        return lines
