
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from API.voice.middleware import TimingMiddleware
from API.voice.routes import stt_router, search_router, metrics_router

# Initialize FastAPI app
app = FastAPI(title="Tme AI Agent - Voice Engine")

# Mount static files (frontend)
app.mount("/static", StaticFiles(directory="font_end"), name="static")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Cho phép tất cả origins (dev mode)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add middleware
app.add_middleware(TimingMiddleware)

# Include routers with /v1 prefix
app.include_router(stt_router, prefix="/v1")
app.include_router(search_router, prefix="/v1")
app.include_router(metrics_router, prefix="/v1")


@app.get("/")
async def root():
    """Health check endpoint"""
    return {"status": "ok", "service": "Tme AI Agent - Voice Engine"}
