from flask import Flask, request, jsonify
import os

app = Flask(__name__)

VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "recsolog123")
PORT = int(os.environ.get("PORT", 10000))


@app.route("/", methods=["GET"])
def home():
    return "✅ Webhook Recsolog activo y escuchando.", 200


@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode and token:
        if mode == "subscribe" and token == VERIFY_TOKEN:
            print("🟢 Webhook verificado correctamente con Meta.")
            return challenge, 200
        else:
            print("🔴 Token de verificación incorrecto.")
            return "Error: token inválido", 403
    return "Error: parámetros faltantes", 400


@app.route("/webhook", methods=["POST"])
def receive_message():
    data = request.get_json()
    print("📩 Webhook recibido:", data)
    return jsonify({"status": "received"}), 200


if __name__ == "__main__":
    print(f"🚀 Iniciando webhook en puerto {PORT} (Render)...")
    app.run(host="0.0.0.0", port=PORT)
