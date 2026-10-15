from dotenv import load_dotenv
load_dotenv()  # DEBE IR PRIMERO que las importaciones de api.routes

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import SQLModel

from database import engine, init_db
from api.routes import health, alerts, stream, analysis, twilio_stream, login, users

# Importante: importar modelos para que SQLModel registre la tabla 'User'
import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


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

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception:
                pass

manager = ConnectionManager()

@app.get("/")
def check_health():
    return {"status": "online", "system": "VishGuard AI Engine"}

@app.get("/alerts")
def get_alert_history():
    """Endpoint HTTP para consultar el historial."""
    db = SessionLocal()
    try:
        alertas = db.query(AlertHistory).order_by(AlertHistory.timestamp.desc()).all()
        return alertas
    finally:
        db.close()

@app.websocket("/ws/stream")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    print("🔌 Cliente conectado al canal WebSocket de VishGuard AI.")
    
    try:
        while True:
            # 1. Recibir el texto de la llamada
            mensaje_transcrito = await websocket.receive_text()
            print(f"📥 [WebSocket Entrada]: \"{mensaje_transcrito}\"")
            
            if not mensaje_transcrito.strip():
                continue

            # 2. Analizar con la IA (Groq / Gemini)
            evaluacion = analyzer.analizar_texto(mensaje_transcrito)
            
            # 3. Guardar en Base de Datos SQLite si hay riesgo
            if evaluacion.get("nivel_riesgo") in ["PELIGROSO", "FRAUDE", "MEDIO"]:
                db = SessionLocal()
                try:
                    nueva_alerta = AlertHistory(
                        nivel_riesgo=evaluacion.get("nivel_riesgo"),
                        score=evaluacion.get("score"),
                        patrones_detectados=", ".join(evaluacion.get("patrones_detectados", [])),
                        frase_critica=evaluacion.get("frase_critica", ""),
                        recomendacion=evaluacion.get("recomendacion", "")
                    )
                    db.add(nueva_alerta)
                    db.commit()
                    print("💾 Alerta guardada en Base de Datos SQLite.")
                except Exception as db_err:
                    print(f"⚠️ Error al guardar en BD: {db_err}")
                finally:
                    db.close()

            # 4. 📌 RESPONDER DIRECTAMENTE AL CLIENTE SIN CERRAR EL SOCKET
            # En lugar de broadcast masivo, usamos websocket.send_json directamente
            await websocket.send_json(evaluacion)
            print("📤 Resultado JSON enviado de vuelta al cliente con éxito (Canal abierto).")

    except WebSocketDisconnect:
        manager.disconnect(websocket)
        print("⚠️ Cliente desconectado.")
    except Exception as e:
        print(f"❌ Error en sesión WebSocket: {e}")
        manager.disconnect(websocket)
