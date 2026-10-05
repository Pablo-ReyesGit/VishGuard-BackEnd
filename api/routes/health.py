from fastapi import APIRouter

router = APIRouter()

@router.get("/")
def check_health():
    return {"status": "online", "system": "VishGuard AI Engine"}