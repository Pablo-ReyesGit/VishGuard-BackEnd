import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from modules.stt import SpeechToText
from modules.analyzer import VishingAnalyzer

def probar_pipeline_completo():
    print("==================================================")
    print("  (VISHGUARD AI)")
    print("==================================================\n")

    # 1. Inicializar Módulos
    stt = SpeechToText(model_size="tiny", device="cpu")
    analyzer = VishingAnalyzer()

    # 2. Simulación de entrada de texto transcrita directamente
    # (Para validar la tubería completa mientras probamos archivos .wav)
    audio_simulado = "Estimado cliente, su cuenta bancaria ha sido bloqueada. Por favor dicte el código de confirmación que le enviamos por SMS."
    
    print(f"Entrada de Audio (Simulado/Transcrito): \"{audio_simulado}\"\n")
    
    # 3. Analizar con Gemini Flash
    print("🔍 Analizando intención con Gemini Flash...")
    resultado = analyzer.analizar_texto(audio_simulado)

    # 4. Resultados visuales de alerta
    print("\n RESULTADO DE LA EVALUACIÓN:")
    print(f"• Nivel de Riesgo : {resultado['nivel_riesgo']}")
    print(f"• Probabilidad    : {resultado['score']}%")
    print(f"• Patrones        : {', '.join(resultado['patrones_detectados'])}")
    print(f"• Frase Crítica   : \"{resultado['frase_critica']}\"")
    print(f"• Recomendación   : {resultado['recomendacion']}")

if __name__ == "__main__":
    probar_pipeline_completo()