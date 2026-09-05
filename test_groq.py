import os
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

try:
    models_page = client.models.list()
    print("=== MODELOS DISPONIBLES EN TU CUENTA ===")
    for model in models_page.data:
        print(f"-> {model.id}")
except Exception as e:
    print(f"Error consultando modelos: {e}")