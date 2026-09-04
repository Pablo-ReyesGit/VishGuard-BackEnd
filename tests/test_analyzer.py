import sys
import os
import json

# Agregar la ruta raiz para importar modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from modules.analyzer import VishingAnalyzer

def ejecutar_pruebas():
    analyzer = VishingAnalyzer()

    casos_de_prueba = [
        {
            "id": "TC-01 (Legitimo)",
            "texto": "Hola buenas tardes, le llamamos de la clinica medica para confirmarle su cita de manana a las 10 AM con el doctor Morales."
        },
        {
            "id": "TC-02 (Urgencia / Sospecha)",
            "texto": "Estimado cliente, detectamos una transferencia sospechosa desde su cuenta de ahorro. Debe ingresar a la banca en linea de inmediato para cancelar la transaccion."
        },
        {
            "id": "TC-03 (Fraude Critico / Vishing)",
            "texto": "Le habla el ingeniero de seguridad del banco. Para detener el bloqueo de su tarjeta en este momento, necesito que me dicte el codigo SMS de 6 digitos que le acaba de llegar a su telefono."
        }
    ]

    print("==================================================")
    print(" 🛡️ PRUEBA DEL MODULO ANALIZADOR VISHGUARD AI")
    print("==================================================\n")

    for caso in casos_de_prueba:
<<<<<<< HEAD
        print(f"📌 Probando: {caso['id']}")
        print(f"💬 Texto: \"{caso['texto']}\"")
        
        resultado = analyzer.analizar_texto(caso['texto'])
        
        print("🤖 Respuesta JSON devuelta por Gemini Flash:")
=======
        print(f" Probando: {caso['id']}")
        print(f" Texto: \"{caso['texto']}\"")
        
        resultado = analyzer.analizar_texto(caso['texto'])
        
        print(" Respuesta JSON devuelta por Gemini Flash:")
>>>>>>> main
        print(json.dumps(resultado, indent=4, ensure_ascii=False))
        print("-" * 50 + "\n")

if __name__ == "__main__":
    ejecutar_pruebas()