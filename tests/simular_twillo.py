"""
Simulador de Twilio Media Streams + app Android para probar VishGuard SIN Twilio.

Hace lo mismo que harían Twilio y la app:
  1. La "app" se conecta a  /ws/stream?numero=<numero>  y escucha alertas.
  2. "Twilio" se conecta a  /ws/twilio  y envía los eventos reales de Media
     Streams: connected -> start (con customParameters.to) -> media (20 ms por
     frame, mu-law 8 kHz en base64) -> stop.
  3. Muestra las alertas que recibe la "app" y termina con código 0 si llegó
     al menos una, o 1 si no llegó ninguna.

Uso (con el backend corriendo en el puerto 8000):
    pip install websockets
    python tests/simular_twilio.py --numero +50257008032
    python tests/simular_twilio.py --numero +50257008032 --segundos 10
    python tests/simular_twilio.py --numero +50257008032 --url wss://xxxx.ngrok-free.app
    python tests/simular_twilio.py --numero +50257008032 --prefijo /api/v1 --token <JWT>

Notas:
  * Con VISHGUARD_STT=simulado el backend responde con un texto fijo cada 3 s
    (y NO guarda en la base de datos). Con VISHGUARD_STT=groq transcribe el
    audio: este simulador envía silencio, que se descarta (no hay voz que
    transcribir), así que para probar Groq usa una llamada real.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import sys
from urllib.parse import quote

try:
    import websockets
except ImportError:  # pragma: no cover
    sys.exit("Falta la librería: pip install websockets")

STREAM_SID = "MZ_SIMULADO"
CALL_SID = "CA_SIMULADO"
FRAME_MULAW_BYTES = 160       # 20 ms a 8 kHz
FRAMES_POR_SEGUNDO = 50


def evento_media() -> str:
    payload = base64.b64encode(bytes([0xFF] * FRAME_MULAW_BYTES)).decode()  # silencio mu-law
    return json.dumps(
        {"event": "media", "streamSid": STREAM_SID, "media": {"payload": payload}}
    )


async def escuchar_app(url: str, alertas: list, lista: asyncio.Event) -> None:
    """Simula la app Android: recibe lo que el backend le envía."""
    async with websockets.connect(url) as ws:
        print("[APP]    conectada a /ws/stream")
        lista.set()
        try:
            async for mensaje in ws:
                if mensaje == "pong":
                    continue
                alertas.append(mensaje)
                try:
                    data = json.loads(mensaje)
                    print(
                        f"[APP]    ALERTA #{len(alertas)}: nivel={data.get('nivel_riesgo')} "
                        f"score={data.get('score')} recomendacion={data.get('recomendacion')!r}"
                    )
                except json.JSONDecodeError:
                    print(f"[APP]    mensaje: {mensaje}")
        except websockets.ConnectionClosed:
            pass


async def simular_twilio(url: str, numero: str, segundos: int) -> None:
    """Simula a Twilio enviando el audio de una llamada."""
    async with websockets.connect(url) as ws:
        print("[TWILIO] conectado a /ws/twilio")
        await ws.send(json.dumps({"event": "connected", "protocol": "Call", "version": "1.0.0"}))
        await ws.send(
            json.dumps(
                {
                    "event": "start",
                    "streamSid": STREAM_SID,
                    "start": {
                        "streamSid": STREAM_SID,
                        "callSid": CALL_SID,
                        "customParameters": {"to": numero},
                        "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000},
                    },
                }
            )
        )
        print(f"[TWILIO] start enviado (to={numero}); enviando {segundos} s de audio...")
        for _ in range(segundos * FRAMES_POR_SEGUNDO):
            await ws.send(evento_media())
            await asyncio.sleep(1 / FRAMES_POR_SEGUNDO)  # ritmo real: 20 ms por frame
        await ws.send(json.dumps({"event": "stop", "streamSid": STREAM_SID}))
        print("[TWILIO] stop enviado")
        try:
            await asyncio.wait_for(ws.wait_closed(), timeout=10)
        except asyncio.TimeoutError:
            pass


async def main(args: argparse.Namespace) -> int:
    base = args.url.rstrip("/") + args.prefijo.rstrip("/")
    consulta = f"?numero={quote(args.numero)}" + (f"&token={quote(args.token)}" if args.token else "")
    alertas: list = []
    lista = asyncio.Event()

    tarea_app = asyncio.create_task(escuchar_app(f"{base}/ws/stream{consulta}", alertas, lista))
    try:
        await asyncio.wait_for(lista.wait(), timeout=10)
    except asyncio.TimeoutError:
        tarea_app.cancel()
        print("[ERROR]  la app no pudo conectarse a /ws/stream (¿backend corriendo? ¿token/prefijo?)")
        return 1
    if tarea_app.done() and tarea_app.exception():
        print(f"[ERROR]  {tarea_app.exception()}")
        return 1

    await simular_twilio(f"{base}/ws/twilio", args.numero, args.segundos)
    await asyncio.sleep(args.espera)  # margen para análisis pendientes
    tarea_app.cancel()

    print()
    if alertas:
        print(f"RESULTADO: OK, la app recibió {len(alertas)} alerta(s).")
        return 0
    print(
        "RESULTADO: la app NO recibió alertas. Revisa: VISHGUARD_STT (en 'groq' el silencio "
        "se descarta), que el número coincida y /debug/connections."
    )
    return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Simula Twilio Media Streams y la app Android")
    parser.add_argument("--numero", required=True, help="Número de la app, ej. +50257008032")
    parser.add_argument("--url", default="ws://127.0.0.1:8000", help="Base ws:// o wss:// del backend")
    parser.add_argument("--segundos", type=int, default=7, help="Segundos de audio a enviar (mín. 3)")
    parser.add_argument("--prefijo", default="", help="Prefijo de rutas, ej. /api/v1")
    parser.add_argument("--token", default=None, help="JWT si WS_AUTH_REQUIRED=true")
    parser.add_argument("--espera", type=float, default=2.0, help="Segundos extra para recibir alertas")
    try:
        sys.exit(asyncio.run(main(parser.parse_args())))
    except KeyboardInterrupt:
        sys.exit(130)