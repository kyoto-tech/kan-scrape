from fastapi import APIRouter

from app.api.routes import events, health

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(events.router)
