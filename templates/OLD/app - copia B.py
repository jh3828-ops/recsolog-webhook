from flask import Flask, render_template, request, jsonify
from datetime import datetime, timedelta
from sqlalchemy import create_engine, text
import sqlite3
import threading
import time

# --- Configuración base ---
app = Flask(__name__)
app.secret_key = "clave_super_segura"

# --- Conexión a SQL Server ---
try:
    connection_string = (
        "mssql+pyodbc://recsolog:8_HaZ!2Z@204.232.237.135,1433/Recsolog_wms"
        "?driver=ODBC+Driver+18+for+SQL+Server&Encrypt=no&TrustServerCertificate=yes"
    )
    engine = create_engine(connection_string, fast_executemany=True)
    print("✅ Conectado correctamente a SQL Server.")
except Exception as e:
    print(f"❌ Error al conectar a SQL Server:\n{e}")

# --- Base local SQLite (para guardar datos locales del usuario) ---
LOCAL_DB = "planner_local.db"

def init_local_db():
    """Inicializa la base local SQLite si no existe."""
    conn = sqlite3.connect(LOCAL_DB)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS registros_locales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            folio TEXT UNIQUE,
            fecha_solicitada TEXT,
            fecha_entregada TEXT,
            cumplimiento TEXT
        )
    """)
    conn.commit()
    conn.close()

# Crear la base local al iniciar
init_local_db()

# --- Funciones auxiliares de persistencia ---
def local_get(folio):
    conn = sqlite3.connect(LOCAL_DB)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM registros_locales WHERE folio=?", (folio,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def local_set(folio, campo, valor):
    conn = sqlite3.connect(LOCAL_DB)
    c = conn.cursor()
    registro = local_get(folio)
    if registro:
        c.execute(f"UPDATE registros_locales SET {campo}=? WHERE folio=?", (valor, folio))
    else:
        c.execute(
            "INSERT INTO registros_locales (folio, fecha_solicitada, fecha_entregada, cumplimiento) VALUES (?, '', '', '')",
            (folio,),
        )
        c.execute(f"UPDATE registros_locales SET {campo}=? WHERE folio=?", (valor, folio))
    conn.commit()
    conn.close()

# --- Funciones lógicas ---
def calcular_cumplimiento(hora_limite, fecha_entrega):
    if not fecha_entrega:
        return "Pendiente"
    dt_limite = datetime.strptime(hora_limite, "%Y-%m-%d %H:%M:%S")
    dt_entrega = datetime.strptime(fecha_entrega, "%Y-%m-%d %H:%M:%S")
    return "Cumple" if dt_entrega <= dt_limite else "No Cumple"

def calcular_hora_limite(fecha_solicitada):
    dt = datetime.strptime(fecha_solicitada, "%Y-%m-%d %H:%M:%S")
    return (dt + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")

def get_pedidos(search=None, fecha_inicio=None, fecha_fin=None):
    """Obtiene los pedidos desde SQL Server (solo lectura)."""
    query = """
        SELECT 
            ds.IDDocumentoSalida,
            ds.FechaDocumento,
            ds.FechaHoraRegistro
        FROM DOCUMENTOSALIDA ds
        INNER JOIN DETALLEEMBARQUE de
            ON ds.IDDocumentoSalida = de.IDEmbarque
        WHERE ds.IDCompania = '15'
          AND de.IDEstadoEmbarque = 7
          AND (
                ds.IDDocumentoSalida LIKE '%F1' OR
                ds.IDDocumentoSalida LIKE '%F2' OR
                ds.IDDocumentoSalida LIKE '%F1X'
              )
    """
    args = {}

    if search:
        query += " AND ds.IDDocumentoSalida LIKE :search"
        args["search"] = f"%{search}%"

    if fecha_inicio and fecha_fin:
        query += " AND CAST(ds.FechaHoraRegistro AS DATE) BETWEEN :inicio AND :fin"
        args["inicio"] = fecha_inicio
        args["fin"] = fecha_fin
    elif fecha_inicio:
        query += " AND CAST(ds.FechaHoraRegistro AS DATE) >= :inicio"
        args["inicio"] = fecha_inicio
    elif fecha_fin:
        query += " AND CAST(ds.FechaHoraRegistro AS DATE) <= :fin"
        args["fin"] = fecha_fin

    query += " ORDER BY ds.FechaHoraRegistro DESC"

    registros = []
    try:
        with engine.begin() as conn:
            result = conn.execute(text(query), args)
            registros = result.mappings().all()  # ✅ devuelve dicts list
    except Exception as e:
        print(f"Error en consulta SQL Server: {e}")
        return []

    pedidos = []
    for r in registros:
        pedido = dict(r)
        folio = pedido["IDDocumentoSalida"]
        fecha_registro = pedido["FechaHoraRegistro"]
        fecha_str = fecha_registro.strftime("%Y-%m-%d %H:%M:%S") if isinstance(fecha_registro, datetime) else str(fecha_registro)

        local = local_get(folio)
        fecha_solicitada = local["fecha_solicitada"] if local else ""
        fecha_entregada = local["fecha_entregada"] if local else ""
        cumplimiento = local["cumplimiento"] if local else "Pendiente"

        pedido.update(
            {
                "FechaSolicitada": fecha_solicitada,
                "FechaEntregada": fecha_entregada,
                "Cumplimiento": cumplimiento,
                "FechaHoraRegistroStr": fecha_str,
            }
        )
        pedidos.append(pedido)

    return pedidos

# --- Rutas principales ---
@app.route("/")
def index():
    return render_template("index.html", datetime=datetime)

@app.route("/planner")
def planner_view():
    """Vista principal del Planner (solo tabla)."""
    search = request.args.get("search", "").strip()
    fecha_inicio = request.args.get("fecha_inicio")
    fecha_fin = request.args.get("fecha_fin")

    pedidos = get_pedidos(search, fecha_inicio or None, fecha_fin or None)
    return render_template(
        "planner_dashboard.html",
        facturas=pedidos,
        current_search=search,
        current_fecha_inicio=fecha_inicio,
        current_fecha_fin=fecha_fin,
        datetime=datetime,
        timedelta=timedelta,
    )

@app.route("/kpi")
def kpi_view():
    """Vista de KPIs y datos globales."""
    pedidos = get_pedidos()
    total = len(pedidos)
    cumplen = sum(1 for p in pedidos if p["Cumplimiento"] == "Cumple")
    no_cumplen = sum(1 for p in pedidos if p["Cumplimiento"] == "No Cumple")
    pendientes = sum(1 for p in pedidos if p["Cumplimiento"] == "Pendiente")
    eficiencia = round((cumplen / total * 100) if total > 0 else 0, 2)

    # Si es una petición AJAX (JS), devolver solo JSON
    if request.args.get("ajax"):
        return jsonify({
            "total": total,
            "cumplen": cumplen,
            "no_cumplen": no_cumplen,
            "pendientes": pendientes,
            "eficiencia": eficiencia
        })

    # Renderizado normal
    return render_template(
        "planner_kpi.html",
        total=total,
        cumplen=cumplen,
        no_cumplen=no_cumplen,
        pendientes=pendientes,
        eficiencia=eficiencia,
        datetime=datetime
    )

# --- API local (para botones en Planner) ---
@app.route("/local/solicitada", methods=["POST"])
def marcar_solicitada():
    data = request.get_json()
    folio = data.get("id")
    hora_actual = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    local_set(folio, "fecha_solicitada", hora_actual)
    hora_limite = calcular_hora_limite(hora_actual)
    return jsonify({"status": "ok", "hora": hora_actual, "hora_limite": hora_limite})

@app.route("/local/entregada", methods=["POST"])
def marcar_entregada():
    data = request.get_json()
    folio = data.get("id")
    hora_actual = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    registro = local_get(folio)
    if registro and registro["fecha_solicitada"]:
        hora_limite = calcular_hora_limite(registro["fecha_solicitada"])
        cumple = calcular_cumplimiento(hora_limite, hora_actual)
    else:
        cumple = "Pendiente"

    local_set(folio, "fecha_entregada", hora_actual)
    local_set(folio, "cumplimiento", cumple)
    return jsonify({"status": "ok", "hora": hora_actual, "cumple": cumple})

# --- Auto-sincronización con SQL Server ---
def sincronizar_periodicamente():
    while True:
        try:
            pedidos = get_pedidos()
            print(f"🔁 Sincronizados {len(pedidos)} pedidos desde SQL Server.")
        except Exception as e:
            print(f"Error en sincronización: {e}")
        time.sleep(60)

threading.Thread(target=sincronizar_periodicamente, daemon=True).start()

# --- Inicio del servidor ---
if __name__ == "__main__":
    app.run(debug=True)
