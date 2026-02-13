from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .database import get_db_connection
from .routers import quiz, library, auth, highlights, admin, pdfs, flashcards
from fastapi.middleware.gzip import GZipMiddleware

app = FastAPI(
    title="MedQuiz Pro API", 
    version="0.2.0",
    redirect_slashes=False  # Disable 307 redirects for trailing slashes (prevents localhost leak behind proxy)
)

# Allow CORS for Next.js frontend (default port 3000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(GZipMiddleware, minimum_size=1000)

from fastapi import Request
from fastapi.responses import JSONResponse
import logging

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("backend.log")
    ]
)
logger = logging.getLogger(__name__)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Global Exception: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"message": "Internal Server Error", "detail": str(exc)},
    )

app.include_router(quiz.router)
app.include_router(library.router)
app.include_router(auth.router)
app.include_router(highlights.router)
app.include_router(admin.router)
app.include_router(pdfs.router)
app.include_router(flashcards.router)

from .job_worker import start_job_worker, stop_job_worker

@app.on_event("startup")
def _startup_job_worker():
    # Single worker thread that pulls from background_jobs and processes sequentially.
    start_job_worker()

@app.on_event("shutdown")
def _shutdown_job_worker():
    stop_job_worker()

@app.get("/")
def read_root():
    return {"status": "ok", "message": "MedQuiz Pro Backend is running (V2)"}

@app.get("/health")
def health_check():
    # Verify DB connection
    try:
        conn = get_db_connection()
        conn.execute("SELECT 1")
        conn.close()
        db_status = "connected"
    except Exception as e:
        db_status = f"error: {str(e)}"
        
    return {"status": "healthy", "database": db_status}
