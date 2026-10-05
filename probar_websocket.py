import asyncio
import glob
import os
import websockets


def obtener_ultimo_audio():
  carpeta = r"D:\Documentos\Grabaciones de sonido"
  # Busca archivos de audio comunes
  patrones = [
      os.path.join(carpeta, "*.m4a"),
      os.path.join(carpeta, "*.wav"),
      os.path.join(carpeta, "*.mp3"),
  ]
  archivos = []
  for p in patrones:
    archivos.extend(glob.glob(p))

  if not archivos:
    return None

  # Devuelve el archivo modificado más recientemente
  return max(archivos, key=os.path.getmtime)


async def enviar_audio_prueba():
  uri = "ws://localhost:8000/ws/stream-audio"
  ruta_audio = obtener_ultimo_audio()

  if not ruta_audio:
    print(
        "❌ No se encontraron archivos de audio en 'D:\\Documentos\\Grabaciones"
        " de sonido'"
    )
    return

  print(f"🎙️ Usando archivo: {os.path.basename(ruta_audio)}")
  print("⚡ Conectando al WebSocket de VishGuard...")

  async with websockets.connect(uri) as websocket:
    print("✅ Conectado con éxito al backend.")

    with open(ruta_audio, "rb") as f:
      audio_bytes = f.read()

    print(f"📤 Enviando {len(audio_bytes)} bytes al servidor...")
    await websocket.send(audio_bytes)

    respuesta = await websocket.recv()
    print("\n📥 RESPUESTA RECIBIDA DE VISHGUARD AI:")
    print("--------------------------------------------------")
    print(respuesta)
    print("--------------------------------------------------")


asyncio.run(enviar_audio_prueba())