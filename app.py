import os
import time
import sqlite3
import requests
import pandas as pd
import csv
import io
from flask import Flask, render_template, send_file
from datetime import datetime, timedelta
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from threading import Thread
from flask import request
from flask import jsonify


def init_local_db():
    conn = sqlite3.connect("local_data.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pedidos (
            pedido TEXT PRIMARY KEY,
            fecha_solicitada TEXT,
            hora_limite TEXT,
            fecha_entregada TEXT,
            cumplimiento TEXT
        )
    """)
    conn.commit()
    conn.close()

# Inicializa al inicio
init_local_db()


# ------------------------------------------------------
# CONFIGURACIÓN DE FLASK
# ------------------------------------------------------
app = Flask(__name__)

# ------------------------------------------------------
# VARIABLES DE ENTORNO (.env)
# ------------------------------------------------------
load_dotenv()

# WhatsApp Cloud API
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID")
WHATSAPP_DESTINATARIO = os.getenv("WHATSAPP_DESTINATARIO")

# SQL Server
SQL_SERVER = os.getenv("SQL_SERVER", "204.232.237.135")
SQL_DB = os.getenv("SQL_DB", "Recsolog_wms")
SQL_USER = os.getenv("SQL_USER", "recsolog")
SQL_PASS = os.getenv("SQL_PASS", "8_HaZ!2Z")

# ------------------------------------------------------
# CONEXIÓN A SQL SERVER (OPTIMIZADA CON POOLING)
# ------------------------------------------------------
def crear_engine_sqlserver():
    try:
        connection_string = (
            f"mssql+pyodbc://{SQL_USER}:{SQL_PASS}@{SQL_SERVER}/{SQL_DB}"
            "?driver=ODBC+Driver+18+for+SQL+Server"
            "&Encrypt=no"
        )
        engine = create_engine(connection_string, pool_size=5, max_overflow=10, pool_recycle=1800)
        print("✅ Conectado correctamente a SQL Server.")
        return engine
    except Exception as e:
        print(f"❌ Error al conectar a SQL Server: {e}")
        return None

engine = crear_engine_sqlserver()

# ------------------------------------------------------
# BASE LOCAL SQLITE (registra notificaciones y evita duplicados)
# ------------------------------------------------------
LOCAL_DB = "pedidos_local.db"

def init_local_db():
    """Crea o actualiza la tabla local 'pedidos_local' para asegurar columnas correctas."""
    conn = sqlite3.connect(LOCAL_DB)
    cur = conn.cursor()

    # Crear la tabla si no existe
    cur.execute("""
        CREATE TABLE IF NOT EXISTS pedidos_local (
            folio TEXT PRIMARY KEY,
            fecha_solicitada TEXT,
            hora_limite TEXT,
            fecha_entregada TEXT,
            cumplimiento TEXT,
            fecha_envio TEXT
        )
    """)

    # Asegurar que todas las columnas existan (por si la tabla es antigua)
    columnas_necesarias = {
        "hora_limite": "ALTER TABLE pedidos_local ADD COLUMN hora_limite TEXT",
        "fecha_entregada": "ALTER TABLE pedidos_local ADD COLUMN fecha_entregada TEXT",
        "cumplimiento": "ALTER TABLE pedidos_local ADD COLUMN cumplimiento TEXT",
        "fecha_envio": "ALTER TABLE pedidos_local ADD COLUMN fecha_envio TEXT"
    }

    # Obtener columnas existentes
    cur.execute("PRAGMA table_info(pedidos_local)")
    existentes = [col[1] for col in cur.fetchall()]

    # Agregar las faltantes
    for col, sql in columnas_necesarias.items():
        if col not in existentes:
            print(f"🛠️ Añadiendo columna faltante '{col}' a pedidos_local")
            cur.execute(sql)

    conn.commit()
    conn.close()


# ------------------------------------------------------
# FUNCIONES AUXILIARES SQLITE
# ------------------------------------------------------
def pedido_ya_enviado_hoy(folio):
    """Verifica si el pedido ya fue notificado hoy."""
    conn = sqlite3.connect(LOCAL_DB)
    cur = conn.cursor()
    cur.execute("""
        SELECT fecha_envio FROM pedidos_local
        WHERE folio = ? AND date(fecha_envio) = date('now', 'localtime')
    """, (folio,))
    existe = cur.fetchone() is not None
    conn.close()
    return existe

def registrar_envio(folio):
    """Registra que el pedido fue notificado hoy."""
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(LOCAL_DB)
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO pedidos_local (folio) VALUES (?)", (folio,))
    cur.execute("UPDATE pedidos_local SET fecha_envio = ? WHERE folio = ?", (ahora, folio))
    conn.commit()
    conn.close()

# ------------------------------------------------------
# FUNCIONES DE TIEMPO Y CUMPLIMIENTO
# ------------------------------------------------------
def calcular_hora_limite(fecha_solicitada):
    dt = datetime.strptime(fecha_solicitada, "%Y-%m-%d %H:%M:%S")
    return (dt + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")

def calcular_cumplimiento(hora_limite, fecha_entregada):
    if not fecha_entregada or not hora_limite:
        return "Pendiente"
    dt_lim = datetime.strptime(hora_limite, "%Y-%m-%d %H:%M:%S")
    dt_env = datetime.strptime(fecha_entregada, "%Y-%m-%d %H:%M:%S")
    return "Cumple" if dt_env <= dt_lim else "No Cumple"

# ------------------------------------------------------
# REGISTRO DE LOGS EN CSV (HISTORIAL DE ENVÍOS)
# ------------------------------------------------------
def registrar_log_envio(folio, mensaje, exito=True):
    """Guarda cada mensaje enviado en un CSV."""
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    archivo = "envios_log.csv"
    existe = os.path.exists(archivo)

    with open(archivo, mode="a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not existe:
            writer.writerow(["FechaHora", "Folio", "Mensaje", "Resultado"])
        writer.writerow([
            ahora,
            folio,
            mensaje.replace("\n", " "),
            "✅ Enviado" if exito else "⚠️ Error"
        ])

# ------------------------------------------------------
# FUNCIÓN PARA ENVIAR MENSAJE A WHATSAPP
# ------------------------------------------------------
def enviar_mensaje_whatsapp(mensaje):
    """Envía un mensaje de texto a través de la API de WhatsApp Cloud."""
    url = f"https://graph.facebook.com/v17.0/{WHATSAPP_PHONE_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {
        "messaging_product": "whatsapp",
        "to": WHATSAPP_DESTINATARIO,
        "type": "text",
        "text": {"body": mensaje}
    }

    try:
        res = requests.post(url, json=data, headers=headers)
        if res.status_code == 200:
            print(f"✅ Mensaje enviado a WhatsApp: {mensaje}")
        else:
            print(f"⚠️ Error al enviar mensaje: {res.status_code} - {res.text}")
    except Exception as e:
        print(f"❌ Error en conexión con WhatsApp API: {e}")

# ------------------------------------------------------
# CONSULTA SQL: SOLO PEDIDOS DE HOY Y FACTURABLES
# ------------------------------------------------------
def get_pedidos(fecha_inicio=None, fecha_fin=None):
    """Obtiene pedidos del SQL Server (con IDEstadoEmbarque = 7 y terminaciones F1, F1X, F2) 
    y combina con la base local para mantener las fechas y cumplimiento."""
    try:
        hoy = datetime.now().strftime("%Y-%m-%d")
        fecha_inicio = fecha_inicio or hoy
        fecha_fin = fecha_fin or hoy

        query = text("""
            SELECT 
                d.IDDocumentoSalida AS IDDocumentoSalida,
                d.FechaHoraRegistro AS FechaHoraRegistro
            FROM DOCUMENTOSALIDA d
            INNER JOIN DETALLEEMBARQUE e 
                ON d.IDDocumentoSalida = e.IDEmbarque
            WHERE e.IDEstadoEmbarque = 7
              AND (
                  d.IDDocumentoSalida LIKE '%-F1'
                  OR d.IDDocumentoSalida LIKE '%-F1X'
                  OR d.IDDocumentoSalida LIKE '%-F2'
              )
              AND CONVERT(date, d.FechaHoraRegistro) BETWEEN :inicio AND :fin
            ORDER BY d.FechaHoraRegistro DESC
        """)

        with engine.connect() as conn:
            registros = conn.execute(query, {"inicio": fecha_inicio, "fin": fecha_fin}).fetchall()

        pedidos = []
        for r in registros:
            pedidos.append({
                "pedido": r.IDDocumentoSalida,
                "fecha_solicitada": None,
                "hora_limite": None,
                "fecha_entregada": None,
                "cumplimiento": "Pendiente"
            })

        print(f"✅ {len(pedidos)} pedidos cargados desde SQL Server ({fecha_inicio} a {fecha_fin})")
        return pedidos

    except Exception as e:
        print(f"⚠️ Error al obtener pedidos: {e}")
        return []

# ------------------------------------------------------
# SINCRONIZACIÓN Y NOTIFICACIÓN AUTOMÁTICA
# ------------------------------------------------------
def sincronizar_periodicamente():
    pedidos_previos = set()
    while True:
        try:
            pedidos = get_pedidos()
            actuales = {p["pedido"] for p in pedidos}
            nuevos = actuales - pedidos_previos

            if nuevos:
                enviados_hoy = 0
                for folio in nuevos:
                    if pedido_ya_enviado_hoy(folio):
                        continue

                    registrar_envio(folio)
                    mensaje = (
                        f"📦 Nuevo pedido detectado: *{folio}*\n"
                        f"Por favor imprimir la factura correspondiente."
                    )

                    try:
                        enviar_mensaje_whatsapp(mensaje)
                        registrar_log_envio(folio, mensaje, exito=True)
                    except Exception as e:
                        registrar_log_envio(folio, mensaje, exito=False)
                        print(f"⚠️ Error al enviar mensaje: {e}")

                    enviados_hoy += 1

                if enviados_hoy > 0:
                    print(f"🟢 {enviados_hoy} nuevos pedidos detectados y notificados.")
                else:
                    print("✅ No hay pedidos nuevos que notificar hoy.")
            else:
                print("🔁 Sin cambios detectados en pedidos.")

            pedidos_previos = actuales
        except Exception as e:
            print(f"Error en sincronización: {e}")
        time.sleep(60)

# ------------------------------------------------------
# EXPORTAR REPORTE A EXCEL
# ------------------------------------------------------
from flask import send_file
import io
import pandas as pd

@app.route("/exportar_excel")
def exportar_excel():
    """
    Genera y descarga un archivo Excel con todos los pedidos
    combinando los datos del SQL Server y los registros locales.
    """
    try:
        # 1️⃣ Obtener pedidos desde SQL Server
        pedidos_sql = get_pedidos()

        # 2️⃣ Obtener información local (solicitada, límite, entrega, cumplimiento)
        conn = sqlite3.connect("local_data.db")
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM pedidos")
        pedidos_local = {row["pedido"]: dict(row) for row in cursor.fetchall()}
        conn.close()

        # 3️⃣ Combinar datos
        datos_para_excel = []
        for p in pedidos_sql:
            pedido_id = p["pedido"]
            local = pedidos_local.get(pedido_id, {})
            datos_para_excel.append({
                "Pedido": pedido_id,
                "Fecha Solicitada": local.get("fecha_solicitada", ""),
                "Hora Límite": local.get("hora_limite", ""),
                "Fecha Entregada": local.get("fecha_entregada", ""),
                "Cumplimiento": local.get("cumplimiento", "Pendiente"),
            })

        if not datos_para_excel:
            return "No hay datos para exportar."

        # 4️⃣ Crear el Excel en memoria
        df = pd.DataFrame(datos_para_excel)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
            df.to_excel(writer, index=False, sheet_name="KPI_Facturas")

        output.seek(0)
        fecha_hoy = datetime.now().strftime("%Y%m%d_%H%M%S")

        # 5️⃣ Enviar el archivo para descarga
        return send_file(
            output,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            download_name=f"Reporte_KPI_Facturas_{fecha_hoy}.xlsx",
            as_attachment=True
        )

    except Exception as e:
        print(f"⚠️ Error al exportar a Excel: {e}")
        return "Error al generar el archivo Excel."

def sincronizar_pedidos():
    """
    Sincroniza pedidos desde SQL Server y notifica nuevos pedidos por WhatsApp.
    No borra los datos locales (hora solicitada, entrega, etc.)
    """
    try:
        pedidos_sql = get_pedidos()  # pedidos del SQL Server
        conn = sqlite3.connect("local_data.db")
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pedidos (
                pedido TEXT PRIMARY KEY,
                fecha_solicitada TEXT,
                hora_limite TEXT,
                fecha_entregada TEXT,
                cumplimiento TEXT
            )
        """)

        nuevos = []
        for p in pedidos_sql:
            pedido_id = p["pedido"]

            # Verificar si ya existe localmente
            cursor.execute("SELECT 1 FROM pedidos WHERE pedido = ?", (pedido_id,))
            existe = cursor.fetchone()

            if not existe:
                # Inserta pedido nuevo en la base local
                cursor.execute("""
                    INSERT INTO pedidos (pedido, fecha_solicitada, hora_limite, fecha_entregada, cumplimiento)
                    VALUES (?, NULL, NULL, NULL, 'Pendiente')
                """, (pedido_id,))
                nuevos.append(pedido_id)

        conn.commit()
        conn.close()

        if nuevos:
            print(f"🟢 {len(nuevos)} nuevos pedidos detectados: {nuevos}")
            for pedido in nuevos:
                enviar_mensaje_whatsapp(pedido)
        else:
            print("✅ No hay pedidos nuevos que notificar hoy.")

    except Exception as e:
        print(f"⚠️ Error en sincronización incremental: {e}")

def enviar_mensaje_whatsapp(pedido):
    """Envía un mensaje a WhatsApp cuando se detecta un nuevo pedido."""
    try:
        token = os.getenv("WHATSAPP_TOKEN")
        phone_number_id = os.getenv("WHATSAPP_PHONE_ID")
        to = os.getenv("WHATSAPP_TO")  # tu número autorizado

        url = f"https://graph.facebook.com/v17.0/{phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        data = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {
                "body": f"📦 Nuevo pedido detectado: *{pedido}*\nPor favor imprimir la factura correspondiente."
            }
        }

        response = requests.post(url, headers=headers, json=data)
        if response.status_code == 200:
            print(f"✅ Mensaje enviado a WhatsApp: {pedido}")
        else:
            print(f"⚠️ Error al enviar mensaje: {response.text}")

    except Exception as e:
        print(f"⚠️ Error en envío WhatsApp: {e}")


# ------------------------------------------------------
# RUTAS FLASK BÁSICAS
# ------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html", datetime=datetime)


@app.route("/planner")
def planner_view():
    try:
        fecha_inicio = request.args.get("fecha_inicio")
        fecha_fin = request.args.get("fecha_fin")
        search = request.args.get("search", "")

        # Trae pedidos desde SQL Server
        pedidos_sql = get_pedidos(fecha_inicio, fecha_fin)

        # Trae datos locales
        conn = sqlite3.connect("local_data.db")
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM pedidos")
        pedidos_local = {row["pedido"]: dict(row) for row in cursor.fetchall()}
        conn.close()

        # Combina ambos
        pedidos_finales = []
        for p in pedidos_sql:
            pedido_id = p["pedido"]
            local = pedidos_local.get(pedido_id, {})
            pedidos_finales.append({
                "pedido": pedido_id,
                "fecha_solicitada": local.get("fecha_solicitada"),
                "hora_limite": local.get("hora_limite"),
                "fecha_entregada": local.get("fecha_entregada"),
                "cumplimiento": local.get("cumplimiento", "Pendiente"),
            })

        print(f"✅ Renderizando {len(pedidos_finales)} pedidos (combinados SQL + local)")
        return render_template(
            "planner_dashboard.html",
            facturas=pedidos_finales,
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            search=search
        )
    except Exception as e:
        print(f"⚠️ Error al renderizar planner: {e}")
        return render_template("planner_dashboard.html", facturas=[], fecha_inicio=None, fecha_fin=None)


@app.route("/actualizar_solicitada/<pedido>", methods=["POST"])
def actualizar_solicitada(pedido):
    """Registra fecha solicitada y calcula hora límite (+30 minutos)."""
    try:
        conn = sqlite3.connect("local_data.db")
        cursor = conn.cursor()

        # Crear la tabla si no existe (seguridad extra)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pedidos (
                pedido TEXT PRIMARY KEY,
                fecha_solicitada TEXT,
                hora_limite TEXT,
                fecha_entregada TEXT,
                cumplimiento TEXT
            )
        """)

        # Calcula las horas
        fecha_solicitada = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        hora_limite_dt = datetime.now() + timedelta(minutes=30)
        hora_limite = hora_limite_dt.strftime("%Y-%m-%d %H:%M:%S")

        # Inserta o actualiza según exista
        cursor.execute("""
            INSERT INTO pedidos (pedido, fecha_solicitada, hora_limite, cumplimiento)
            VALUES (?, ?, ?, 'Pendiente')
            ON CONFLICT(pedido) DO UPDATE SET
                fecha_solicitada=excluded.fecha_solicitada,
                hora_limite=excluded.hora_limite,
                cumplimiento='Pendiente'
        """, (pedido, fecha_solicitada, hora_limite))

        conn.commit()
        conn.close()

        return jsonify({
            "status": "success",
            "fecha_solicitada": fecha_solicitada,
            "hora_limite": hora_limite
        })

    except Exception as e:
        print(f"⚠️ Error al actualizar solicitada: {e}")
        return jsonify({"status": "error"}), 500


@app.route("/actualizar_entregada/<pedido>", methods=["POST"])
def actualizar_entregada(pedido):
    """Registra fecha de entrega y evalúa cumplimiento con hora límite."""
    try:
        conn = sqlite3.connect("local_data.db")
        cursor = conn.cursor()

        cursor.execute("SELECT hora_limite FROM pedidos WHERE pedido = ?", (pedido,))
        row = cursor.fetchone()
        if not row:
            print(f"⚠️ Pedido no encontrado en local_data.db: {pedido}")
            return jsonify({"status": "error", "msg": "Pedido no encontrado"}), 404

        hora_limite = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
        fecha_entregada_dt = datetime.now()
        fecha_entregada = fecha_entregada_dt.strftime("%Y-%m-%d %H:%M:%S")

        cumple = fecha_entregada_dt <= hora_limite
        cumplimiento = "Cumple" if cumple else "No cumple"

        cursor.execute("""
            UPDATE pedidos
            SET fecha_entregada = ?, cumplimiento = ?
            WHERE pedido = ?
        """, (fecha_entregada, cumplimiento, pedido))

        conn.commit()
        conn.close()

        return jsonify({
            "status": "success",
            "fecha_entregada": fecha_entregada,
            "cumplimiento": cumplimiento,
            "cumple": cumple
        })

    except Exception as e:
        print(f"⚠️ Error al actualizar entrega: {e}")
        return jsonify({"status": "error"}), 500


@app.route("/kpi")
def kpi_view():
    """Vista de KPIs basada en los mismos datos del Planner."""
    try:
        # Obtener rango de fechas desde parámetros (opcional)
        fecha_inicio = request.args.get("fecha_inicio")
        fecha_fin = request.args.get("fecha_fin")

        pedidos = get_pedidos(fecha_inicio, fecha_fin)
        total = len(pedidos)

        # Calcular métricas
        cumple = sum(1 for p in pedidos if p.get("Cumplimiento") == "Cumple")
        no_cumple = sum(1 for p in pedidos if p.get("Cumplimiento") == "No Cumple")
        pendiente = sum(1 for p in pedidos if p.get("Cumplimiento") == "Pendiente")

        cumplimiento_pct = 0
        if total > 0:
            cumplimiento_pct = round((cumple / total) * 100, 2)

        # Promedio de tiempo entre solicitada y entregada (en minutos)
        tiempos = []
        for p in pedidos:
            if p.get("FechaSolicitada") and p.get("FechaEntregada"):
                try:
                    f1 = datetime.strptime(p["FechaSolicitada"], "%Y-%m-%d %H:%M:%S")
                    f2 = datetime.strptime(p["FechaEntregada"], "%Y-%m-%d %H:%M:%S")
                    delta = (f2 - f1).total_seconds() / 60
                    tiempos.append(delta)
                except:
                    pass

        promedio_min = round(sum(tiempos) / len(tiempos), 2) if tiempos else 0

        return render_template(
            "kpi_dashboard.html",
            total=total,
            cumple=cumple,
            no_cumple=no_cumple,
            pendiente=pendiente,
            cumplimiento_pct=cumplimiento_pct,
            promedio_min=promedio_min,
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin
        )

    except Exception as e:
        print(f"⚠️ Error al cargar KPIs: {e}")
        return render_template(
            "kpi_dashboard.html",
            total=0, cumple=0, no_cumple=0,
            cumplimiento_pct=0, promedio_min=0,
            error=str(e)
        )

# ------------------------------------------------------
# KPI´S
# ------------------------------------------------------
@app.route("/kpi")
def kpi_dashboard():
    """
    Página de métricas (KPIs) — muestra estadísticas generales.
    Calcula los totales desde la base local SQLite (pedidos_local)
    y los combina con los datos de cumplimiento del sistema.
    """
    try:
        conn = sqlite3.connect(LOCAL_DB)
        df = pd.read_sql_query("SELECT * FROM pedidos_local", conn)
        conn.close()

        if df.empty or "cumplimiento" not in df.columns:
            stats = {
                "tasa_cumplimiento": 0,
                "total_cumple": 0,
                "total_no_cumple": 0,
                "total_enviadas": 0
            }
            facturas = []
        else:
            total_enviadas = len(df[df["fecha_entregada"].notnull()])
            total_cumple = len(df[df["cumplimiento"] == "Cumple"])
            total_no_cumple = len(df[df["cumplimiento"] == "No Cumple"])
            tasa_cumplimiento = round((total_cumple / total_enviadas) * 100, 2) if total_enviadas > 0 else 0

            stats = {
                "tasa_cumplimiento": tasa_cumplimiento,
                "total_cumple": total_cumple,
                "total_no_cumple": total_no_cumple,
                "total_enviadas": total_enviadas
            }

            facturas = df[df["fecha_entregada"].notnull()].to_dict(orient="records")

        return render_template("reporte.html", stats=stats, facturas=facturas)

    except Exception as e:
        print(f"⚠️ Error en kpi_dashboard: {e}")
        return f"Ocurrió un error al generar el reporte KPI: {e}", 500



# ------------------------------------------------------
# EJECUCIÓN PRINCIPAL
# ------------------------------------------------------
if __name__ == "__main__":
    hilo_sync = Thread(target=sincronizar_periodicamente, daemon=True)
    hilo_sync.start()
    init_local_db()
    sincronizar_pedidos()
    app.run(debug=True)