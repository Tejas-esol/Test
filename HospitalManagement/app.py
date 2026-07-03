"""
Gradio Web UI for the Agentic Hospital Management System.

Provides an interactive interface where users can:
- Select a patient or enter a custom patient ID
- Type their medical request in natural language
- See the structured JSON output
- View the task execution trace
- View the inter-agent communication log

Launch::

    python -m HospitalManagement.app
    # or
    gradio HospitalManagement/app.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys

# Ensure parent dir is on path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from HospitalManagement.bootstrap import create_orchestrator
from HospitalManagement.core.hospital_db import HospitalDB
from HospitalManagement.core.state import SharedState

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)-30s %(levelname)-5s %(message)s",
)
logger = logging.getLogger(__name__)


async def process_request(
    patient_id: str,
    user_query: str,
) -> tuple:
    """Process a patient request and return formatted results."""
    if not patient_id.strip():
        return (
            json.dumps({"error": "Please select or enter a patient ID"}, indent=2),
            "No patient ID provided",
            "No messages",
        )
    if not user_query.strip():
        return (
            json.dumps({"error": "Please enter a medical request"}, indent=2),
            "No query provided",
            "No messages",
        )

    try:
        orchestrator = create_orchestrator(max_retries=2)
        state = SharedState(
            patient_id=patient_id.strip(),
            user_query=user_query.strip(),
            db=HospitalDB.from_seed(),
        )

        result = await orchestrator.run_async(state)

        # Format core output
        core_output = {
            "appointment_status": result.get("appointment_status", "N/A"),
            "lab_test_status": result.get("lab_test_status", "N/A"),
            "notification_status": result.get("notification_status", "N/A"),
            "summary": result.get("summary", "No summary"),
        }
        output_json = json.dumps(core_output, indent=2)

        # Format task trace
        trace_lines = []
        for task in result.get("task_trace", []):
            status_map = {
                "done": "[DONE]",
                "failed": "[FAIL]",
                "skipped": "[SKIP]",
                "pending": "[PEND]",
                "running": "[RUN ]",
            }
            status = status_map.get(task["status"], "[????]")
            duration = f" ({task['duration_ms']}ms)" if task.get("duration_ms") else ""
            line = f"{status} {task['kind']:<30} -> {task['agent']}{duration}"
            if task.get("error"):
                line += f"\n       Error: {task['error']}"
            trace_lines.append(line)
        task_trace = "\n".join(trace_lines) if trace_lines else "No tasks executed"

        # Format message trace
        msg_lines = []
        for msg in result.get("message_trace", []):
            msg_lines.append(
                f"[{msg['sender']}] -> [{msg['receiver']}]: {msg['content']}"
            )
        msg_trace = "\n".join(msg_lines) if msg_lines else "No messages"

        # Add timing info
        task_trace += f"\n\nTotal time: {result.get('elapsed_ms', '?')}ms"
        task_trace += f"\nRetries: {result.get('retry_count', 0)}"

        return output_json, task_trace, msg_trace

    except Exception as exc:
        logger.exception("Error processing request")
        return (
            json.dumps({"error": str(exc)}, indent=2),
            f"Error: {exc}",
            "Processing failed",
        )


def build_app():
    """Build and return the Gradio Blocks app."""
    try:
        import gradio as gr
    except ImportError:
        print("Gradio not installed. Install with: pip install gradio")
        print("Running CLI demo instead...")
        from HospitalManagement.run_demo import main
        sys.exit(main())

    # Example queries
    examples = [
        [
            "P002",
            "I have chest pain. Book the earliest appointment with a cardiologist. "
            "Check whether I already have an ECG report. If not, schedule an ECG test. "
            "Finally notify me with all the details.",
        ],
        [
            "P001",
            "Check whether I already have an ECG report. If not, schedule an ECG test.",
        ],
        [
            "P002",
            "Book an orthopedic appointment for my knee pain.",
        ],
        [
            "P001",
            "Just notify me about my medical records.",
        ],
        [
            "P002",
            "Book a Dermatology doctor appointment.",
        ],
    ]

    custom_css = """
    .gradio-container {
        max-width: 1100px !important;
        margin: auto !important;
    }
    .output-json {
        font-family: 'Fira Code', 'Consolas', monospace !important;
        font-size: 13px !important;
    }
    """

    with gr.Blocks(
        title="Agentic Hospital Management System",
    ) as app:
        gr.Markdown(
            """
            # 🏥 Agentic AI Hospital Management System
            **Multi-agent collaboration for complex patient workflows**

            This system uses multiple specialized AI agents that communicate,
            delegate tasks, make dynamic decisions, and validate results.
            """
        )

        with gr.Row():
            with gr.Column(scale=1):
                patient_input = gr.Textbox(
                    label="Patient ID",
                    placeholder="e.g., P001, P002",
                    value="P002",
                    lines=1,
                )
            with gr.Column(scale=3):
                query_input = gr.Textbox(
                    label="Patient Request (natural language)",
                    placeholder="Describe your medical needs...",
                    lines=3,
                )

        submit_btn = gr.Button(
            "Process Request",
            variant="primary",
            size="lg",
        )

        with gr.Tabs():
            with gr.TabItem("Output"):
                output_json = gr.Code(
                    label="Structured Output (JSON)",
                    language="json",
                    lines=12,
                )
            with gr.TabItem("Task Trace"):
                task_trace = gr.Textbox(
                    label="Task Execution Trace",
                    lines=15,
                    max_lines=30,
                    interactive=False,
                )
            with gr.TabItem("Agent Messages"):
                msg_trace = gr.Textbox(
                    label="Inter-Agent Communication Log",
                    lines=15,
                    max_lines=30,
                    interactive=False,
                )

        gr.Examples(
            examples=examples,
            inputs=[patient_input, query_input],
            label="Example Scenarios",
        )

        gr.Markdown(
            """
            ---
            **Available Patients:** P001 (John Doe, 45, has ECG) · P002 (Alice Smith, 32, no records)

            **Available Doctors:** Dr. Brown (Cardiology) · Dr. Green (Orthopedics)

            **Agents:** IntentAgent · PatientHistoryAgent · DoctorSearchAgent ·
            SlotAvailabilityAgent · AppointmentBookingAgent · ConfirmationAgent ·
            LabReportCheckAgent · NotificationAgent · ValidationAgent
            """
        )

        # Wire up the handler
        submit_btn.click(
            fn=process_request,
            inputs=[patient_input, query_input],
            outputs=[output_json, task_trace, msg_trace],
        )
        query_input.submit(
            fn=process_request,
            inputs=[patient_input, query_input],
            outputs=[output_json, task_trace, msg_trace],
        )

    return app


# Build the app
app = build_app()

if __name__ == "__main__":
    app.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        theme=gr.themes.Soft(
            primary_hue="blue",
            secondary_hue="slate",
        ),
        css=custom_css,
    )
