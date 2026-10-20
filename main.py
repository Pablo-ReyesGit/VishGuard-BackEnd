from contextlib import asynccontextmanager
import logging

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Cargar la configuración antes de importar rutas o servicios.
load_dotenv()

from database import init_db
from api.routes import alerts, analysis, health, login, stream, twilio_stream, users

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Crea las tablas que falten al iniciar. No actualiza tablas existentes.
    init_db()
    yield


app = FastAPI(
    title="VishGuard AI - Calibrated Detection Engine",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(alerts.router)
app.include_router(stream.router)
app.include_router(analysis.router)
app.include_router(twilio_stream.router)
app.include_router(login.router, prefix="/api/v1", tags=["auth"])
app.include_router(users.router, prefix="/api/v1", tags=["users"])


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
