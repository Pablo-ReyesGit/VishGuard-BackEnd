"""Simulador de Twilio Media Streams + app Android para probar VishGuard.
Uso:
    python scripts/simular_twillo.py --numero +50257008032
"""
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
except ImportError:
    sys.exit("Falta la librería: pip install websockets")

STREAM_SID = "MZ_SIMULADO"
CALL_SID = "CA_SIMULADO"

async def main():
    print("Simulador de Twilio Media Streams listo.")

if __name__ == "__main__":
    asyncio.run(main())
