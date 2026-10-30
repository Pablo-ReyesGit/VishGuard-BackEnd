"""Prueba MANUAL del stream de Twilio.
Uso:
    uvicorn main:app --port 8000
    python scripts/probar_stream_manual.py
"""
import argparse
import asyncio
import base64
import json
import websockets

async def probar_stream(url: str, segundos: int) -> None:
    silencio = base64.b64encode(bytes([0xFF] * 160)).decode()
    async with websockets.connect(f"{url.rstrip('/')}/ws/twilio") as ws:
        await ws.send(json.dumps({"event": "start", "streamSid": "TEST123"}))
        for _ in range(segundos * 50):
            await ws.send(json.dumps({"event": "media", "media": {"payload": silencio}}))
            await asyncio.sleep(0.02)
        await ws.send(json.dumps({"event": "stop"}))
    print(f"Listo: se enviaron {segundos} s de silencio a {url}/ws/twilio")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Prueba manual del stream de Twilio")
    parser.add_argument("--url", default="ws://localhost:8000", help="Base ws:// del backend")
    parser.add_argument("--segundos", type=int, default=6, help="Segundos de silencio a enviar")
    args = parser.parse_args()
    asyncio.run(probar_stream(args.url, args.segundos))
