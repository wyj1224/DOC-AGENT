from fastapi import APIRouter


router = APIRouter(tags=["系统"])


@router.get("/health")
def health():
    return {"status": "ok"}
