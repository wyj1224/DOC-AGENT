import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db.database import init_db
from app.routers import agent, excel, knowledge, system, templates, word
from app.visitor import prepare_visitor, set_visitor_cookie


def cors_origins() -> list[str]:
    defaults = [
        "http://127.0.0.1:5174",
        "http://localhost:5174",
        "http://127.0.0.1:5175",
        "http://localhost:5175",
    ]
    configured = [
        origin.strip().rstrip("/")
        for origin in os.getenv("CORS_ORIGINS", "").split(",")
        if origin.strip()
    ]
    return defaults + configured


app = FastAPI(title="灵枢·规鉴 API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def anonymous_visitor_cookie(request, call_next):
    cookie_value = prepare_visitor(request)
    response = await call_next(request)
    set_visitor_cookie(response, cookie_value)
    return response

app.include_router(system.router)
app.include_router(knowledge.router)
app.include_router(excel.router)
app.include_router(word.router)
app.include_router(templates.router)
app.include_router(agent.router)


@app.on_event("startup")
def startup():
    init_db()
