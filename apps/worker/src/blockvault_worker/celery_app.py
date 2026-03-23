from __future__ import annotations

import os
import sys
from pathlib import Path

from celery import Celery

API_SRC = Path(__file__).resolve().parents[3] / "api" / "src"
if str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))

broker_url = os.getenv("BLOCKVAULT_CELERY_BROKER_URL", "redis://127.0.0.1:6379/0")
result_backend = os.getenv("BLOCKVAULT_CELERY_RESULT_BACKEND", broker_url)

celery_app = Celery("blockvault_worker", broker=broker_url, backend=result_backend)
celery_app.conf.task_serializer = "json"
celery_app.conf.result_serializer = "json"
celery_app.conf.accept_content = ["json"]
celery_app.conf.imports = ("blockvault_worker.tasks",)
