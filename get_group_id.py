import os
import requests
from dotenv import load_dotenv

# Cargar credenciales desde .env
load_dotenv()
token = os.getenv("WHATSAPP_TOKEN")
phone_id = os.getenv("WHATSAPP_PHONE_ID")

if not token or not phone_id:
    print("❌ Faltan variables en el archivo .env (WHATSAPP_TOKEN o WHATSAPP_PHONE_ID)")
    exit()

# Endpoint de mensajes recientes
url = f"https://graph.facebook.com/v17.0/{phone_id}/messages?limit=10"

headers = {
    "Authorization": f"Bearer {token}"
}

print("📨 Consultando los últimos mensajes recibidos en tu cuenta de WhatsApp Cloud...")

try:
    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        data = response.json()
        messages = data.get("data", [])
        if not messages:
            print("⚠️ No se encontraron mensajes recientes. Envia un mensaje desde tu grupo al número de WhatsApp Cloud y vuelve a intentarlo.")
        else:
            print("\n✅ Mensajes encontrados:")
            for msg in messages:
                if "@g.us" in str(msg):
                    print("\n📌 Posible grupo detectado:")
                    print(msg)
            print("\n🔎 Busca líneas con '@g.us' — ese es tu Group ID.")
    else:
        print(f"❌ Error en la consulta ({response.status_code}): {response.text}")

except Exception as e:
    print(f"❌ Error inesperado: {e}")
