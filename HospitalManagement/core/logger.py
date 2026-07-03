"""
Beautiful terminal logging for the Hospital Management System.

Provides colorful, structured log output that makes it easy to
follow the multi-agent workflow step by step.

Usage::

    from HospitalManagement.core.logger import setup_logging, agent_log
    setup_logging()
    agent_log("IntentAgent", "Detected 3 intents", level="info")
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    from colorama import Fore, Style, Back, init as colorama_init
    colorama_init(autoreset=True)
    HAS_COLOR = True
except ImportError:
    HAS_COLOR = False

    class _Stub:
        def __getattr__(self, name):
            return ""

    Fore = _Stub()
    Style = _Stub()
    Back = _Stub()


# ──────────────────────────────────────────────────────────────────
# Agent icons and colors
# ──────────────────────────────────────────────────────────────────

AGENT_STYLE = {
    "Orchestrator":           {"icon": ">>", "color": Fore.CYAN},
    "IntentAgent":            {"icon": "AI", "color": Fore.YELLOW},
    "PatientHistoryAgent":    {"icon": "PT", "color": Fore.GREEN},
    "DoctorSearchAgent":      {"icon": "DR", "color": Fore.BLUE},
    "SlotAvailabilityAgent":  {"icon": "SL", "color": Fore.MAGENTA},
    "AppointmentBookingAgent":{"icon": "BK", "color": Fore.CYAN},
    "ConfirmationAgent":      {"icon": "CF", "color": Fore.GREEN},
    "LabReportCheckAgent":    {"icon": "LB", "color": Fore.YELLOW},
    "NotificationAgent":      {"icon": "NT", "color": Fore.BLUE},
    "ValidationAgent":        {"icon": "VL", "color": Fore.GREEN},
}

LEVEL_COLORS = {
    "DEBUG":    Fore.WHITE,
    "INFO":     Fore.WHITE,
    "WARNING":  Fore.YELLOW,
    "ERROR":    Fore.RED,
    "CRITICAL": Fore.RED,
}


# ──────────────────────────────────────────────────────────────────
# Custom formatter
# ──────────────────────────────────────────────────────────────────

class HospitalLogFormatter(logging.Formatter):
    """Pretty-prints log records with timestamps, agent icons, and colors."""

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.now().strftime("%H:%M:%S")

        # Determine agent name from the record
        agent = getattr(record, "agent_name", None)
        if not agent:
            name_parts = record.name.split(".")
            agent = name_parts[-1] if len(name_parts) > 1 else "System"

        style = AGENT_STYLE.get(agent, {"icon": "--", "color": Fore.WHITE})
        icon = style["icon"]
        agent_color = style["color"]
        level_color = LEVEL_COLORS.get(record.levelname, Fore.WHITE)

        msg = record.getMessage()

        # Format: [HH:MM:SS] [IC] AGENT_NAME       | message
        return (
            f"{Fore.CYAN}[{ts}]{Style.RESET_ALL} "
            f"{agent_color}[{icon}]{Style.RESET_ALL} "
            f"{agent_color}{agent:<24}{Style.RESET_ALL} "
            f"{Fore.WHITE}|{Style.RESET_ALL} "
            f"{level_color}{msg}{Style.RESET_ALL}"
        )


# ──────────────────────────────────────────────────────────────────
# Log capture handler (for sending logs to the UI)
# ──────────────────────────────────────────────────────────────────

class LogCaptureHandler(logging.Handler):
    """Captures log records into a list for returning to the UI."""

    def __init__(self):
        super().__init__()
        self.records: List[Dict[str, Any]] = []

    def emit(self, record: logging.LogRecord) -> None:
        agent = getattr(record, "agent_name", None)
        if not agent:
            name_parts = record.name.split(".")
            agent = name_parts[-1] if len(name_parts) > 1 else "System"

        style = AGENT_STYLE.get(agent, {"icon": "--", "color": ""})

        self.records.append({
            "timestamp": datetime.fromtimestamp(record.created).strftime("%H:%M:%S.%f")[:-3],
            "level": record.levelname,
            "agent": agent,
            "icon": style["icon"],
            "message": record.getMessage(),
        })

    def get_logs(self) -> List[Dict[str, Any]]:
        return list(self.records)

    def clear(self) -> None:
        self.records.clear()


# ──────────────────────────────────────────────────────────────────
# Setup function
# ──────────────────────────────────────────────────────────────────

_initialized = False


def setup_logging(level: int = logging.INFO) -> None:
    """
    Configure the HospitalManagement logger with beautiful formatting.
    Call once at application startup.
    """
    global _initialized
    if _initialized:
        return
    _initialized = True

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(HospitalLogFormatter())
    handler.setLevel(level)

    # Configure the root HospitalManagement logger
    root = logging.getLogger("HospitalManagement")
    root.setLevel(level)
    root.handlers = [handler]
    root.propagate = False


def agent_log(
    agent_name: str,
    message: str,
    level: str = "info",
) -> None:
    """
    Convenience function for agents to emit structured log messages.

    Parameters
    ----------
    agent_name : str
        Name of the agent (e.g. ``"IntentAgent"``).
    message : str
        The log message.
    level : str
        Log level: ``"debug"``, ``"info"``, ``"warning"``, ``"error"``.
    """
    logger = logging.getLogger(f"HospitalManagement.agents.{agent_name}")
    record = logger.makeRecord(
        name=logger.name,
        level=getattr(logging, level.upper(), logging.INFO),
        fn="",
        lno=0,
        msg=message,
        args=(),
        exc_info=None,
    )
    record.agent_name = agent_name
    logger.handle(record)


def print_banner(host: str = "localhost", port: int = 8000) -> None:
    """Print a startup banner to the terminal."""
    print()
    print(f"{Fore.CYAN}{'=' * 62}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}  Hospital AI Management System - Server Started{Style.RESET_ALL}")
    print(f"{Fore.CYAN}  URL: {Fore.WHITE}http://{host}:{port}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}  Database: {Fore.WHITE}SQLite (persistent){Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'=' * 62}{Style.RESET_ALL}")
    print()


def print_request_header(patient_id: str, query: str) -> None:
    """Print a visual header for an incoming request."""
    short_query = query[:60] + "..." if len(query) > 60 else query
    print()
    print(f"{Fore.CYAN}{'~' * 62}{Style.RESET_ALL}")
    print(
        f"{Fore.CYAN}  NEW REQUEST{Style.RESET_ALL} | "
        f"Patient: {Fore.WHITE}{patient_id}{Style.RESET_ALL} | "
        f'"{Fore.WHITE}{short_query}{Style.RESET_ALL}"'
    )
    print(f"{Fore.CYAN}{'~' * 62}{Style.RESET_ALL}")


def print_request_footer(elapsed_ms: int, retries: int) -> None:
    """Print a visual footer after a request completes."""
    print(
        f"{Fore.GREEN}  COMPLETE{Style.RESET_ALL} | "
        f"Time: {Fore.WHITE}{elapsed_ms}ms{Style.RESET_ALL} | "
        f"Retries: {Fore.WHITE}{retries}{Style.RESET_ALL}"
    )
    print(f"{Fore.CYAN}{'~' * 62}{Style.RESET_ALL}")
    print()
