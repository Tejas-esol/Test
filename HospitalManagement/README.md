# 🏥 Agentic AI Hospital Management System

A multi-agent AI system that handles complex patient requests through collaboration between specialized AI agents. Unlike a monolithic chatbot, this system decomposes patient requests into tasks, distributes them across agents, executes them in parallel where possible, validates results, and recovers from failures.

## Architecture

```
Patient Request → IntentAgent (NLU) → Dynamic Task DAG
                                          ↓
                  ┌─────────────────────────────────────┐
                  │  Parallel Execution (independent)    │
                  │                                     │
                  │  PatientHistoryAgent ──────┐        │
                  │  DoctorSearchAgent ───┐    │        │
                  │  LabReportCheckAgent  │    │        │
                  └───────────────────────┼────┼────────┘
                                          ↓    ↓
                  ┌─────────────────────────────────────┐
                  │  Sequential Chain (dependent)        │
                  │                                     │
                  │  SlotAvailabilityAgent               │
                  │         ↓                           │
                  │  AppointmentBookingAgent             │
                  │         ↓                           │
                  │  ConfirmationAgent                  │
                  └─────────────────────────────────────┘
                                          ↓
                  NotificationAgent (waits for all above)
                                          ↓
                  ValidationAgent (self-correction loop)
                                          ↓
                              Final JSON Response
```

## Requirements Satisfied

| # | Requirement | Implementation |
|---|-------------|----------------|
| 1 | **Task Understanding** | `IntentAgent` runs NLU (rule-based or Gemini) to extract structured intents |
| 2 | **Task Delegation** | `Orchestrator` distributes tasks to 9 specialized agents via shared state + message bus |
| 3 | **Dynamic Decision Making** | Task DAG is built dynamically based on NLU results; agents decide actions based on intermediate results |
| 4 | **Parallel Collaboration** | Independent tasks (patient fetch, doctor search, lab check) run simultaneously via `ThreadPoolExecutor` |
| 5 | **Multi-step Execution** | Booking chain: Search → Slots → Book → Confirm, coordinated via dependency DAG |
| 6 | **Validation & Self-Correction** | `ValidationAgent` cross-checks all outputs against DB state; triggers retry on inconsistency |
| 7 | **Failure Recovery** | Booking tries alternate doctors/slots; notification falls back across channels (SMS → email → push → in-app) |

## Agents

| Agent | Responsibility |
|-------|---------------|
| `IntentAgent` | NLU parsing, dynamic task DAG construction |
| `PatientHistoryAgent` | Patient record retrieval |
| `DoctorSearchAgent` | Doctor search by specialization |
| `SlotAvailabilityAgent` | Earliest slot selection across candidates |
| `AppointmentBookingAgent` | Appointment booking with failure recovery |
| `ConfirmationAgent` | Booking confirmation generation |
| `LabReportCheckAgent` | Lab report check + conditional scheduling |
| `NotificationAgent` | Multi-channel notification with fallback |
| `ValidationAgent` | Output validation and self-correction |

## Quick Start

### Prerequisites
- Python 3.10+
- (Optional) Gradio for web UI: `pip install gradio`
- (Optional) Gemini API for LLM-backed NLU: `pip install google-genai`

### Install Dependencies

```bash
pip install -r HospitalManagement/requirements.txt
```

### Run Tests

```bash
# Set encoding for Windows
set PYTHONIOENCODING=utf-8

# Run all 8 scenario tests
python -m HospitalManagement.test_scenarios
```

### CLI Demo

```bash
# Default assessment scenario
python -m HospitalManagement.run_demo

# Custom query
python -m HospitalManagement.run_demo --patient P002 --query "Book a cardiologist appointment"

# Pre-built demos
python -m HospitalManagement.run_demo --demo standard
python -m HospitalManagement.run_demo --demo recovery    # failure recovery
python -m HospitalManagement.run_demo --demo booking-fail # graceful failure
python -m HospitalManagement.run_demo --demo notify-fail  # notification demo

# Verbose logging
python -m HospitalManagement.run_demo -v
```

### Web UI (Gradio)

```bash
python -m HospitalManagement.app
# Opens at http://localhost:7860
```

### Enable Gemini NLU (Optional)

1. Create a `.env` file in the root of the `HospitalManagement` directory.
2. Add your Gemini API key to the `.env` file like this:
```env
GEMINI_API_KEY=your-api-key-here
```

When a Gemini API key is set in the `.env` file, the system automatically uses Gemini for intent extraction with automatic fallback to the rule-based NLU if the API call fails.

## Sample Output

```json
{
  "appointment_status": "Booked — A200 with Dr. Brown on 2026-07-10 09:00",
  "lab_test_status": "ecg test scheduled (ID: L500)",
  "notification_status": "Sent via sms",
  "summary": "Patient: Alice Smith. Symptoms: chest pain, pain. Appointment: Booked — A200 with Dr. Brown on 2026-07-10 09:00. Lab Test: ecg test scheduled (ID: L500). Notification: Sent via sms."
}
```

## Project Structure

```
HospitalManagement/
├── __init__.py              # Package root
├── __main__.py              # Entry point for python -m
├── app.py                   # Gradio web UI
├── bootstrap.py             # Agent/NLU wiring
├── run_demo.py              # CLI runner with demo scenarios
├── test_scenarios.py        # 8 comprehensive scenario tests
├── requirements.txt         # Dependencies
├── README.md                # This file
├── core/
│   ├── __init__.py
│   ├── hospital_db.py       # Snapshot-isolated hospital database
│   ├── state.py             # Task DAG, Message bus, SharedState
│   └── orchestrator.py      # Dynamic DAG-based execution engine
├── nlu/
│   ├── __init__.py
│   ├── base.py              # NLUResult type + NLUExtractor protocol
│   ├── rule_based.py        # Deterministic keyword-based NLU
│   └── gemini_nlu.py        # Gemini API-backed NLU (optional)
└── agents/
    ├── __init__.py
    ├── base.py              # BaseAgent abstract class
    ├── intent_agent.py      # Task understanding + DAG construction
    ├── data_agents.py       # Patient, Doctor, Lab retrieval agents
    ├── booking_agents.py    # Slot check + appointment booking
    ├── confirmation_agent.py# Booking confirmation
    ├── notification_agent.py# Multi-channel notification
    └── validation_agent.py  # Output validation + self-correction
```

## Key Design Decisions

1. **No hardcoded workflow**: The task graph is built dynamically by `IntentAgent` based on NLU results. The orchestrator only knows how to execute a DAG — it has no knowledge of medical workflows.

2. **Snapshot isolation**: Each request gets a deep-copied database snapshot, so concurrent requests never interfere. This makes the system inherently thread-safe.

3. **Cascading skips**: If a task fails, all downstream dependents are automatically skipped (not executed), preventing wasted work and cascading errors.

4. **Two NLU backends**: Rule-based (zero dependencies, deterministic) and Gemini (more flexible, handles edge cases). The rule-based backend is the default; Gemini is used when `GEMINI_API_KEY` is set, with automatic fallback.

5. **Inter-agent communication**: Agents communicate via both shared state mutation AND a broadcast message log. This satisfies the requirement while also providing an auditable communication trace.
