from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from modules.analyzer import VishingAnalyzer
from database import init_db

# Inicializar Base de Datos
init_db()

app = FastAPI(title="VishGuard AI Backend - Gemini Engine")

# Habilitar CORS para permitir peticiones desde Android
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Instancia global del analizador con Gemini
analyzer = VishingAnalyzer()

class CallRequest(BaseModel):
    texto: str

@app.get("/")
def check_health():
    return {"status": "online", "model": "Gemini 2.5 Flash", "system": "VishGuard AI Engine"}

@app.post("/analizar-llamada")
def analizar_llamada(data: CallRequest, request: Request):
    ip_cliente = request.client.host
    print("\n" + "="*60)
    print(f"🔌 [PETICIÓN RECIBIDA] Desde: {ip_cliente}")
    print(f"📥 [TRANSCRIPCIÓN]: \"{data.texto}\"")
    print("="*60)

    # Inferencia de contexto mediante Gemini
    resultado = analyzer.analizar_texto(data.texto)

    print(f"📊 [EVALUACIÓN GEMINI]: Riesgo={resultado.get('nivel_riesgo')} | Score={resultado.get('score')}%")
    print(f"💡 [RECOMENDACIÓN]: {resultado.get('recomendacion')}\n")

    return resultado

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)