from fastapi import FastAPI

from app.routers import health, imports

app = FastAPI(
    title="The Pour Over Mini CDP",
    description="Subscriber, web and app data in one place.",
    docs_url="/app/docs",
    openapi_url="/app/openapi.json",
    redoc_url=None,
)

API_PREFIX = "/app"
app.include_router(health.router, prefix=API_PREFIX)
app.include_router(imports.router, prefix=API_PREFIX)
