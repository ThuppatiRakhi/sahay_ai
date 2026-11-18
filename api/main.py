
"""Main FastAPI application for SahayAI."""

import asyncio
from contextlib import asynccontextmanager
import logging
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.auth import router as auth_router
from api.applications import router as applications_router
from api.chat import router as chat_router
from api.documents import router as documents_router
from api.profile import router as profile_router
from api.schemes import router as schemes_router
from api.voice import router as voice_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context manager.

    Performs non-blocking startup maintenance:
    - Purges expired or revoked user sessions from SQLite via a worker threadpool
      (asyncio.to_thread) to prevent blocking the asynchronous event loop.
    - Validates SAHAY_PII_ENCRYPTION_KEY at startup for secure PII protection.
    - Gracefully handles transient database locks without failing application startup
      or exposing database internals.
    Avoids spawning unmanaged background threads that duplicate during development reloads.
    """
    try:
        from profile.session_manager import SessionManager
        session_mgr = SessionManager()
        cleaned = await asyncio.to_thread(session_mgr.cleanup_expired_sessions)
        logger.info("Application startup: cleaned up %d expired/revoked sessions.", cleaned)
    except Exception as exc:
        logger.warning("Startup session cleanup encountered error: %s", exc)

    # Validate PII encryption key configuration
    try:
        pii_key = os.environ.get("SAHAY_PII_ENCRYPTION_KEY", "").strip()
        if pii_key:
            from cryptography.fernet import Fernet
            Fernet(pii_key.encode("utf-8"))
            logger.info("Application startup: SAHAY_PII_ENCRYPTION_KEY validated successfully.")
        else:
            logger.warning("Application startup: SAHAY_PII_ENCRYPTION_KEY is not configured.")
            if os.environ.get("APP_ENV", "").lower() == "production":
                raise RuntimeError("SAHAY_PII_ENCRYPTION_KEY must be configured in production.")
    except Exception as exc:
        logger.error("Application startup: SAHAY_PII_ENCRYPTION_KEY validation error: %s", exc)
        if os.environ.get("APP_ENV", "").lower() == "production":
            raise

    yield


app = FastAPI(
    title="SahayAI API",
    description="Backend API for government scheme discovery and assistance.",
    version="1.0.0",
    lifespan=lifespan,
)

# Production note on Cookie & HTTPS Security:
# 1. When deploying to production with HTTPS:
#    - set APP_ENV=production
#    - set SESSION_COOKIE_SECURE=true (ensures cookies are only transmitted over TLS)
#    - set SESSION_COOKIE_SAMESITE=lax (or 'strict' if frontend and API share the exact same domain)
#    - set SESSION_SECRET_KEY to a high-entropy secret >= 32 chars
# 2. When allow_credentials=True, CORS specifications forbid wildcard '*' in allow_origins.
#    Origins must be explicitly enumerated.
LOCAL_FRONTEND_ORIGINS = [
    "http://127.0.0.1:5500",
    "http://localhost:5500",
    "http://127.0.0.1:5501",
    "http://localhost:5501",
    "http://127.0.0.1:8000",
    "http://localhost:8000",
    "https://sahay-ai-ste8.onrender.com",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=LOCAL_FRONTEND_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-CSRF-Token"],
)

app.include_router(auth_router)
app.include_router(applications_router)
app.include_router(chat_router)
app.include_router(documents_router)
app.include_router(profile_router)
app.include_router(schemes_router)
app.include_router(voice_router)
app.include_router(voice_router, prefix="/api")

# Mount frontend static files for direct browser access
import os
from fastapi.staticfiles import StaticFiles

frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
if os.path.isdir(frontend_dir):
    app.mount("/frontend", StaticFiles(directory=frontend_dir, html=True), name="frontend")


@app.get("/")
def home():
    return {
        "success": True,
        "message": "Welcome to SahayAI API",
    }


@app.get("/health")
def health_check():
    return {
        "success": True,
        "status": "healthy",
        "service": "SahayAI",
    }
