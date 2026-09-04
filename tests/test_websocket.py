import asyncio
import websockets
import json

async def probar_conexion_live():
    uri = "ws://127.0.0.1:8000/ws/stream"
    print(f"🔌 Conectando a VishGuard AI WebSocket en {uri}...")

    try:
        async with websockets.connect(uri) as websocket:
            print(" Conexión WebSocket establecida con éxito.\n")

            casos = [
                "Buenas tardes, le hablo del banco para confirmar si realizo una compra en linea.",
                "Urgente, su cuenta tiene una transferencia sospechosa. Necesito su codigo OTP enviado por SMS para detenerla."
            ]

            for texto in casos:
<<<<<<< HEAD
                print(f"📤 Enviando al servidor: \"{texto}\"")
=======
                print(f" Enviando al servidor: \"{texto}\"")
>>>>>>> main
                await websocket.send(texto)

                # CORRECCIÓN AQUÍ: Usamos .recv() en lugar de .receive()
                respuesta = await websocket.recv()
                alerta = json.loads(respuesta)

                print(" Alerta Flotante Recibida desde el Backend:")
                print(f"   • Nivel Riesgo : {alerta.get('nivel_riesgo')}")
                print(f"   • Score        : {alerta.get('score')}%")
                print(f"   • Patrones     : {alerta.get('patrones_detectados')}")
                print(f"   • Recomendacion: {alerta.get('recomendacion')}\n")
                print("-" * 50)

    except Exception as e:
        print(f" Error durante la comunicación WebSocket: {e}")

if __name__ == "__main__":
    asyncio.run(probar_conexion_live())