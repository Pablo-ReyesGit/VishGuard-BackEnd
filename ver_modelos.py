import os
import requests
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("GROQ_API_KEY")

if not api_key:
    print("❌ No se encontró GROQ_API_KEY en el archivo .env")
else:
    url = "https://api.groq.com/openai/v1/models"
    headers = {"Authorization": f"Bearer {api_key}"}
    
    try:
        response = requests.get(url, headers=headers)
        data = response.json()
        
        if "data" in data:
            print("\n✅ MODELOS DISPONIBLES EN TU CUENTA DE GROQ:\n")
            for model in data["data"]:
                print(f" - {model['id']}")
            print("\n")
        else:
            print(f"❌ Error devuelto por la API: {data}")
    except Exception as e:
        print(f"❌ Error al conectar: {e}")