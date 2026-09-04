import requests

# URL de tu backend HTTP local
URL = "http://localhost:8000/analizar-llamada"

print("="*60)
print("📞 SIMULADOR DE TRANSCRIPCIÓN DE LLAMADA - VISHGUARD AI")
print("="*60)

texto_transcrito = input("\n✍️ Escribe el texto transcrito de la llamada: ")

if texto_transcrito.strip():
    print("\n🔄 Enviando al servidor para análisis de IA...")
    try:
        # Enviar petición de una sola vía
        response = requests.post(URL, json={"texto": texto_transcrito})
        
        if response.status_code == 200:
            data = response.json()
            print("\n" + "="*40)
            print("📊 RESULTADO DEL ANÁLISIS")
            print("="*40)
            print(f"🚨 Nivel de Riesgo : {data.get('nivel_riesgo')}")
            print(f"📈 Score de Amenaza: {data.get('score')}%")
            print(f"💡 Recomendación   : {data.get('recomendacion')}")
            print("="*40)
            print("✅ Petición completada y conexión cerrada exitosamente.\n")
        else:
            print(f"⚠️ Error en la respuesta del servidor: status {response.status_code}")
    except Exception as e:
        print(f"❌ Error de conexión: {e}")
else:
    print("⚠️ No ingresaste texto.")