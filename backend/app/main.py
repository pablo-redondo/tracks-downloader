from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator

from .downloader import ALLOWED_DOMAINS, JobManager

app = FastAPI(title="Tracks Downloader")
job_manager = JobManager()


class CreateJobRequest(BaseModel):
    url: str
    quality: str = "192"

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        v = v.strip()
        if not v or not any(domain in v for domain in ALLOWED_DOMAINS):
            raise ValueError("Solo se admiten enlaces de YouTube o SoundCloud")
        return v

    @field_validator("quality")
    @classmethod
    def validate_quality(cls, v: str) -> str:
        if v not in {"128", "192", "320"}:
            raise ValueError("Calidad no válida")
        return v


@app.post("/api/jobs")
def create_job(payload: CreateJobRequest):
    job_id = job_manager.create_job(payload.url, payload.quality)
    return {"job_id": job_id}


@app.get("/api/jobs")
def list_jobs():
    return job_manager.list_jobs()


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = job_manager.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job no encontrado")
    return job.to_dict()


@app.get("/api/jobs/{job_id}/items/{item_id}/file")
def download_item(job_id: str, item_id: str):
    job = job_manager.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job no encontrado")
    item = job.items.get(item_id)
    if item is None or not item.file_path or not Path(item.file_path).exists():
        raise HTTPException(status_code=404, detail="Archivo no disponible")
    return FileResponse(item.file_path, filename=Path(item.file_path).name, media_type="audio/mpeg")


@app.get("/api/jobs/{job_id}/zip")
def download_zip(job_id: str):
    job = job_manager.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job no encontrado")
    zip_path = job_manager.build_zip(job_id)
    if zip_path is None:
        raise HTTPException(status_code=404, detail="No hay archivos completados todavía")
    return FileResponse(zip_path, filename=f"{job.title or job_id}.zip", media_type="application/zip")


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str):
    if not job_manager.delete_job(job_id):
        raise HTTPException(status_code=404, detail="Job no encontrado")
    return {"ok": True}


frontend_dir = Path(__file__).resolve().parent.parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
