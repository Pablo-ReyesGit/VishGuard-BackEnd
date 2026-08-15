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