from __future__ import annotations

from functools import lru_cache
from typing import Any

from pymongo import MongoClient
from pymongo.database import Database

from .config import get_settings


@lru_cache(maxsize=1)
def get_client() -> MongoClient:
    settings = get_settings()
    if settings.mongo_uri.startswith("mongomock://"):
        import mongomock

        return mongomock.MongoClient()

    return MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=1500)


def get_database() -> Database:
    settings = get_settings()
    return get_client()[settings.mongo_database]


def reset_database_cache() -> None:
    get_client.cache_clear()


def ping_database() -> dict[str, Any]:
    if get_settings().mongo_uri.startswith("mongomock://"):
        return {"ok": 1.0, "engine": "mongomock"}
    return get_database().command("ping")
