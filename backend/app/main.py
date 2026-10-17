from fastapi import FastAPI

from app.routers import assistant, auth, events, health, imports, segments, subscribers, webhooks

app = FastAPI(
    title="The Pour Over Mini CDP",
    description="Subscriber, web and app data in one place.",
    docs_url="/app/docs",
    openapi_url="/app/openapi.json",
    redoc_url=None,
)

API_PREFIX = "/app"
app.include_router(health.router, prefix=API_PREFIX)
app.include_router(auth.router, prefix=API_PREFIX)
app.include_router(imports.router, prefix=API_PREFIX)
app.include_router(subscribers.router)
app.include_router(segments.router)
app.include_router(events.router)
app.include_router(webhooks.router)
app.include_router(assistant.router)
