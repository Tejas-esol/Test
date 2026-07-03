"""
Dynamic Agentic Orchestrator — the core execution engine.

Responsibilities:
- Accepts a patient request and runs NLU (via IntentAgent).
- Executes the dynamically-built task DAG.
- Dispatches independent tasks in parallel (asyncio + ThreadPool).
- Handles cascading skips for failed dependencies.
- Runs validation and retries if issues are detected.
- Produces the final structured JSON response.
- Emits rich terminal logs for every step.
"""

from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List

from HospitalManagement.agents.base import BaseAgent
from HospitalManagement.core.logger import (
    LogCaptureHandler,
    agent_log,
    print_request_footer,
    print_request_header,
)
from HospitalManagement.core.state import SharedState, Task, TaskStatus

logger = logging.getLogger("HospitalManagement.core.orchestrator")


class Orchestrator:
    """
    Event-loop driven orchestrator that runs agents based on task
    readiness in the DAG.

    Key design decisions:
    - **No hardcoded sequence**: the orchestrator only looks at which
      tasks are *ready* (all deps terminal), not at task kinds.
    - **Parallel dispatch**: all concurrently-ready tasks run in a
      thread pool simultaneously.
    - **Self-correction**: after all tasks complete, if the
      ValidationAgent reports issues, the orchestrator resets failed
      tasks and retries (up to ``max_retries``).
    - **Structured logging**: every step emits agent-tagged log
      messages for terminal visibility.
    """

    def __init__(self, agents: Dict[str, BaseAgent], max_retries: int = 2):
        self._agents = agents
        self._max_retries = max_retries

    # ── public API ───────────────────────────────────────────────

    def run(self, state: SharedState) -> Dict[str, Any]:
        """Synchronous entry point — runs the event loop."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                raise RuntimeError("closed")
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(self.run_async(state))

    async def run_async(self, state: SharedState) -> Dict[str, Any]:
        """
        Asynchronous entry point.

        1. Run IntentAgent to build the task DAG.
        2. Execute the DAG in topological-ready order.
        3. Validate and retry if needed.
        4. Return final output with logs.
        """
        start = time.time()

        # Attach a log capture handler for this request
        log_capture = LogCaptureHandler()
        root_logger = logging.getLogger("HospitalManagement")
        root_logger.addHandler(log_capture)

        # Print request header
        print_request_header(state.patient_id, state.user_query)

        try:
            # ── Phase 1: Intent understanding ────────────────────
            agent_log("Orchestrator", f"Processing request for patient {state.patient_id}")

            intent_task = Task(
                kind="UNDERSTAND_INTENT",
                agent_name="IntentAgent",
            )
            state.add_task(intent_task)
            self._execute_task(intent_task, state)

            if intent_task.status == TaskStatus.FAILED:
                agent_log("Orchestrator", f"Failed to understand request: {intent_task.error}", "error")
                return self._build_output(state, start, log_capture, error=intent_task.error)

            # Log the task DAG
            task_kinds = [t.kind for t in state.tasks.values() if t.kind != "UNDERSTAND_INTENT"]
            agent_log("Orchestrator", f"Task DAG built: {len(task_kinds)} tasks -> {', '.join(task_kinds)}")

            # ── Phase 2: Execute the DAG ─────────────────────────
            await self._execute_dag(state)

            # ── Phase 3: Validation + retry loop ─────────────────
            for attempt in range(self._max_retries + 1):
                val_task = state.get_task_by_kind("VALIDATE")
                if val_task and val_task.status == TaskStatus.DONE:
                    result = val_task.result
                    if isinstance(result, dict) and result.get("valid", True):
                        agent_log("Orchestrator", "Validation passed - all checks OK")
                        break
                    issues = result.get("issues", []) if isinstance(result, dict) else []
                    if issues and attempt < self._max_retries:
                        agent_log(
                            "Orchestrator",
                            f"Validation found {len(issues)} issue(s) - retrying (attempt {attempt + 2})",
                            "warning",
                        )
                        state.retry_count += 1
                        self._reset_for_retry(state, issues)
                        await self._execute_dag(state)
                    else:
                        break
                else:
                    break

            elapsed_ms = round((time.time() - start) * 1000)
            agent_log("Orchestrator", f"Completed in {elapsed_ms}ms ({state.retry_count} retries)")
            print_request_footer(elapsed_ms, state.retry_count)

            return self._build_output(state, start, log_capture)

        finally:
            root_logger.removeHandler(log_capture)

    # ── output builder ───────────────────────────────────────────

    def _build_output(
        self,
        state: SharedState,
        start: float,
        log_capture: LogCaptureHandler,
        error: str | None = None,
    ) -> Dict[str, Any]:
        """Assemble the final output dict."""
        elapsed_ms = round((time.time() - start) * 1000)

        if error:
            return {
                "appointment_status": "N/A",
                "lab_test_status": "N/A",
                "notification_status": "N/A",
                "summary": f"Failed to understand request: {error}",
                "task_trace": state.task_trace(),
                "message_trace": state.message_trace(),
                "logs": log_capture.get_logs(),
                "elapsed_ms": elapsed_ms,
                "retry_count": state.retry_count,
            }

        return {
            "appointment_status": state.output.get("appointment_status", "N/A"),
            "lab_test_status": state.output.get("lab_test_status", "N/A"),
            "notification_status": state.output.get("notification_status", "N/A"),
            "summary": state.output.get("summary", "No summary generated"),
            "task_trace": state.task_trace(),
            "message_trace": state.message_trace(),
            "logs": log_capture.get_logs(),
            "elapsed_ms": elapsed_ms,
            "retry_count": state.retry_count,
        }

    # ── DAG execution ────────────────────────────────────────────

    async def _execute_dag(self, state: SharedState) -> None:
        """Execute tasks in topological-ready order with parallel dispatch."""
        loop = asyncio.get_event_loop()
        max_iterations = 50

        for _ in range(max_iterations):
            if state.all_tasks_terminal():
                break

            ready: List[Task] = []
            for task in state.tasks.values():
                if task.status != TaskStatus.PENDING:
                    continue
                if not task.is_ready(state):
                    continue
                if task.should_skip(state):
                    failed_deps = [
                        state.tasks[d].kind
                        for d in task.depends_on_success
                        if state.tasks.get(d)
                        and state.tasks[d].status in (TaskStatus.FAILED, TaskStatus.SKIPPED)
                    ]
                    task.mark_skipped(f"Dependency failed/skipped: {', '.join(failed_deps)}")
                    self._on_task_complete(task, state)
                    continue
                ready.append(task)

            if not ready:
                pending = [t.kind for t in state.tasks.values() if t.status == TaskStatus.PENDING]
                if pending:
                    agent_log("Orchestrator", f"Deadlock detected - pending: {pending}", "error")
                    for t in state.tasks.values():
                        if t.status == TaskStatus.PENDING:
                            t.mark_failed("Deadlock - unresolvable dependencies")
                break

            # Log parallel dispatch
            if len(ready) > 1:
                names = [t.kind for t in ready]
                agent_log("Orchestrator", f"Parallel dispatch: {', '.join(names)}")

            # Execute
            if len(ready) == 1:
                self._execute_task(ready[0], state)
            else:
                with ThreadPoolExecutor(max_workers=len(ready)) as pool:
                    futures = [
                        loop.run_in_executor(pool, self._execute_task, task, state)
                        for task in ready
                    ]
                    await asyncio.gather(*futures)

    # ── single task execution ────────────────────────────────────

    def _execute_task(self, task: Task, state: SharedState) -> None:
        """Execute a single task by delegating to the appropriate agent."""
        agent = self._agents.get(task.agent_name)
        if agent is None:
            task.mark_failed(f"No agent registered for '{task.agent_name}'")
            agent_log("Orchestrator", f"No agent for '{task.agent_name}'", "error")
            self._on_task_complete(task, state)
            return

        task.mark_running()
        agent_log(task.agent_name, f"Starting: {task.kind}")

        try:
            result = agent.execute(task, state)
            task.mark_done(result)
            duration = round((task.finished_at - task.started_at) * 1000)
            agent_log(task.agent_name, f"Done: {task.kind} ({duration}ms)")
        except Exception as exc:
            task.mark_failed(str(exc))
            agent_log(task.agent_name, f"Failed: {task.kind} - {exc}", "error")

        self._on_task_complete(task, state)

    def _on_task_complete(self, task: Task, state: SharedState) -> None:
        """Post-completion hook — update output for key task kinds."""
        if task.status == TaskStatus.FAILED:
            kind = task.kind
            if kind == "SEARCH_DOCTORS":
                state.output["appointment_status"] = f"Failed - {task.error}"
            elif kind == "BOOK_APPOINTMENT":
                if "appointment_status" not in state.output:
                    state.output["appointment_status"] = f"Failed - {task.error}"
            elif kind.startswith("CHECK_LAB_"):
                if "lab_test_status" not in state.output:
                    state.output["lab_test_status"] = f"Failed - {task.error}"
            elif kind == "SEND_NOTIFICATION":
                state.output["notification_status"] = f"Failed - {task.error}"
        elif task.status == TaskStatus.SKIPPED:
            kind = task.kind
            if kind == "BOOK_APPOINTMENT":
                search_task = state.get_task_by_kind("SEARCH_DOCTORS")
                if search_task and search_task.error:
                    state.output["appointment_status"] = f"Failed - {search_task.error}"
                else:
                    state.output["appointment_status"] = "Skipped - dependency failed"
            elif kind == "SEND_NOTIFICATION":
                state.output["notification_status"] = "Skipped - dependent tasks failed"

    # ── retry logic ──────────────────────────────────────────────

    def _reset_for_retry(self, state: SharedState, issues: List[str]) -> None:
        """Reset failed/skipped tasks for retry."""
        for task in state.tasks.values():
            if task.kind == "VALIDATE" or task.status in (TaskStatus.FAILED, TaskStatus.SKIPPED):
                task.status = TaskStatus.PENDING
                task.result = None
                task.error = None
                task.started_at = None
                task.finished_at = None

        state.post_message(
            sender="Orchestrator",
            receiver="*",
            content=f"Retry #{state.retry_count}: resetting failed tasks",
            data={"issues": issues},
        )
