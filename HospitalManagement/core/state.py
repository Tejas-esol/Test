"""
Core state primitives — Task graph, Message bus, and SharedState.

Each user request produces a fresh ``SharedState`` that agents read
and mutate.  Tasks form a DAG (dependencies via ``depends_on_success``).
Agents post ``Message`` objects to a broadcast log so every agent can
observe the full communication history.
"""

from __future__ import annotations

import enum
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from HospitalManagement.core.hospital_db import HospitalDB


# ──────────────────────────────────────────────────────────────────
# Task status
# ──────────────────────────────────────────────────────────────────

class TaskStatus(enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"           # cascading skip from failed dependency


# ──────────────────────────────────────────────────────────────────
# Task — a unit of work in the execution graph
# ──────────────────────────────────────────────────────────────────

@dataclass
class Task:
    """
    Represents a discrete unit of work executed by a single agent.

    * ``kind``: human-readable label (e.g. ``"SEARCH_DOCTORS"``).
    * ``agent_name``: the agent responsible for this task.
    * ``depends_on_success``: set of task-ids that must be DONE before
      this task can run.
    * ``params``: arbitrary dict passed to the agent at execution time.
    """

    kind: str
    agent_name: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    depends_on_success: Set[str] = field(default_factory=set)
    params: Dict[str, Any] = field(default_factory=dict)
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: Optional[str] = None
    started_at: Optional[float] = None
    finished_at: Optional[float] = None

    # ── readiness predicates ─────────────────────────────────────

    @property
    def is_terminal(self) -> bool:
        return self.status in (TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.SKIPPED)

    def is_ready(self, state: "SharedState") -> bool:
        """True if all dependencies are terminal and task is still PENDING."""
        if self.status != TaskStatus.PENDING:
            return False
        terminal_ids = {
            tid for tid, t in state.tasks.items() if t.is_terminal
        }
        return self.depends_on_success.issubset(terminal_ids)

    def should_skip(self, state: "SharedState") -> bool:
        """
        True if any dependency in ``depends_on_success`` has a status
        that is **not** DONE (i.e. FAILED or SKIPPED).

        This enables cascading skips: if A fails, B (depends on A)
        is skipped, and C (depends on B) is also skipped.
        """
        for dep_id in self.depends_on_success:
            dep = state.tasks.get(dep_id)
            if dep and dep.status in (TaskStatus.FAILED, TaskStatus.SKIPPED):
                return True
        return False

    # ── lifecycle helpers ────────────────────────────────────────

    def mark_running(self) -> None:
        self.status = TaskStatus.RUNNING
        self.started_at = time.time()

    def mark_done(self, result: Any = None) -> None:
        self.status = TaskStatus.DONE
        self.result = result
        self.finished_at = time.time()

    def mark_failed(self, error: str) -> None:
        self.status = TaskStatus.FAILED
        self.error = error
        self.finished_at = time.time()

    def mark_skipped(self, reason: str = "dependency failed") -> None:
        self.status = TaskStatus.SKIPPED
        self.error = reason
        self.finished_at = time.time()


# ──────────────────────────────────────────────────────────────────
# Message — inter-agent communication log
# ──────────────────────────────────────────────────────────────────

@dataclass
class Message:
    """An immutable log entry for inter-agent communication."""

    sender: str                     # agent name
    receiver: str                   # agent name or "*" for broadcast
    content: str
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


# ──────────────────────────────────────────────────────────────────
# SharedState — single request context
# ──────────────────────────────────────────────────────────────────

@dataclass
class SharedState:
    """
    Mutable context shared across all agents for one user request.

    * ``db`` — snapshot-isolated hospital data store.
    * ``tasks`` — task DAG keyed by task-id.
    * ``messages`` — ordered inter-agent message log.
    * ``output`` — the final response dict accumulating results.
    * ``metadata`` — arbitrary scratchpad for agents to share data
      (e.g. NLU intents, detected specialization, etc.).
    """

    patient_id: str
    user_query: str
    db: HospitalDB = field(default_factory=HospitalDB.from_memory)

    # Task graph
    tasks: Dict[str, Task] = field(default_factory=dict)

    # Message bus
    messages: List[Message] = field(default_factory=list)

    # Final output (accumulated by agents)
    output: Dict[str, Any] = field(default_factory=dict)

    # Shared scratchpad
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Retry/validation tracking
    retry_count: int = 0
    max_retries: int = 2

    # ── helpers ──────────────────────────────────────────────────

    def add_task(self, task: Task) -> Task:
        self.tasks[task.id] = task
        return task

    def post_message(
        self,
        sender: str,
        receiver: str,
        content: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> Message:
        msg = Message(
            sender=sender,
            receiver=receiver,
            content=content,
            data=data or {},
        )
        self.messages.append(msg)
        return msg

    def get_task_by_kind(self, kind: str) -> Optional[Task]:
        """Return the first task matching ``kind``."""
        for t in self.tasks.values():
            if t.kind == kind:
                return t
        return None

    def all_tasks_terminal(self) -> bool:
        return all(t.is_terminal for t in self.tasks.values())

    def task_trace(self) -> List[Dict[str, Any]]:
        """Return a serialisable list of task statuses (for debugging/UI)."""
        return [
            {
                "task_id": t.id,
                "kind": t.kind,
                "agent": t.agent_name,
                "status": t.status.value,
                "result": _safe_repr(t.result),
                "error": t.error,
                "duration_ms": (
                    round((t.finished_at - t.started_at) * 1000)
                    if t.started_at and t.finished_at
                    else None
                ),
            }
            for t in self.tasks.values()
        ]

    def message_trace(self) -> List[Dict[str, str]]:
        """Return a serialisable list of messages (for debugging/UI)."""
        return [
            {
                "sender": m.sender,
                "receiver": m.receiver,
                "content": m.content,
            }
            for m in self.messages
        ]


def _safe_repr(obj: Any, max_len: int = 200) -> Optional[str]:
    if obj is None:
        return None
    s = str(obj)
    return s if len(s) <= max_len else s[:max_len] + "…"
