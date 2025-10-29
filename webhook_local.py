from flask import Flask, request, jsonify
import os

app = Flask(__name__)

@app.route("/", methods=["GET"])
def home():
    return "✅ Webhook Recsolog activo y escuchando correctamente.", 200


@app.route("/webhook", methods=["GET"])
def verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    verify_token = os.getenv("WHATSAPP_VERIFY_TOKEN", "recsolog123")

    if mode and token:
        if mode == "subscribe" and token == verify_token:
            return challenge, 200
        else:
            return "Token inválido", 403
    return "Parámetros faltantes", 400


@app.route("/webhook", methods=["POST"])
def receive():
    data = request.get_json()
    print("📩 Webhook recibido:", data)
    return jsonify({"status": "received"}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
