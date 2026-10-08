"""Prueba MANUAL del stream de Twilio. NO es un test de pytest.

Reemplaza a tests/test_twilio_stream.py, que ejecutaba `asyncio.run(...)` al
importarse: bastaba con correr `pytest` para que hiciera conexiones reales a
localhost:8000 (y, sin el servidor levantado, abortaba toda la recolección).

Envía unos segundos de silencio a /ws/twilio de un backend YA levantado y se
desconecta con un `stop`. Sirve para ver en la consola de uvicorn que el stream
se abre, se acumula audio y se cierra.

Uso:
    uvicorn main:app --port 8000          (en otra terminal)
    python probar_stream_manual.py
    python probar_stream_manual.py --url ws://localhost:8000 --segundos 6

Para probar los dos hablantes con la app conectada, usa tests/simular_twillo.py.
"""

import argparse
import asyncio
import base64
import json

import websockets


async def probar_stream(url: str, segundos: int) -> None:
    # 160 bytes mu-law = 20 ms a 8 kHz. 0xFF es silencio en esta codificación.
    silencio = base64.b64encode(bytes([0xFF] * 160)).decode()

    async with websockets.connect(f"{url.rstrip('/')}/ws/twilio") as ws:
        await ws.send(json.dumps({"event": "start", "streamSid": "TEST123"}))
        for _ in range(segundos * 50):
            await ws.send(json.dumps({"event": "media", "media": {"payload": silencio}}))
            await asyncio.sleep(0.02)  # ritmo real
        await ws.send(json.dumps({"event": "stop"}))
    print(f"Listo: se enviaron {segundos} s de silencio a {url}/ws/twilio")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Prueba manual del stream de Twilio")
    parser.add_argument("--url", default="ws://localhost:8000", help="Base ws:// del backend")
    parser.add_argument("--segundos", type=int, default=6, help="Segundos de silencio a enviar")
    args = parser.parse_args()
    asyncio.run(probar_stream(args.url, args.segundos))