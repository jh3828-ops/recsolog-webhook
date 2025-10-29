import sqlite3
from flask import Flask, render_template, request, redirect, url_for, flash, send_file
from datetime import datetime, timedelta
import pandas as pd
import io

app = Flask(__name__)
app.secret_key = 'tu_clave_secreta_aqui' # Importante para mensajes flash

# --- Configuración y Conexión de Base de Datos ---

DATABASE = 'facturacion.db'

def db_connect():
    """Establece la conexión a la base de datos."""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row # Permite acceder a las columnas por nombre
    return conn

def db_execute(query, args=()):
    """Ejecuta una consulta SQL, retorna el resultado si aplica."""
    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute(query, args)
    conn.commit()
    # Si es una inserción, retornar el resultado si aplica
    return cursor.fetchall() if query.strip().upper().startswith("SELECT") else None

def init_db():
    """Inicializa la tabla de facturas si no existe."""
    db_execute("""
        CREATE TABLE IF NOT EXISTS facturas (
            id INTEGER PRIMARY KEY,
            folio_fiscal TEXT NOT NULL UNIQUE,
            mesa TEXT NOT NULL,
            urgente TEXT NOT NULL,
            comentarios TEXT,
            fecha_solicitud TEXT, -- YYYY-MM-DD (Col A)
            hora_solicitud TEXT,  -- HH:MM:SS (Col E)
            fecha_ingreso TEXT,   -- Full datetime (Col A/E comb.)
            hora_limite TEXT,     -- Full datetime (Col H)
            aprobacion_solicitante TEXT DEFAULT 'Pendiente', -- Col F
            estado_envio TEXT DEFAULT 'Pendiente',          -- Col I
            fecha_envio TEXT,     -- Full datetime (Col J)
            cumplimiento_tiempo TEXT -- Col M
        );
    """)

# Inicializa la DB al arrancar la aplicación
with app.app_context():
    init_db()

# --- Funciones Auxiliares de Lógica de Negocio ---

def calcular_hora_limite(fecha_ingreso):
    """Calcula la hora límite (30 minutos después) y la formatea."""
    dt_ingreso = datetime.strptime(fecha_ingreso, '%Y-%m-%d %H:%M:%S')
    # Suma 30 minutos al tiempo de ingreso
    dt_limite = dt_ingreso + timedelta(minutes=30)
    return dt_limite.strftime('%Y-%m-%d %H:%M:%S')

def calcular_tiempo_restante(hora_limite):
    """Calcula el estado del semáforo basado en el tiempo restante al límite."""
    if not hora_limite:
        return 'verde', None

    dt_limite = datetime.strptime(hora_limite, '%Y-%m-%d %H:%M:%S')
    ahora = datetime.now()
    diferencia = dt_limite - ahora
    
    if diferencia.total_seconds() < 0:
        return 'rojo', f"VENCIDO por {-diferencia.total_seconds() // 60} min"
    elif diferencia.total_seconds() <= 300: # 5 minutos = 300 segundos
        return 'amarillo', None
    else:
        return 'verde', None

def calcular_cumplimiento(hora_limite, fecha_envio):
    """Calcula la Columna M (Cumplimiento de tiempo)."""
    if not fecha_envio:
        return 'Pendiente'
        
    dt_limite = datetime.strptime(hora_limite, '%Y-%m-%d %H:%M:%S')
    dt_envio = datetime.strptime(fecha_envio, '%Y-%m-%d %H:%M:%S')
    
    diferencia = dt_envio - dt_limite
    
    if diferencia.total_seconds() <= 0:
        return 'Cumple'
    else:
        minutos_tarde = int(diferencia.total_seconds() // 60)
        segundos_tarde = int(diferencia.total_seconds() % 60)
        return f'No Cumple (Tardó {minutos_tarde} min {segundos_tarde} seg)'


def get_facturas_with_status(search=None, estado=None, mesa=None):
    """Obtiene y procesa todas las facturas con semáforo y cumplimiento."""
    query = "SELECT * FROM facturas WHERE 1=1"
    args = []

    if search:
        query += " AND folio_fiscal LIKE ?"
        args.append(f"%{search}%")
    
    if estado and estado != 'todos':
        query += " AND estado_envio = ?"
        args.append(estado)

    if mesa and mesa != 'todos':
        query += " AND mesa = ?"
        args.append(mesa)

    query += " ORDER BY fecha_ingreso DESC"
    
    raw_facturas = db_execute(query, args)
    
    facturas_procesadas = []
    
    for row in raw_facturas:
        factura = dict(row)
        
        hora_limite = factura.get('hora_limite')
        estado_envio = factura.get('estado_envio', 'Pendiente')
        fecha_envio = factura.get('fecha_envio')
        
        if estado_envio == 'Pendiente':
            time_status, _ = calcular_tiempo_restante(hora_limite)
            cumplimiento = 'Pendiente'
        else:
            time_status = 'verde' 
            cumplimiento = calcular_cumplimiento(hora_limite, fecha_envio)

        factura['time_status'] = time_status
        factura['cumplimiento_tiempo'] = cumplimiento
        
        if factura['fecha_ingreso']:
            dt_ingreso = datetime.strptime(factura['fecha_ingreso'], '%Y-%m-%d %H:%M:%S')
            factura['fecha_solicitud'] = dt_ingreso.strftime('%Y-%m-%d')
            factura['hora_solicitud'] = dt_ingreso.strftime('%H:%M:%S')

        facturas_procesadas.append(factura)
        
    return facturas_procesadas


# --- Rutas de la Aplicación ---

@app.route('/', methods=['GET'])
def index():
    """Ruta principal: Permite al usuario seleccionar el módulo (Planner o Empacador) y ofrece la opción de exportar."""
    # Renderiza la página de selección de rol (index.html)
    return render_template('index.html')


@app.route('/planner', methods=['GET'])
def planner_view():
    """Ruta del Planner: Muestra el dashboard completo con filtros y acciones."""
    search = request.args.get('search', '').strip()
    estado = request.args.get('estado', 'todos')
    mesa = request.args.get('mesa', 'todos')

    facturas = get_facturas_with_status(search, estado, mesa)
    
    # Obtener opciones únicas de mesas de la base de datos para el filtro
    mesas_raw = db_execute("SELECT DISTINCT mesa FROM facturas ORDER BY mesa")
    mesas = [row['mesa'] for row in mesas_raw] if mesas_raw else []
    
    filter_options = {
        'estados': ['Pendiente', 'Enviada'],
        'mesas': mesas
    }

    return render_template(
        'planner_dashboard.html',
        facturas=facturas,
        filter_options=filter_options,
        current_search=search,
        current_estado=estado,
        current_mesa=mesa
    )

@app.route('/empacador', methods=['GET'])
def empacador_view():
    """Ruta del Empacador: Muestra solo el formulario de registro y la tabla read-only."""
    facturas = get_facturas_with_status()
    return render_template('empacador_dashboard.html', facturas=facturas)


@app.route('/empacador/agregar', methods=['POST'])
def agregar_factura():
    """Ruta para agregar una nueva solicitud de factura (usada por Empacador)."""
    folio_fiscal = request.form['folio_fiscal'].upper()
    mesa = request.form['mesa']
    urgente = request.form['urgente']
    
    # El Empacador solo llena los campos principales, el comentario inicia vacío
    comentarios = "" 
    
    try:
        fecha_ingreso = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        hora_limite = calcular_hora_limite(fecha_ingreso)

        db_execute(
            """INSERT INTO facturas (folio_fiscal, mesa, urgente, comentarios, fecha_ingreso, hora_limite, fecha_solicitud, hora_solicitud) 
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                folio_fiscal, 
                mesa, 
                urgente, 
                comentarios, 
                fecha_ingreso, 
                hora_limite,
                fecha_ingreso.split(' ')[0],
                fecha_ingreso.split(' ')[1]
            )
        )
        flash(f'Solicitud {folio_fiscal} registrada para la Mesa {mesa}. Límite: {hora_limite.split(" ")[1]} (30 min)', 'success')
        
    except sqlite3.IntegrityError:
        flash(f'Error: El Folio Fiscal {folio_fiscal} ya existe.', 'error')
    except Exception as e:
        flash(f'Ocurrió un error al registrar la solicitud: {e}', 'error')
        
    # Redirigir de vuelta al módulo del empacador después de la adición
    return redirect(url_for('empacador_view'))


@app.route('/guardar_comentario/<int:factura_id>', methods=['POST'])
def guardar_comentario(factura_id):
    """Ruta para que el Planner guarde comentarios de forma inline (AJAX)."""
    from flask import jsonify # Importación local para esta función
    
    data = request.get_json()
    comentario = data.get('comentario', '')
    
    try:
        db_execute(
            "UPDATE facturas SET comentarios = ? WHERE id = ?",
            (comentario, factura_id)
        )
        return jsonify({'status': 'success', 'message': 'Comentario guardado.'}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'Error al guardar el comentario: {e}'}), 500
    

@app.route('/aprobar/<int:factura_id>', methods=['POST'])
def aprobar_solicitud(factura_id):
    """Ruta para marcar la solicitud como Aprobada (Usada por Planner)."""
    try:
        db_execute(
            "UPDATE facturas SET aprobacion_solicitante = ? WHERE id = ?",
            ('Aprobado', factura_id)
        )
        flash(f'Solicitud {factura_id} marcada como Aprobada por Solicitante (F).', 'success')
    except Exception as e:
        flash(f'Error al aprobar: {e}', 'error')
    
    return redirect(url_for('planner_view'))

# *** RUTA CORRECTA: ENVIAR_CFDI ***
@app.route('/enviar/<int:factura_id>', methods=['POST'])
def enviar_cfdi(factura_id): # <--- Esta es la función correcta (enviar_cfdi)
    """Ruta para marcar el CFDI como Enviado (Usada por Planner)."""
    try:
        factura = db_execute("SELECT hora_limite FROM facturas WHERE id = ?", (factura_id,))
        if not factura:
            flash("Error: Factura no encontrada.", 'error')
            return redirect(url_for('planner_view'))
            
        hora_limite = factura[0]['hora_limite']
        fecha_envio = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        cumplimiento = calcular_cumplimiento(hora_limite, fecha_envio)
        
        db_execute(
            "UPDATE facturas SET estado_envio = ?, fecha_envio = ?, cumplimiento_tiempo = ? WHERE id = ?",
            ('Enviada', fecha_envio, cumplimiento, factura_id)
        )
        flash(f'CFDI enviado para la factura {factura_id}. Cumplimiento: {cumplimiento}.', 'success')
    except Exception as e:
        flash(f'Error al enviar CFDI: {e}', 'error')
    
    return redirect(url_for('planner_view'))


@app.route('/exportar_excel')
def exportar_excel():
    """Genera y descarga un archivo Excel con los campos específicos solicitados."""
    try:
        raw_facturas = db_execute("SELECT * FROM facturas ORDER BY fecha_ingreso DESC")
        
        if not raw_facturas:
            flash("No hay datos para exportar.", 'error')
            # Redirigir a la página principal si está disponible, sino al planner
            if request.referrer and url_for('index') in request.referrer:
                 return redirect(url_for('index'))
            return redirect(url_for('planner_view'))

        datos_para_excel = []
        for f in raw_facturas:
            
            fecha_entrega_completa = f['fecha_envio'] if f['estado_envio'] == 'Enviada' and f['fecha_envio'] else 'PENDIENTE'
            hora_limite_completa = f['hora_limite'] if f['hora_limite'] else 'N/A'
            cumplimiento = calcular_cumplimiento(f['hora_limite'], f['fecha_envio']) if f['estado_envio'] == 'Enviada' else 'PENDIENTE'

            datos_para_excel.append({
                'Pedido': f['folio_fiscal'],                          
                'Fecha y Hora Solicitud': f['fecha_ingreso'],         
                'Fecha y Hora Límite': hora_limite_completa,          
                'Fecha y Hora Entrega': fecha_entrega_completa,       
                'Mesa': f['mesa'],                                    
                'Estatus': f['estado_envio'],                         
                'Cumplimiento': cumplimiento                          
            })

        df = pd.DataFrame(datos_para_excel)
        output = io.BytesIO()
        writer = pd.ExcelWriter(output, engine='xlsxwriter')
        df.to_excel(writer, index=False, sheet_name='Reporte Facturas')
        writer.close()
        output.seek(0)
        
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            download_name=f'Reporte_Facturacion_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx',
            as_attachment=True
        )

    except Exception as e:
        flash(f'Ocurrió un error durante la exportación a Excel: {e}', 'error')
        
        # Redirigir a la página principal si está disponible, sino al planner
        if request.referrer and url_for('index') in request.referrer:
            return redirect(url_for('index'))
        return redirect(url_for('planner_view'))

if __name__ == '__main__':
    app.run(debug=True)
