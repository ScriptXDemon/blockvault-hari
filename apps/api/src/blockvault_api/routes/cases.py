from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..database import get_database
from ..repositories import create_case
from ..schemas import CreateCaseRequest
from ..security import SessionUser, current_user

router = APIRouter(prefix="/api/v1/cases", tags=["cases"])


@router.post("")
def create_case_route(payload: CreateCaseRequest, user: SessionUser = Depends(current_user)) -> dict[str, object]:
    record = create_case(owner_wallet=user.wallet_address, title=payload.title, description=payload.description)
    return {
        "id": record["case_id"],
        "title": record["title"],
        "description": record["description"],
        "createdAt": record["created_at"].isoformat(),
    }


@router.get("")
def list_cases(user: SessionUser = Depends(current_user)) -> dict[str, object]:
    db = get_database()
    items = [
        {
            "id": item["case_id"],
            "title": item["title"],
            "description": item["description"],
            "createdAt": item["created_at"].isoformat(),
        }
        for item in db.cases.find({"owner_wallet": user.wallet_address}).sort("created_at", -1)
    ]
    return {"items": items}


@router.get("/{case_id}")
def get_case(case_id: str, user: SessionUser = Depends(current_user)) -> dict[str, object]:
    db = get_database()
    item = db.cases.find_one({"case_id": case_id, "owner_wallet": user.wallet_address})
    if not item:
        raise HTTPException(status_code=404, detail="Case not found")
    return {
        "id": item["case_id"],
        "title": item["title"],
        "description": item["description"],
        "createdAt": item["created_at"].isoformat(),
    }
