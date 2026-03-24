"""FastAPI backend for GroundwaterGPT Dashboard.

Thin application factory — all endpoint logic lives in ``api.routes.*``.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes.chat import GROUNDWATER_KB, _fallback_response, _get_site_context  # noqa: F401
from api.routes.chat import router as chat_router
from api.routes.data import router as data_router
from api.routes.knowledge import router as knowledge_router
from api.routes.research_workflow import router as research_workflow_router
from api.routes.wells import router as wells_router
from api.site_metadata import SITE_METADATA  # noqa: F401

app = FastAPI(title="GroundwaterGPT API", version="1.0.0")

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
app.include_router(research_workflow_router)
app.include_router(wells_router)


@app.get("/")
def root():
    """API root — health-check and link to docs."""
    return {
        "name": "GroundwaterGPT API",
        "version": "1.0.0",
        "docs": "/docs",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
