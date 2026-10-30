"""
Simulador de Twilio Media Streams + app Android para probar VishGuard SIN Twilio.

Hace lo mismo que harían Twilio y la app, con LOS DOS lados de la conversación:
  1. La "app" se conecta a  /ws/stream?numero=<numero>  y escucha alertas.
  2. "Twilio" se conecta a  /ws/twilio  y envía los eventos reales de Media
     Streams con both_tracks: connected -> start (con customParameters to/from)
     -> media (20 ms por frame, mu-law 8 kHz en base64, con `track` y
     `timestamp`) -> stop.
         pista "inbound"  = el llamante  (tono de 440 Hz)
         pista "outbound" = el receptor  (tono de 880 Hz), que contesta tras
                            --receptor-despues segundos
  3. Muestra cada mensaje que recibe la "app" con su hablante, y termina con
     código 0 si llegaron mensajes de AMBOS hablantes, o 1 si no.

Uso (con el backend corriendo en el puerto 8000):
    pip install websockets
    python tests/simular_twilio.py --numero +50257008032
    python tests/simular_twilio.py --numero +50257008032 --segundos 10 --receptor-despues 2
    python tests/simular_twilio.py --numero +50257008032 --url wss://xxxx.ngrok-free.app
    python tests/simular_twilio.py --numero +50257008032 --prefijo /api/v1 --token <JWT>
    python tests/simular_twilio.py --numero +50257008032 --solo-llamante   (una sola pista)

Con VISHGUARD_GUARDAR_WAV=1 en el backend, el WAV resultante es estéreo: el
canal izquierdo suena a 440 Hz desde el segundo 0 y el derecho a 880 Hz desde el
segundo --receptor-despues.

Notas:
  * Con VISHGUARD_STT=simulado el backend responde con un texto fijo cada 3 s por
    hablante (y NO guarda en la base de datos). Con VISHGUARD_STT=groq los tonos
    no son voz: para probar Groq usa una llamada real.
  * Con --silencio se envía silencio en lugar de tonos.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import math
import struct
import sys
from urllib.parse import quote

try:
    import websockets
except ImportError:  # pragma: no cover
    sys.exit("Falta la librería: pip install websockets")

try:
    import audioop  # Python <= 3.12; en 3.13+: pip install audioop-lts
except ImportError:  # pragma: no cover
    audioop = None

STREAM_SID = "MZ_SIMULADO"
CALL_SID = "CA_SIMULADO"
MUESTRAS_POR_FRAME = 160        # 20 ms a 8 kHz
FRAMES_POR_SEGUNDO = 50
TONO_LLAMANTE_HZ = 440
TONO_RECEPTOR_HZ = 880


def frame_mulaw(frecuencia_hz: float, indice: int, silencio: bool) -> bytes:
    """160 bytes mu-law: un tono continuo (la fase sigue entre frames) o silencio."""
    if silencio or audioop is None:
        return bytes([0xFF] * MUESTRAS_POR_FRAME)
    base = indice * MUESTRAS_POR_FRAME
    pcm = struct.pack(
        f"<{MUESTRAS_POR_FRAME}h",
        *(
            int(12000 * math.sin(2 * math.pi * frecuencia_hz * (base + n) / 8000))
            for n in range(MUESTRAS_POR_FRAME)
        ),
    )
    return audioop.lin2ulaw(pcm, 2)


def evento_media(pista: str, ts_ms: int, audio: bytes) -> str:
    return json.dumps(
        {
            "event": "media",
            "streamSid": STREAM_SID,
            "media": {
                "track": pista,
                "timestamp": str(ts_ms),
                "payload": base64.b64encode(audio).decode(),
            },
        }
    )


async def escuchar_app(url: str, mensajes: list, lista: asyncio.Event) -> None:
    """Simula la app Android: recibe lo que el backend le envía."""
    async with websockets.connect(url) as ws:
        print("[APP]    conectada a /ws/stream")
        lista.set()
        try:
            async for mensaje in ws:
                if mensaje == "pong":
                    continue
                try:
                    data = json.loads(mensaje)
                except json.JSONDecodeError:
                    print(f"[APP]    mensaje: {mensaje}")
                    continue
                mensajes.append(data)
                inicio = data.get("inicio_ms")
                cuando = f"{inicio / 1000:.1f} s" if isinstance(inicio, (int, float)) else "?"
                print(
                    f"[APP]    #{len(mensajes)} {str(data.get('hablante', '?')).upper():9} @ {cuando:>6} "
                    f"nivel={data.get('nivel_riesgo')} score={data.get('score')}"
                )
        except websockets.ConnectionClosed:
            pass


async def simular_twilio(url: str, args: argparse.Namespace) -> None:
    """Simula a Twilio enviando el audio de los dos lados de una llamada."""
    async with websockets.connect(url) as ws:
        print("[TWILIO] conectado a /ws/twilio")
        await ws.send(json.dumps({"event": "connected", "protocol": "Call", "version": "1.0.0"}))
        pistas = ["inbound"] if args.solo_llamante else ["inbound", "outbound"]
        await ws.send(
            json.dumps(
                {
                    "event": "start",
                    "streamSid": STREAM_SID,
                    "start": {
                        "streamSid": STREAM_SID,
                        "callSid": CALL_SID,
                        "tracks": pistas,
                        "customParameters": {"to": args.numero, "from": args.llamante},
                        "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000},
                    },
                }
            )
        )
        print(
            f"[TWILIO] start enviado (llamante={args.llamante}, receptor={args.numero}); "
            f"{args.segundos} s de llamada, el receptor contesta a los {args.receptor_despues} s"
        )
        total = args.segundos * FRAMES_POR_SEGUNDO
        contesta = int(args.receptor_despues * FRAMES_POR_SEGUNDO)
        for i in range(total):
            ts = i * 20
            await ws.send(evento_media("inbound", ts, frame_mulaw(TONO_LLAMANTE_HZ, i, args.silencio)))
            if not args.solo_llamante and i >= contesta:
                await ws.send(
                    evento_media("outbound", ts, frame_mulaw(TONO_RECEPTOR_HZ, i - contesta, args.silencio))
                )
            await asyncio.sleep(1 / FRAMES_POR_SEGUNDO)  # ritmo real: 20 ms por paso
        await ws.send(json.dumps({"event": "stop", "streamSid": STREAM_SID}))
        print("[TWILIO] stop enviado")
        try:
            await asyncio.wait_for(ws.wait_closed(), timeout=10)
        except asyncio.TimeoutError:
            pass


async def main(args: argparse.Namespace) -> int:
    if audioop is None and not args.silencio:
        print("[AVISO]  falta audioop (pip install audioop-lts): se enviará silencio")
    base = args.url.rstrip("/") + args.prefijo.rstrip("/")
    consulta = f"?numero={quote(args.numero)}" + (f"&token={quote(args.token)}" if args.token else "")
    mensajes: list = []
    lista = asyncio.Event()

    tarea_app = asyncio.create_task(escuchar_app(f"{base}/ws/stream{consulta}", mensajes, lista))
    try:
        await asyncio.wait_for(lista.wait(), timeout=10)
    except asyncio.TimeoutError:
        tarea_app.cancel()
        print("[ERROR]  la app no pudo conectarse a /ws/stream (¿backend corriendo? ¿token/prefijo?)")
        return 1
    if tarea_app.done() and tarea_app.exception():
        print(f"[ERROR]  {tarea_app.exception()}")
        return 1

    await simular_twilio(f"{base}/ws/twilio", args)
    await asyncio.sleep(args.espera)  # margen para análisis pendientes
    tarea_app.cancel()

    por_hablante: dict = {}
    for m in mensajes:
        por_hablante[m.get("hablante", "?")] = por_hablante.get(m.get("hablante", "?"), 0) + 1
    print()
    print("RESUMEN:", por_hablante or "sin mensajes")
    esperados = {"llamante"} if args.solo_llamante else {"llamante", "receptor"}
    if esperados <= set(por_hablante):
        print("RESULTADO: OK, la app recibió mensajes de " + " y ".join(sorted(esperados)) + ".")
        return 0
    print(
        "RESULTADO: faltan mensajes de "
        + ", ".join(sorted(esperados - set(por_hablante)))
        + ". Revisa: que el backend tenga both_tracks, VISHGUARD_STT (en 'groq' los tonos "
        "no se transcriben), que el número coincida y /debug/connections."
    )
    return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Simula Twilio Media Streams (ambos lados) y la app Android")
    parser.add_argument("--numero", required=True, help="Número del receptor / de la app, ej. +50257008032")
    parser.add_argument("--llamante", default="+50255551234", help="Número de quien llama")
    parser.add_argument("--url", default="ws://127.0.0.1:8000", help="Base ws:// o wss:// del backend")
    parser.add_argument("--segundos", type=int, default=8, help="Duración de la llamada simulada (mín. 3)")
    parser.add_argument("--receptor-despues", type=float, default=1.0, dest="receptor_despues",
                        help="Segundos hasta que el receptor contesta y empieza a hablar")
    parser.add_argument("--solo-llamante", action="store_true", help="Envía solo la pista inbound")
    parser.add_argument("--silencio", action="store_true", help="Envía silencio en lugar de tonos")
    parser.add_argument("--prefijo", default="", help="Prefijo de rutas, ej. /api/v1")
    parser.add_argument("--token", default=None, help="JWT si WS_AUTH_REQUIRED=true")
    parser.add_argument("--espera", type=float, default=2.0, help="Segundos extra para recibir mensajes")
    try:
        sys.exit(asyncio.run(main(parser.parse_args())))
    except KeyboardInterrupt:
        sys.exit(130)