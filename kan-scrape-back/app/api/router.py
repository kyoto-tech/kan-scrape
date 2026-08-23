import fastapi

from app.api.routes import events, health, match, speech, transcribe

api_router = fastapi.APIRouter()
api_router.include_router(health.router)
api_router.include_router(events.router)
api_router.include_router(match.router)
api_router.include_router(speech.router)
api_router.include_router(transcribe.router)
