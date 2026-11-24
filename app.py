import sqlite3
import re
import hashlib
from datetime import datetime
from flask import Flask, request, jsonify, send_file

try:
    from flask_cors import CORS
except ImportError:
    CORS = None

app = Flask(__name__)
if CORS:
    CORS(app)

DB_NAME = 'contingencia.db'

CLIENTES_INICIALES = [
    ("18.762.431-5", "María González Tapia", "Verificada OK", "green", "$450.000", "$1.200.000", "$200.000", "780 Puntos (Excelente)", "$3.500.000", "Sin Alertas", "green"),
    ("15.123.456-7", "Juan Pérez Cotapos", "Verificada OK", "green", "$1.250.000", "$5.400.000", "$500.000", "810 Puntos (Sobresaliente)", "$8.000.000", "Cliente Preferencial VIP", "#003366"),
    ("19.888.777-K", "Camila Soto Silva", "Falla de Latencia de Red", "#dc3545", "$85.000", "$0", "$200.000", "520 Puntos (Riesgo Medio)", "$0", "Requiere Autorización Supervisor", "#dc3545"),
    ("20.456.123-9", "Carlos Vera Morales", "Verificada OK", "green", "$15.000", "$350.000", "$200.000", "640 Puntos (Aceptable)", "$1.000.000", "Intento Clave Fallida (Previo)", "#ff9900"),
    ("12.345.678-9", "Roberto Muñoz Araya", "Huella Desgastada (3er Intento)", "#ff9900", "$320.000", "$8.900.000", "$200.000", "750 Puntos (Bueno)", "$1.500.000", "Pensionado / Atención Prioritaria", "#003366"),
    ("16.987.654-3", "Andrea Espinoza Palma", "Verificada OK", "green", "$3.800.000", "$12.500.000", "$2.000.000", "790 Puntos (Excelente)", "$15.000.000", "Cuenta Pyme Activa", "green"),
    ("22.111.333-4", "Felipe Cárdenas Lagos", "Verificada OK", "green", "$12.500", "$0", "$200.000", "580 Puntos (Sin Historial)", "$0", "Estudiante (Estrenando CuentaRUT)", "#555"),
    ("17.654.321-K", "Patricia Rojas Fuentes", "Verificada OK", "green", "$920.000", "$2.100.000", "$0 (Bloqueada)", "450 Puntos (Riesgo Alto)", "$0", "BLOQUEO PREVENTIVO LEY DE FRAUDES", "#dc3545"),
    ("14.555.666-8", "Gonzalo Valenzuela Riquelme", "Verificada OK", "green", "$2.100.000", "$18.000.000", "$1.000.000", "830 Puntos (Sobresaliente)", "$12.000.000", "Cliente Gran Ahorrante", "green"),
    ("21.999.000-1", "Valentina Sepúlveda Bravo", "Verificada OK", "green", "$150.000", "$50.000", "$200.000", "670 Puntos (Aceptable)", "$500.000", "Sin Alertas", "green")
]


def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def hash_password(password):
    return hashlib.sha256(password.encode('utf-8')).hexdigest()


def formatear_monto(valor, defecto="$0"):
    val = str(valor or "").strip()
    if not val:
        return defecto
    if val.startswith("$"):
        return val
    digitos = re.sub(r"[^\d]", "", val)
    if digitos:
        return "$" + f"{int(digitos):,}".replace(",", ".")
    return val


def init_db():
    conn = get_db()
    cursor = conn.cursor()

    # Verificar estructura tabla Usuarios
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Usuarios'")
    if cursor.fetchone():
        cols = [row[1] for row in cursor.execute("PRAGMA table_info(Usuarios)").fetchall()]
        if 'email' not in cols:
            cursor.execute("DROP TABLE Usuarios")

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Usuarios (
            id_usuario INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            rol TEXT NOT NULL DEFAULT 'Ejecutivo',
            password_hash TEXT NOT NULL,
            intentos_fallidos INTEGER DEFAULT 0,
            cuenta_bloqueada INTEGER DEFAULT 0,
            fecha_registro TEXT NOT NULL
        )
    ''')

    # Verificar estructura tabla Clientes para Vista 360
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Clientes'")
    if cursor.fetchone():
        cols = [row[1] for row in cursor.execute("PRAGMA table_info(Clientes)").fetchall()]
        if 'cuenta_rut' not in cols:
            cursor.execute("DROP TABLE Clientes")

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Clientes (
            rut_cliente TEXT PRIMARY KEY,
            nombre TEXT NOT NULL,
            biometria TEXT NOT NULL DEFAULT 'Verificada OK',
            bio_color TEXT NOT NULL DEFAULT 'green',
            cuenta_rut TEXT NOT NULL DEFAULT '$0',
            cuenta_ahorro TEXT NOT NULL DEFAULT '$0',
            limite_24h TEXT NOT NULL DEFAULT '$200.000',
            score TEXT NOT NULL DEFAULT '650 Puntos (Aceptable)',
            credito_pre TEXT NOT NULL DEFAULT '$0',
            alerta TEXT NOT NULL DEFAULT 'Sin Alertas',
            alerta_color TEXT NOT NULL DEFAULT 'green'
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Atenciones_Offline (
            id_atencion INTEGER PRIMARY KEY AUTOINCREMENT,
            rut_cliente TEXT NOT NULL,
            nombre_cliente TEXT NOT NULL,
            tramite TEXT NOT NULL,
            ejecutivo_email TEXT NOT NULL,
            fecha TEXT NOT NULL,
            estado_sincronizado INTEGER DEFAULT 1
        )
    ''')

    # Poblar los 10 clientes base en SQLite si la tabla está vacía
    cursor.execute("SELECT COUNT(*) FROM Clientes")
    if cursor.fetchone()[0] == 0:
        cursor.executemany(
            """INSERT INTO Clientes
               (rut_cliente, nombre, biometria, bio_color, cuenta_rut, cuenta_ahorro, limite_24h, score, credito_pre, alerta, alerta_color)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            CLIENTES_INICIALES
        )

    # Poblar ejecutivo base si no existe
    existe = cursor.execute("SELECT 1 FROM Usuarios WHERE email = ?", ("d.monteleone@bancoestado.cl",)).fetchone()
    if not existe:
        cursor.execute(
            """INSERT INTO Usuarios (nombre, email, rol, password_hash, intentos_fallidos, cuenta_bloqueada, fecha_registro)
               VALUES (?, ?, ?, ?, 0, 0, ?)""",
            ("Diego Monteleone", "d.monteleone@bancoestado.cl", "Ejecutivo", hash_password("Banco2026#"), datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        )

    conn.commit()
    conn.close()


def validar_password_segura(password):
    """Mínimo 8 caracteres, mayúsculas, minúsculas, números y símbolos."""
    if len(password) < 8:
        return False, "La contraseña debe tener al menos 8 caracteres."
    if not re.search(r"[A-Z]", password):
        return False, "La contraseña debe incluir al menos una letra mayúscula."
    if not re.search(r"[a-z]", password):
        return False, "La contraseña debe incluir al menos una letra minúscula."
    if not re.search(r"[0-9]", password):
        return False, "La contraseña debe incluir al menos un número."
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>_\-+=/\\]", password):
        return False, "La contraseña debe incluir al menos un símbolo (#, $, @, !, etc.)."
    return True, "Contraseña válida."


def row_a_cliente_dict(row):
    return {
        "nombre": row["nombre"],
        "rut": row["rut_cliente"],
        "biometria": row["biometria"],
        "bioColor": row["bio_color"],
        "cuentaRut": row["cuenta_rut"],
        "cuentaAhorro": row["cuenta_ahorro"],
        "limite24h": row["limite_24h"],
        "score": row["score"],
        "creditoPre": row["credito_pre"],
        "alerta": row["alerta"],
        "alertaColor": row["alerta_color"]
    }


@app.route('/')
def home():
    return send_file('index.html')


# 0. Registro de Nuevos Usuarios en SQLite
@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json() or {}
    nombre = data.get('nombre', '').strip()
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')

    if not nombre or not email or not password:
        return jsonify({"status": "error", "mensaje": "Todos los campos son obligatorios."}), 400

    es_valida, msg = validar_password_segura(password)
    if not es_valida:
        return jsonify({"status": "error", "mensaje": msg}), 400

    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO Usuarios (nombre, email, rol, password_hash, intentos_fallidos, cuenta_bloqueada, fecha_registro)
               VALUES (?, ?, 'Ejecutivo', ?, 0, 0, ?)""",
            (nombre, email, hash_password(password), datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        )
        conn.commit()
        return jsonify({"status": "ok", "mensaje": f"Usuario {nombre} ({email}) guardado en SQLite."}), 201
    except sqlite3.IntegrityError:
        return jsonify({"status": "error", "mensaje": "El correo institucional ya está registrado."}), 400
    finally:
        conn.close()


# 1. Login con Control de 3 Intentos en SQLite
@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json() or {}
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')

    conn = get_db()
    user = conn.execute("SELECT * FROM Usuarios WHERE email = ?", (email,)).fetchone()

    if not user:
        conn.close()
        return jsonify({"status": "error", "mensaje": "Usuario no registrado en SQLite. Regístrese primero."}), 401

    if user['cuenta_bloqueada'] == 1:
        conn.close()
        return jsonify({
            "status": "locked",
            "mensaje": "CUENTA BLOQUEADA: Se superó el máximo de 3 intentos fallidos."
        }), 403

    if user['password_hash'] != hash_password(password):
        nuevos_intentos = user['intentos_fallidos'] + 1
        bloqueada = 1 if nuevos_intentos >= 3 else 0
        conn.execute(
            "UPDATE Usuarios SET intentos_fallidos = ?, cuenta_bloqueada = ? WHERE email = ?",
            (nuevos_intentos, bloqueada, email)
        )
        conn.commit()
        conn.close()

        if bloqueada == 1:
            return jsonify({
                "status": "locked",
                "mensaje": "CUENTA BLOQUEADA (Intento 3 de 3): Acceso suspendido por seguridad."
            }), 403
        else:
            restantes = 3 - nuevos_intentos
            return jsonify({
                "status": "error",
                "mensaje": f"Contraseña incorrecta (Intento {nuevos_intentos} de 3). Quedan {restantes} intento(s)."
            }), 401

    conn.execute("UPDATE Usuarios SET intentos_fallidos = 0 WHERE email = ?", (email,))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok", "usuario": email, "nombre": user['nombre']}), 200


@app.route('/api/unlock', methods=['POST'])
def unlock_account():
    data = request.get_json() or {}
    email = data.get('email', '').strip().lower()
    conn = get_db()
    user = conn.execute("SELECT * FROM Usuarios WHERE email = ?", (email,)).fetchone()
    if not user:
        conn.close()
        return jsonify({"status": "error", "mensaje": "Correo no encontrado en SQLite."}), 404

    conn.execute("UPDATE Usuarios SET intentos_fallidos = 0, cuenta_bloqueada = 0 WHERE email = ?", (email,))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok", "mensaje": f"Cuenta {email} desbloqueada por Supervisor."}), 200


# 2. Gestión de Clientes en SQLite (Listar, Consultar Vista 360 y Agregar Nuevo Cliente)
@app.route('/api/clientes', methods=['GET'])
def listar_clientes():
    conn = get_db()
    rows = conn.execute("SELECT * FROM Clientes ORDER BY rowid ASC").fetchall()
    conn.close()
    return jsonify([row_a_cliente_dict(r) for r in rows]), 200


@app.route('/api/clientes', methods=['POST'])
def crear_cliente():
    data = request.get_json() or {}
    rut = data.get('rut', '').strip()
    nombre = data.get('nombre', '').strip()
    biometria = data.get('biometria', 'Verificada OK').strip()
    bio_color = "green" if "OK" in biometria else "#ff9900"
    cuenta_rut = formatear_monto(data.get('cuentaRut'), "$0")
    cuenta_ahorro = formatear_monto(data.get('cuentaAhorro'), "$0")
    limite_24h = formatear_monto(data.get('limite24h'), "$200.000")
    score = data.get('score', '680 Puntos (Aceptable)').strip() or "680 Puntos (Aceptable)"
    credito_pre = formatear_monto(data.get('creditoPre'), "$0")
    alerta = data.get('alerta', 'Sin Alertas').strip() or "Sin Alertas"
    alerta_color = "green" if alerta == "Sin Alertas" else "#003366"

    if not rut or not nombre:
        return jsonify({"status": "error", "mensaje": "El RUT y el Nombre del cliente son obligatorios."}), 400

    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO Clientes
               (rut_cliente, nombre, biometria, bio_color, cuenta_rut, cuenta_ahorro, limite_24h, score, credito_pre, alerta, alerta_color)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (rut, nombre, biometria, bio_color, cuenta_rut, cuenta_ahorro, limite_24h, score, credito_pre, alerta, alerta_color)
        )
        conn.commit()
        nuevo = conn.execute("SELECT * FROM Clientes WHERE rut_cliente = ?", (rut,)).fetchone()
        print(f"[SQLITE CLIENTES] Nuevo cliente guardado: {rut} - {nombre}")
        return jsonify({
            "status": "ok",
            "mensaje": f"Cliente '{nombre}' ({rut}) guardado en SQLite.",
            "cliente": row_a_cliente_dict(nuevo)
        }), 201
    except sqlite3.IntegrityError:
        return jsonify({"status": "error", "mensaje": f"El RUT {rut} ya existe en la base de datos SQLite."}), 400
    finally:
        conn.close()


@app.route('/api/cliente/<rut>', methods=['GET'])
def get_cliente(rut):
    conn = get_db()
    row = conn.execute("SELECT * FROM Clientes WHERE rut_cliente = ?", (rut.strip(),)).fetchone()
    conn.close()

    if row:
        print(f"[SQLITE VISTA 360] Consulta enviada para RUT: {rut}")
        return jsonify({"status": "ok", "cliente": row_a_cliente_dict(row)}), 200

    return jsonify({
        "status": "not_found",
        "cliente": {
            "nombre": "Cliente Nuevo / No Registrado",
            "rut": rut,
            "biometria": "Pendiente de Enrolamiento",
            "bioColor": "#ff9900",
            "cuentaRut": "$0",
            "cuentaAhorro": "$0",
            "limite24h": "$200.000",
            "score": "Sin Historial",
            "creditoPre": "$0",
            "alerta": "Usar '+ Nuevo Cliente' para registrar",
            "alertaColor": "#ff9900"
        }
    }), 200


# 3. CRUD Completo de Atenciones en SQLite
@app.route('/api/atenciones', methods=['GET'])
def listar_atenciones():
    conn = get_db()
    rows = conn.execute("SELECT * FROM Atenciones_Offline ORDER BY id_atencion DESC").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows]), 200


@app.route('/api/sync', methods=['POST'])
def sync_tramite():
    datos = request.get_json() or {}
    rut = datos.get('rut', '')
    nombre_cliente = datos.get('nombreCliente', 'Cliente BancoEstado')
    tramite = datos.get('tramite', '')
    ejecutivo = datos.get('ejecutivo', 'd.monteleone@bancoestado.cl')
    fecha = datos.get('fecha', datetime.now().strftime("%H:%M:%S"))
    sincronizado = int(datos.get('sincronizado', 1))

    conn = get_db()
    cursor = conn.execute(
        """INSERT INTO Atenciones_Offline (rut_cliente, nombre_cliente, tramite, ejecutivo_email, fecha, estado_sincronizado)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (rut, nombre_cliente, tramite, ejecutivo, fecha, sincronizado)
    )
    nuevo_id = cursor.lastrowid
    conn.commit()
    conn.close()

    estado_txt = "Core Central (En Línea)" if sincronizado == 1 else "SQLite Local (Pendiente Offline)"
    return jsonify({"status": "success", "id": nuevo_id, "mensaje": f"Trámite #{nuevo_id} guardado en {estado_txt}"}), 200


@app.route('/api/atenciones/<int:id_atencion>', methods=['PUT'])
def actualizar_atencion(id_atencion):
    datos = request.get_json() or {}
    nuevo_tramite = datos.get('tramite', '').strip()
    conn = get_db()
    conn.execute("UPDATE Atenciones_Offline SET tramite = ? WHERE id_atencion = ?", (nuevo_tramite, id_atencion))
    conn.commit()
    conn.close()
    return jsonify({"status": "success", "mensaje": f"Atención #{id_atencion} actualizada en SQLite."}), 200


@app.route('/api/atenciones/<int:id_atencion>', methods=['DELETE'])
def eliminar_atencion(id_atencion):
    conn = get_db()
    conn.execute("DELETE FROM Atenciones_Offline WHERE id_atencion = ?", (id_atencion,))
    conn.commit()
    conn.close()
    return jsonify({"status": "success", "mensaje": f"Atención #{id_atencion} eliminada de SQLite."}), 200


@app.route('/api/sync-all', methods=['POST'])
def sincronizar_pendientes():
    conn = get_db()
    cursor = conn.execute("UPDATE Atenciones_Offline SET estado_sincronizado = 1 WHERE estado_sincronizado = 0")
    total = cursor.rowcount
    conn.commit()
    conn.close()
    return jsonify({"status": "success", "total": total, "mensaje": f"{total} trámite(s) pendientes sincronizados con el Core."}), 200


if __name__ == '__main__':
    init_db()
    print("==========================================================")
    print(" SERVIDOR PYTHON (FLASK + SQLITE) BANCOESTADO ONLINE      ")
    print(" Escuchando peticiones HTTP en: http://127.0.0.1:5000     ")
    print("==========================================================")
    app.run(host='127.0.0.1', port=5000, debug=True)