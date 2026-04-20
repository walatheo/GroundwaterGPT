"""FastAPI backend for Florida Aquifer Analysis.

Thin application factory — all endpoint logic lives in ``api.routes.*``.
"""

# Load .env before any other project imports so API keys are available when
# the route modules initialise their LLM agents at import time.
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from api.routes.chat import router as chat_router  # noqa: E402
from api.routes.data import router as data_router  # noqa: E402
from api.routes.knowledge import router as knowledge_router  # noqa: E402
from api.routes.wells import router as wells_router  # noqa: E402
from api.site_metadata import SITE_METADATA  # noqa: F401, E402

app = FastAPI(title="Florida Aquifer Analysis API", version="1.0.0")

# Enable CORS for React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount route modules
app.include_router(data_router)
app.include_router(chat_router)
app.include_router(knowledge_router)
app.include_router(wells_router)


@app.get("/")
def root():
    """API root — health-check and link to docs."""
    return {
        "name": "Florida Aquifer Analysis API",
        "version": "1.0.0",
        "docs": "/docs",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
