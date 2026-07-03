"""
Base agent interface.

Every agent must inherit from ``BaseAgent`` and implement ``execute``.
The orchestrator calls ``execute(task, state)`` and handles lifecycle
(mark_running / mark_done / mark_failed) automatically.
"""

from __future__ import annotations

import abc
import logging
from typing import Any

from HospitalManagement.core.state import SharedState, Task

logger = logging.getLogger(__name__)


class BaseAgent(abc.ABC):
    """
    Abstract base for all agents.

    Subclasses implement ``execute(task, state)`` which:
    - reads ``task.params`` and ``state``
    - performs its work (may mutate ``state.db``, ``state.output``, etc.)
    - returns a result value (stored in ``task.result``)
    - raises on failure (caught by orchestrator → ``task.mark_failed``)
    """

    name: str = "BaseAgent"

    @abc.abstractmethod
    def execute(self, task: Task, state: SharedState) -> Any:
        """Execute the task.  Return value is stored as ``task.result``."""
        ...

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}>"
