<<<<<<< HEAD
import asyncio
import websockets

async def simulador_interactivo():
    uri = "ws://127.0.0.1:8000/ws/stream"
    print("="*60)
    print(" 📞 SIMULADOR DE LLAMADAS EN TIEMPO REAL - VISHGUARD AI")
    print("="*60)
    print("💡 Escribe cualquier texto de la llamada y presiona ENTER para enviarlo.")
    print("💡 Para salir escribe 'salir'.\n")

    try:
        # Configuramos ping_interval y ping_timeout para mantener la conexión viva
        async with websockets.connect(uri, ping_interval=20, ping_timeout=20) as websocket:
            print("✅ Conectado al servidor WebSocket de forma estable.\n")
            
            while True:
                texto = input("\n🎙️ Transcripción de la llamada > ")
                
                if texto.strip().lower() == "salir":
                    print("👋 Cerrando simulación...")
                    break
                
                if not texto.strip():
                    continue

                print("📤 Enviando al servidor y analizando con la IA...")
                await websocket.send(texto)
                
                # Esperar respuesta del backend
                respuesta = await websocket.recv()
                print(f"\n📥 Respuesta recibida de la IA:\n{respuesta}")

    except websockets.exceptions.ConnectionClosedError as e:
        print(f"\n⚠️ Conexión cerrada por el servidor: {e}")
    except Exception as e:
        print(f"\n❌ Error de conexión: {e}")

if __name__ == "__main__":
    asyncio.run(simulador_interactivo())
=======
import requests

# URL de tu backend HTTP local
URL = "http://localhost:8000/analizar-llamada"

print("="*60)
print("📞 SIMULADOR DE TRANSCRIPCIÓN DE LLAMADA - VISHGUARD AI")
print("="*60)

texto_transcrito = input("\n✍️ Escribe el texto transcrito de la llamada: ")

if texto_transcrito.strip():
    print("\n🔄 Enviando al servidor para análisis de IA...")
    try:
        # Enviar petición de una sola vía
        response = requests.post(URL, json={"texto": texto_transcrito})
        
        if response.status_code == 200:
            data = response.json()
            print("\n" + "="*40)
            print("📊 RESULTADO DEL ANÁLISIS")
            print("="*40)
            print(f"🚨 Nivel de Riesgo : {data.get('nivel_riesgo')}")
            print(f"📈 Score de Amenaza: {data.get('score')}%")
            print(f"💡 Recomendación   : {data.get('recomendacion')}")
            print("="*40)
            print("✅ Petición completada y conexión cerrada exitosamente.\n")
        else:
            print(f"⚠️ Error en la respuesta del servidor: status {response.status_code}")
    except Exception as e:
        print(f"❌ Error de conexión: {e}")
else:
    print("⚠️ No ingresaste texto.")
>>>>>>> main
