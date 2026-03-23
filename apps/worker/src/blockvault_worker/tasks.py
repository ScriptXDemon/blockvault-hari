from __future__ import annotations

from .celery_app import celery_app


@celery_app.task(name="blockvault.redactions.run")
def run_redaction_job(job_id: str) -> None:
    from blockvault_api.redaction_jobs import run_redaction_job as execute_redaction_job

    execute_redaction_job(job_id)
