import asyncio, websockets, json, base64

async def test_twilio_stream():
    uri = "ws://localhost:8000/ws/twilio"
    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps({"event": "start", "streamSid": "TEST123"}))

        # Silencio mu-law falso (0xFF ~ silencio en esta codificación)
        silencio = base64.b64encode(bytes([0xFF] * 800)).decode()

        for _ in range(60):  # ~6 segundos acumulados -> debería disparar el análisis 2 veces
            await ws.send(json.dumps({"event": "media", "media": {"payload": silencio}}))
            await asyncio.sleep(0.02)

        await ws.send(json.dumps({"event": "stop"}))

asyncio.run(test_twilio_stream())