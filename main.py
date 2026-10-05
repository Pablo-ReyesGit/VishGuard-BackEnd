from dotenv import load_dotenv

load_dotenv()  # Carga variables (.env) antes de importar submódulos

from api.routes import alerts, analysis, health, stream
from database import init_db
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Inicialización de la base de datos local (SQLite/PostgreSQL)
init_db()

app = FastAPI(
    title="VishGuard AI - Calibrated Detection Engine",
    description="Motor en tiempo real para detección de Vishing mediante Groq Whisper y LLaMA",
    version="1.0.0",
)

# Configuración de permisos CORS para comunicación fluida con Android
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Inclusión de Routers HTTP y WebSocket
app.include_router(health.router)
app.include_router(alerts.router)
app.include_router(analysis.router)
app.include_router(stream.router)  # Endpoint WebSocket (/ws/stream-audio)

if __name__ == "__main__":
  import uvicorn

  uvicorn.run(app, host="0.0.0.0", port=8000)