"""
FastAPI web server for the Hospital Management System.

Provides:
- REST API for processing patient queries
- REST API for retrieving patients, doctors, history
- Static file serving for the chat-based frontend
- Database reset endpoint for demo purposes

Launch::

    python -m HospitalManagement.server
    # Opens at http://localhost:8000
"""

from __future__ import annotations

import asyncio
import os
import sys
import logging

# Ensure parent dir is on path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional

from HospitalManagement.bootstrap import create_orchestrator
from HospitalManagement.core.hospital_db import HospitalDB
from HospitalManagement.core.logger import setup_logging, print_banner
from HospitalManagement.core.state import SharedState

# ──────────────────────────────────────────────────────────────────
# Setup
# ──────────────────────────────────────────────────────────────────

setup_logging()
logger = logging.getLogger("HospitalManagement.server")

# Persistent SQLite database (shared across all requests)
DB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "hospital_data.db",
)
db = HospitalDB.from_seed(db_path=DB_PATH)

# Pre-build the orchestrator
orchestrator = create_orchestrator(max_retries=2)

# Static files directory
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


# ──────────────────────────────────────────────────────────────────
# FastAPI app
# ──────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Hospital AI Management System",
    description="Multi-agent AI system for hospital workflows",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ──────────────────────────────────────────────────────────────────
# Request / Response models
# ──────────────────────────────────────────────────────────────────

class QueryRequest(BaseModel):
    patient_id: str
    query: str


class PatientCreateRequest(BaseModel):
    patient_id: str
    name: str
    age: int
    email: str = ""
    phone: str = ""


# ──────────────────────────────────────────────────────────────────
# API endpoints
# ──────────────────────────────────────────────────────────────────

@app.post("/api/query")
async def process_query(request: QueryRequest):
    """Process a patient query through the multi-agent system."""
    if not request.patient_id.strip():
        raise HTTPException(status_code=400, detail="Patient ID is required")
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Query is required")

    # Verify patient exists
    patient = db.get_patient(request.patient_id.strip())
    if patient is None:
        raise HTTPException(
            status_code=404,
            detail=f"Patient '{request.patient_id}' not found in database",
        )

    # Create state with the shared persistent DB
    state = SharedState(
        patient_id=request.patient_id.strip(),
        user_query=request.query.strip(),
        db=db,
    )

    # Run the orchestrator
    result = await orchestrator.run_async(state)

    return JSONResponse(content=result)


@app.get("/api/patients")
async def get_patients():
    """Get all patients with their details."""
    patients = db.get_all_patients()
    return JSONResponse(content={"patients": patients})


@app.get("/api/patients/{patient_id}")
async def get_patient(patient_id: str):
    """Get a specific patient's details and history."""
    patient = db.get_patient(patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")

    labs = db.get_lab_reports(patient_id)
    appointments = []
    for appt_id in patient.get("appointments", []):
        # Get appointment details
        for appt in db.conn.execute(
            "SELECT * FROM appointments WHERE appointment_id = ?", (appt_id,)
        ).fetchall():
            doctor = db.get_doctor(appt.get("doctor_id", ""))
            appt_detail = dict(appt)
            if doctor:
                appt_detail["doctor_name"] = doctor["name"]
                appt_detail["specialization"] = doctor["specialization"]
            appointments.append(appt_detail)

    return JSONResponse(content={
        "patient": patient,
        "lab_reports": labs,
        "appointment_details": appointments,
    })


@app.get("/api/doctors")
async def get_doctors():
    """Get all doctors with their available slots."""
    doctors = db.get_all_doctors()
    return JSONResponse(content={"doctors": doctors})


@app.post("/api/reset")
async def reset_database():
    """Reset the database to initial seed data."""
    db.reset()
    logger.info("Database reset to seed data")
    return JSONResponse(content={"status": "Database reset successfully"})


@app.post("/api/patients")
async def add_patient(request: PatientCreateRequest):
    """Add a new patient to the database."""
    existing = db.get_patient(request.patient_id)
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Patient '{request.patient_id}' already exists",
        )
    patient = db.add_patient(
        patient_id=request.patient_id,
        name=request.name,
        age=request.age,
        email=request.email,
        phone=request.phone,
    )
    return JSONResponse(content={"patient": patient})


# ──────────────────────────────────────────────────────────────────
# Static file serving
# ──────────────────────────────────────────────────────────────────

@app.get("/")
async def serve_index():
    """Serve the main frontend page."""
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


# Mount static files (CSS, JS)
if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ──────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    print_banner(host="localhost", port=8000)
    uvicorn.run(
        "HospitalManagement.server:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="warning",  # Suppress uvicorn noise; our logger handles it
    )
