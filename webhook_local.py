from flask import Flask, request, jsonify
import os

app = Flask(__name__)

print("🚀 Iniciando archivo webhook_local.py en Render...")

@app.route("/", methods=["GET"])
def home():
    return "✅ Webhook Recsolog activo y escuchando correctamente.", 200



# ✅ Ruta GET para verificación de Webhook con Meta (Facebook)
@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    verify_token = os.getenv("WHATSAPP_VERIFY_TOKEN", "recsolog123")

    if mode and token:
        if mode == "subscribe" and token == verify_token:
            print("🟢 Verificación de webhook exitosa.")
            return challenge, 200
        else:
            print("🔴 Token de verificación inválido.")
            return "Token de verificación inválido", 403
    return "Solicitud inválida", 400


# ✅ Ruta POST para recibir mensajes desde WhatsApp Cloud API
@app.route("/webhook", methods=["POST"])
def receive_webhook():
    try:
        data = request.get_json()
        print("📩 Webhook recibido:", data)
        return jsonify({"status": "received"}), 200
    except Exception as e:
        print("⚠️ Error procesando webhook:", e)
        return jsonify({"error": str(e)}), 500


# 🔧 Puerto dinámico para Render
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)