"""Prueba offline de Whisper con una grabación de VishGuard.

Transcribe cada pista del WAV (izquierdo = llamante, derecho = receptor) EMULANDO lo que
hace la canalización real: bloques de CHUNK_SEG segundos con SOLAPE_SEG de solape. Imprime
el texto de cada bloque y cuánto tardó, para decidir modelo y tamaño de bloque.

Ejecútalo desde la raíz del backend (donde está la carpeta `modules`):

    python probar_wav.py grabaciones\\CAxxxx.wav tiny base small
    python probar_wav.py grabaciones\\CAxxxx.wav small medium --chunk 5 --solape 1

Regla práctica: si "x del tiempo real" por bloque supera ~0.4 con dos pistas, el modelo
no sostiene la llamada en vivo con este hardware (baja de modelo, usa GPU o Groq).
"""

import argparse
import audioop
import os
import sys
import time
import wave

import numpy as np

sys.path.insert(0, os.getcwd())
from modules.stt import SpeechToText  # noqa: E402

SR = 8000
UMBRAL_SILENCIO_RMS = 150


def cargar_pistas(ruta: str) -> dict[str, np.ndarray]:
    with wave.open(ruta, "rb") as w:
        if w.getframerate() != SR or w.getsampwidth() != 2:
            sys.exit(f"Se esperaba PCM16 a 8 kHz; el archivo es {w.getframerate()} Hz / {w.getsampwidth()*8} bit")
        canales = w.getnchannels()
        datos = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    if canales == 2:
        return {"llamante": datos[0::2], "receptor": datos[1::2]}
    return {"mono": datos}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("wav")
    ap.add_argument("modelos", nargs="*", default=["small"])
    ap.add_argument("--chunk", type=float, default=5.0, help="segundos por bloque")
    ap.add_argument("--solape", type=float, default=1.0, help="segundos de solape con el bloque anterior")
    args = ap.parse_args()

    pistas = cargar_pistas(args.wav)
    paso = int(args.chunk * SR)
    solape = int(args.solape * SR)

    for modelo in args.modelos:
        print(f"\n================ modelo: {modelo} ================")
        stt = SpeechToText(model_size=modelo)
        for nombre, x in pistas.items():
            print(f"\n--- pista: {nombre} ---")
            total_t, total_a = 0.0, 0.0
            for pos in range(0, len(x), paso):
                ini = max(0, pos - solape)
                bloque = x[ini : pos + paso].tobytes()
                if audioop.rms(bloque, 2) < UMBRAL_SILENCIO_RMS:
                    continue
                t0 = time.perf_counter()
                texto = stt.transcribir_pcm(bloque)
                dt = time.perf_counter() - t0
                dur = len(bloque) / (SR * 2)
                total_t += dt
                total_a += dur
                print(f"[{ini / SR:5.1f} s] ({dt:4.1f} s p/ {dur:.1f} s) {texto or '(vacío)'}")
            if total_a:
                print(f"=> {total_t:.1f} s de proceso para {total_a:.1f} s de audio (x{total_t / total_a:.2f})")


if __name__ == "__main__":
    main()