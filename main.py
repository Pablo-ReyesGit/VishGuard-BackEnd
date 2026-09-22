from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import SQLModel

from database import engine, init_db
from api.routes import health, alerts, stream, analysis, twilio_stream, login, users

# Importante: importar modelos para que SQLModel registre la tabla 'User'
import models 


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Inicializa y crea todas las tablas en Neon/Postgres al arrancar
    init_db()
    yield


# Instanciación ÚNICA pasando el lifespan
app = FastAPI(
    title="VishGuard AI - Calibrated Detection Engine",
    lifespan=lifespan
)

# Configuración de CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Inclusión de routers
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