import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db.database import init_db
from app.routers import agent, auth, excel, knowledge, system, templates, word


def cors_origins() -> list[str]:
    defaults = ["http://127.0.0.1:5173", "http://localhost:5173"]
    configured = [
        origin.strip().rstrip("/")
        for origin in os.getenv("CORS_ORIGINS", "").split(",")
        if origin.strip()
    ]
    return defaults + configured


app = FastAPI(title="Clause Agent API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(system.router)
app.include_router(auth.router)
app.include_router(knowledge.router)
app.include_router(excel.router)
app.include_router(word.router)
app.include_router(templates.router)
app.include_router(agent.router)


@app.on_event("startup")
def startup():
    init_db()
