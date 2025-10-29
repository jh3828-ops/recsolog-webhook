from flask import Flask, request, jsonify
import os

# ========================================
# ✅ CONFIGURACIÓN BASE DEL WEBHOOK
# ========================================
app = Flask(__name__)

# Meta / WhatsApp Cloud API token y clave de verificación
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "recsolog123")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")

# Puerto (Render requiere 0.0.0.0 y un puerto dinámico)
PORT = int(os.environ.get("PORT", 10000))


# ========================================
# ✅ ENDPOINT PARA VERIFICACIÓN (GET)
# ========================================
@app.route("/webhook", methods=["GET"])
def verify_webhook():
    """
    Facebook llama este endpoint para verificar el token del webhook.
    Render debe responder con el 'hub.challenge' si el token es válido.
    """
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode and token:
        if mode == "subscribe" and token == VERIFY_TOKEN:
            print("🟢 Webhook verificado correctamente con Meta.")
            return challenge, 200
        else:
            print("🔴 Error: token de verificación incorrecto.")
            return "Error: token inválido", 403
    return "Error: parámetros faltantes", 400


# ========================================
# ✅ ENDPOINT PARA RECIBIR MENSAJES (POST)
# ========================================
@app.route("/webhook", methods=["POST"])
def receive_message():
    """
    Este endpoint recibe los mensajes o notificaciones
    que envía WhatsApp Cloud API a tu webhook.
    """
    data = request.get_json()
    print("📩 Webhook recibido:")
    print(data)

    # Confirmar recepción a Meta (importante)
    return jsonify({"status": "received"}), 200


# ========================================
# ✅ ENDPOINT PRINCIPAL DE PRUEBA
# ========================================
@app.route("/", methods=["GET"])
def home():
    return "✅ Webhook Recsolog activo y escuchando.", 200


# ========================================
# 🚀 INICIO DEL SERVIDOR FLASK
# ========================================
if __name__ == "__main__":
    print(f"🚀 Iniciando webhook en puerto {PORT} (Render)...")
    app.run(host="0.0.0.0", port=PORT)
