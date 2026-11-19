"""
Sistema de Asistencia — DEMO para Casa Perú
===========================================
Copia de demostración del sistema de asistencia Eddy's BBQ.

Base de datos: PostgreSQL (DATABASE_URL) en la nube
               MySQL (MYSQL_*) si se configura
               SQLite en desarrollo local

Modo demo (DEMO_MODE=1):
  * No requiere el lector físico ZK9500 / DigitalPersona.
  * La huella se simula desde la pantalla (mismo flujo de negocio real).
  * Se siembran datos de ejemplo de Casa Perú la primera vez.

Variables de entorno:
  DATABASE_URL    → cadena de conexión PostgreSQL (Render/Neon/Supabase)
  MYSQL_HOST / MYSQL_USER / MYSQL_PASSWORD / MYSQL_DB
  AGENT_API_KEY   → clave secreta para el agente local
  DEMO_MODE       → "1" activa el simulador de huella
  DEMO_COMPANY    → nombre de la empresa mostrado en la interfaz
"""

from flask import Flask, render_template, jsonify, request, send_file
import os, sys, csv, io, threading, time, random

# Consola Windows (cp1252) no soporta ✓ / emojis en logs
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
from collections import defaultdict
from datetime import datetime, date, timezone, timedelta

# Zona horaria Ecuador (UTC-5)
TZ_EC = timezone(timedelta(hours=-5))

def now_ec():
    """Retorna datetime actual en hora Ecuador como string."""
    return datetime.now(TZ_EC).strftime("%Y-%m-%d %H:%M:%S")

def get_logical_day(dt):
    """Día lógico de una marcación.

    Si la hora es < 4:00 AM, la marcación pertenece al día anterior
    (turno nocturno). Esto evita que un empleado que sale a las 02:00 AM
    cuente como Entrada de un nuevo día.
    """
    if dt.hour < 4:
        return (dt - timedelta(days=1)).date()
    return dt.date()

app = Flask(__name__)

# ─── Detección de entorno ────────────────────────────────────────────────────
MYSQL_HOST     = os.environ.get("MYSQL_HOST")
MYSQL_USER     = os.environ.get("MYSQL_USER")
MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD")
MYSQL_DB       = os.environ.get("MYSQL_DB")

DATABASE_URL = os.environ.get("DATABASE_URL")

USE_MYSQL    = all([MYSQL_HOST, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DB])
USE_POSTGRES = bool(DATABASE_URL) and not USE_MYSQL

# ─── Modo demostración (sin lector físico) ───────────────────────────────────
DEMO_MODE    = os.environ.get("DEMO_MODE", "0").strip().lower() in ("1", "true", "yes", "on", "si", "sí")
DEMO_COMPANY = os.environ.get("DEMO_COMPANY", "Casa Perú")

# ── Diagnóstico de variables de entorno (visible en logs de Render) ──────────
print("=" * 55)
print("  [DIAGNÓSTICO] Variables de entorno MySQL:")
print(f"  MYSQL_HOST='{MYSQL_HOST}'")
print(f"  MYSQL_USER='{MYSQL_USER}'")
print(f"  MYSQL_PASSWORD='{'***' if MYSQL_PASSWORD else None}'")
print(f"  MYSQL_DB='{MYSQL_DB}'")
print(f"  USE_MYSQL={USE_MYSQL}")
print("=" * 55)

# ─── Capa MySQL ──────────────────────────────────────────────────────────────
if USE_MYSQL:
    import pymysql
    import pymysql.cursors

    def get_db():
        conn = pymysql.connect(
            host=MYSQL_HOST,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            database=MYSQL_DB,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=False,
            init_command="SET time_zone = '-05:00'",
        )
        return conn

    def init_db():
        print("  [DB] Intentando conectar a MySQL...")
        try:
            conn = get_db()
            print(f"  [DB] ✓ Conexión exitosa a {MYSQL_HOST}/{MYSQL_DB}")
        except Exception as e:
            print(f"  [DB] *** ERROR DE CONEXIÓN MYSQL: {e} ***")
            raise
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS locales (
                        id     INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                        nombre VARCHAR(255) NOT NULL
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """)
                cur.execute("SELECT COUNT(*) as cnt FROM locales")
                if cur.fetchone()["cnt"] == 0:
                    for loc in ["Casa Matriz", "Local Norte", "Local Sur", "Local Centro"]:
                        cur.execute("INSERT INTO locales (nombre) VALUES (%s)", (loc,))
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS cargos (
                        id     INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                        nombre VARCHAR(255) NOT NULL
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """)
                cur.execute("SELECT COUNT(*) as cnt FROM cargos")
                if cur.fetchone()["cnt"] == 0:
                    for cargo in ["Administrador", "Cajero", "Cocinero", "Mesero", "Ayudante de cocina", "Bartender", "Supervisor"]:
                        cur.execute("INSERT INTO cargos (nombre) VALUES (%s)", (cargo,))
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS employees (
                        id       INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                        name     VARCHAR(255) NOT NULL,
                        dept     VARCHAR(255) DEFAULT 'General',
                        cargo    VARCHAR(255) DEFAULT '',
                        template LONGBLOB
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """)
                try:
                    cur.execute("ALTER TABLE employees ADD COLUMN cargo VARCHAR(255) DEFAULT '' AFTER dept")
                except Exception:
                    pass
                # Permitir empleados sin huella (template NULL)
                try:
                    cur.execute("ALTER TABLE employees MODIFY template LONGBLOB NULL")
                except Exception:
                    pass
                # Índices empleados (aceleran filtro por local)
                for idx_sql in [
                    "CREATE INDEX idx_employees_dept ON employees(dept)",
                    "CREATE INDEX idx_employees_name ON employees(name)",
                ]:
                    try:
                        cur.execute(idx_sql)
                    except Exception:
                        pass
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS attendance (
                        id            INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                        employee_id   INT NOT NULL,
                        employee_name VARCHAR(255) NOT NULL,
                        dept          VARCHAR(255),
                        local         VARCHAR(255),
                        punch_type    VARCHAR(50) NOT NULL,
                        timestamp     VARCHAR(50) NOT NULL
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """)
                try:
                    cur.execute("ALTER TABLE attendance ADD COLUMN local VARCHAR(255) AFTER dept")
                except Exception:
                    pass
                # Índices attendance (aceleran reportes y filtrado)
                for idx_sql in [
                    "CREATE INDEX idx_attendance_emp_ts ON attendance(employee_id, timestamp)",
                    "CREATE INDEX idx_attendance_local ON attendance(local)",
                    "CREATE INDEX idx_attendance_dept ON attendance(dept)",
                    "CREATE INDEX idx_attendance_ts ON attendance(timestamp)",
                ]:
                    try:
                        cur.execute(idx_sql)
                    except Exception:
                        pass
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS agents (
                        id        VARCHAR(100) PRIMARY KEY,
                        name      VARCHAR(255),
                        api_key   VARCHAR(255) NOT NULL,
                        last_seen VARCHAR(50),
                        status    VARCHAR(50) DEFAULT 'offline'
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS access_codes (
                        id          INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                        code        VARCHAR(100) NOT NULL UNIQUE,
                        descripcion VARCHAR(255) DEFAULT '',
                        activo      TINYINT(1) DEFAULT 1
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """)
                cur.execute("SELECT COUNT(*) as cnt FROM access_codes")
                if cur.fetchone()["cnt"] == 0:
                    cur.execute("INSERT INTO access_codes (code, descripcion) VALUES (%s, %s)", ("admin123", "Administrador"))
                    cur.execute("INSERT INTO access_codes (code, descripcion) VALUES (%s, %s)", ("supervisor2024", "Supervisor"))
            conn.commit()
            print("  [DB] ✓ Tablas MySQL verificadas/creadas correctamente")
        except Exception as e:
            print(f"  [DB] *** ERROR AL CREAR TABLAS: {e} ***")
            raise
        finally:
            conn.close()

    def db_query(sql, params=(), fetchone=False, fetchall=False, commit=False):
        conn = get_db()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                if commit:
                    conn.commit()
                    return cur.lastrowid
                if fetchone:
                    return cur.fetchone()
                if fetchall:
                    return cur.fetchall()
        finally:
            conn.close()

# ─── Capa PostgreSQL (Render / Neon / Supabase) ─────────────────────────────
elif USE_POSTGRES:
    import psycopg2
    import psycopg2.extras

    def get_db():
        url = DATABASE_URL
        # Render entrega la URL con sslmode=require; Neon también lo acepta.
        if "sslmode=" not in url:
            url += ("&" if "?" in url else "?") + "sslmode=require"
        conn = psycopg2.connect(url, cursor_factory=psycopg2.extras.RealDictCursor)
        conn.autocommit = False
        return conn

    def init_db():
        print("  [DB] Conectando a PostgreSQL...")
        conn = get_db()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS locales (
                        id     SERIAL PRIMARY KEY,
                        nombre VARCHAR(255) NOT NULL
                    )""")
                cur.execute("SELECT COUNT(*) AS cnt FROM locales")
                if cur.fetchone()["cnt"] == 0:
                    for loc in ["Casa Matriz", "Local Norte", "Local Sur", "Local Centro"]:
                        cur.execute("INSERT INTO locales (nombre) VALUES (%s)", (loc,))
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS cargos (
                        id     SERIAL PRIMARY KEY,
                        nombre VARCHAR(255) NOT NULL
                    )""")
                cur.execute("SELECT COUNT(*) AS cnt FROM cargos")
                if cur.fetchone()["cnt"] == 0:
                    for cargo in ["Administrador", "Cajero", "Cocinero", "Mesero", "Ayudante de cocina", "Bartender", "Supervisor"]:
                        cur.execute("INSERT INTO cargos (nombre) VALUES (%s)", (cargo,))
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS employees (
                        id       SERIAL PRIMARY KEY,
                        name     VARCHAR(255) NOT NULL,
                        dept     VARCHAR(255) DEFAULT 'General',
                        cargo    VARCHAR(255) DEFAULT '',
                        template BYTEA
                    )""")
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS attendance (
                        id            SERIAL PRIMARY KEY,
                        employee_id   INT NOT NULL,
                        employee_name VARCHAR(255) NOT NULL,
                        dept          VARCHAR(255),
                        local         VARCHAR(255),
                        punch_type    VARCHAR(50) NOT NULL,
                        timestamp     VARCHAR(50) NOT NULL
                    )""")
                for idx_sql in [
                    "CREATE INDEX IF NOT EXISTS idx_employees_dept ON employees(dept)",
                    "CREATE INDEX IF NOT EXISTS idx_employees_name ON employees(name)",
                    "CREATE INDEX IF NOT EXISTS idx_attendance_emp_ts ON attendance(employee_id, timestamp)",
                    "CREATE INDEX IF NOT EXISTS idx_attendance_local ON attendance(local)",
                    "CREATE INDEX IF NOT EXISTS idx_attendance_dept ON attendance(dept)",
                    "CREATE INDEX IF NOT EXISTS idx_attendance_ts ON attendance(timestamp)",
                ]:
                    try:
                        cur.execute(idx_sql)
                    except Exception:
                        pass
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS agents (
                        id        VARCHAR(100) PRIMARY KEY,
                        name      VARCHAR(255),
                        api_key   VARCHAR(255) NOT NULL,
                        last_seen VARCHAR(50),
                        status    VARCHAR(50) DEFAULT 'offline'
                    )""")
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS access_codes (
                        id          SERIAL PRIMARY KEY,
                        code        VARCHAR(100) NOT NULL UNIQUE,
                        descripcion VARCHAR(255) DEFAULT '',
                        activo      SMALLINT DEFAULT 1
                    )""")
                cur.execute("SELECT COUNT(*) AS cnt FROM access_codes")
                if cur.fetchone()["cnt"] == 0:
                    cur.execute("INSERT INTO access_codes (code, descripcion) VALUES (%s, %s)", ("admin123", "Administrador"))
                    cur.execute("INSERT INTO access_codes (code, descripcion) VALUES (%s, %s)", ("supervisor2024", "Supervisor"))
            conn.commit()
            print("  [DB] ✓ Tablas PostgreSQL verificadas/creadas correctamente")
        except Exception as e:
            print(f"  [DB] *** ERROR AL CREAR TABLAS POSTGRES: {e} ***")
            conn.rollback()
            raise
        finally:
            conn.close()

    def db_query(sql, params=(), fetchone=False, fetchall=False, commit=False):
        conn = get_db()
        try:
            with conn.cursor() as cur:
                if commit and sql.lstrip().upper().startswith("INSERT") and "RETURNING" not in sql.upper():
                    cur.execute(sql + " RETURNING id", params)
                    row = cur.fetchone()
                    conn.commit()
                    return row["id"] if row else None
                cur.execute(sql, params)
                if commit:
                    conn.commit()
                    return None
                if fetchone:
                    return cur.fetchone()
                if fetchall:
                    return cur.fetchall()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

# ─── Capa SQLite (desarrollo local) ─────────────────────────────────────────
else:
    import sqlite3

    DB = os.environ.get("DB_PATH", "attendance.db")

    def get_db():
        con = sqlite3.connect(DB)
        con.row_factory = sqlite3.Row
        return con

    def init_db():
        with get_db() as con:
            con.execute("""CREATE TABLE IF NOT EXISTS locales (
                id     INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL
            )""")
            cur = con.execute("SELECT COUNT(*) FROM locales")
            if cur.fetchone()[0] == 0:
                for loc in ["Casa Matriz", "Local Norte", "Local Sur", "Local Centro"]:
                    con.execute("INSERT INTO locales (nombre) VALUES (?)", (loc,))
            con.execute("""CREATE TABLE IF NOT EXISTS cargos (
                id     INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL
            )""")
            cur2 = con.execute("SELECT COUNT(*) FROM cargos")
            if cur2.fetchone()[0] == 0:
                for cargo in ["Administrador", "Cajero", "Cocinero", "Mesero", "Ayudante de cocina", "Bartender", "Supervisor"]:
                    con.execute("INSERT INTO cargos (nombre) VALUES (?)", (cargo,))
            con.execute("""CREATE TABLE IF NOT EXISTS employees (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                name     TEXT NOT NULL,
                dept     TEXT DEFAULT 'General',
                cargo    TEXT DEFAULT '',
                template BLOB
            )""")
            try:
                con.execute("ALTER TABLE employees ADD COLUMN cargo TEXT DEFAULT ''")
            except Exception:
                pass
            # Índices empleados
            for idx_sql in [
                "CREATE INDEX IF NOT EXISTS idx_employees_dept ON employees(dept)",
                "CREATE INDEX IF NOT EXISTS idx_employees_name ON employees(name)",
            ]:
                try:
                    con.execute(idx_sql)
                except Exception:
                    pass
            con.execute("""CREATE TABLE IF NOT EXISTS attendance (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id   INTEGER NOT NULL,
                employee_name TEXT NOT NULL,
                dept          TEXT,
                local         TEXT,
                punch_type    TEXT NOT NULL,
                timestamp     TEXT NOT NULL
            )""")
            try:
                con.execute("ALTER TABLE attendance ADD COLUMN local TEXT")
            except Exception:
                pass
            # Índices attendance
            for idx_sql in [
                "CREATE INDEX IF NOT EXISTS idx_attendance_emp_ts ON attendance(employee_id, timestamp)",
                "CREATE INDEX IF NOT EXISTS idx_attendance_ts ON attendance(timestamp)",
            ]:
                try:
                    con.execute(idx_sql)
                except Exception:
                    pass
            con.execute("""CREATE TABLE IF NOT EXISTS agents (
                id         TEXT PRIMARY KEY,
                name       TEXT,
                api_key    TEXT NOT NULL,
                last_seen  TEXT,
                status     TEXT DEFAULT 'offline'
            )""")
            con.execute("""CREATE TABLE IF NOT EXISTS access_codes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                code        TEXT NOT NULL UNIQUE,
                descripcion TEXT DEFAULT '',
                activo      INTEGER DEFAULT 1
            )""")
            cur3 = con.execute("SELECT COUNT(*) FROM access_codes")
            if cur3.fetchone()[0] == 0:
                con.execute("INSERT INTO access_codes (code, descripcion) VALUES (?, ?)", ("admin123", "Administrador"))
                con.execute("INSERT INTO access_codes (code, descripcion) VALUES (?, ?)", ("supervisor2024", "Supervisor"))
            con.commit()

    def db_query(sql, params=(), fetchone=False, fetchall=False, commit=False):
        # SQLite usa ? como placeholder; convertimos %s → ?
        sql_sqlite = sql.replace("%s", "?")
        with get_db() as con:
            cur = con.execute(sql_sqlite, params)
            if commit:
                con.commit()
                return cur.lastrowid
            if fetchone:
                row = cur.fetchone()
                return dict(row) if row else None
            if fetchall:
                rows = con.execute(sql_sqlite, params).fetchall()
                return [dict(r) for r in rows]


# ─── Datos de ejemplo (solo modo demo) ───────────────────────────────────────
DEMO_SEDES = ["Casa Perú — Lima", "Casa Perú — Arequipa", "Casa Perú — Cusco"]
DEMO_CARGOS = ["Administrador", "Chef", "Cocinero", "Ayudante de cocina", "Mesero",
               "Bartender", "Barista", "Cajero", "Supervisor", "Anfitrión"]

DEMO_EMPLEADOS = [
    # (nombre, sede, cargo, tiene_huella)
    ("María Fernanda Quispe",  "Casa Perú — Lima",     "Administradora",       True),
    ("Carlos Alberto Rojas",   "Casa Perú — Lima",     "Chef",                 True),
    ("Lucía Torres Mendoza",   "Casa Perú — Lima",     "Cajera",               True),
    ("Jorge Luis Huamán",      "Casa Perú — Lima",     "Mesero",               True),
    ("Ana Paula Chávez",       "Casa Perú — Lima",     "Barista",              True),
    ("Diego Alonso Paredes",   "Casa Perú — Lima",     "Cocinero",             True),
    ("Rosa Elena Mamani",      "Casa Perú — Arequipa", "Supervisora",          True),
    ("Pedro Pablo Ccahuana",   "Casa Perú — Arequipa", "Chef",                 True),
    ("Valeria Nicole Salas",   "Casa Perú — Arequipa", "Mesera",               True),
    ("Miguel Ángel Apaza",     "Casa Perú — Arequipa", "Ayudante de cocina",   True),
    ("Sofía Alejandra Núñez",  "Casa Perú — Arequipa", "Cajera",               False),
    ("Renzo Fabricio Vargas",  "Casa Perú — Cusco",    "Administrador",        True),
    ("Camila Isabel Flores",   "Casa Perú — Cusco",    "Anfitriona",           True),
    ("José Antonio Cárdenas",  "Casa Perú — Cusco",    "Bartender",            True),
    ("Katherine Ysabel Soto",  "Casa Perú — Cusco",    "Mesera",               False),
    ("Bruno Sebastián Loayza", "Casa Perú — Cusco",    "Cocinero",             False),
]


def seed_demo_employees():
    """Crea sedes, cargos y colaboradores de ejemplo (una sola vez)."""
    row = db_query("SELECT COUNT(*) AS cnt FROM employees", fetchone=True)
    if row and row["cnt"] > 0:
        return False

    db_query("DELETE FROM locales", commit=True)
    db_query("DELETE FROM cargos", commit=True)
    for sede in DEMO_SEDES:
        db_query("INSERT INTO locales (nombre) VALUES (%s)", (sede,), commit=True)
    for cargo in DEMO_CARGOS:
        db_query("INSERT INTO cargos (nombre) VALUES (%s)", (cargo,), commit=True)

    for nombre, sede, cargo, tiene in DEMO_EMPLEADOS:
        tpl = os.urandom(1024) if tiene else None
        db_query(
            "INSERT INTO employees (name, dept, cargo, template) VALUES (%s,%s,%s,%s)",
            (nombre, sede, cargo, tpl), commit=True)

    print(f"  [DEMO] ✓ {len(DEMO_EMPLEADOS)} colaboradores de ejemplo creados")
    return True


def seed_demo_attendance(dias=10):
    """Genera marcaciones de ejemplo de los últimos días."""
    empleados = db_query("SELECT id, name, dept FROM employees", fetchall=True) or []
    if not empleados:
        return
    hoy = datetime.now(TZ_EC).date()
    creadas = 0
    for emp in empleados:
        for atras in range(dias, 0, -1):
            dia = hoy - timedelta(days=atras)
            if dia.weekday() == 6:          # domingo libre
                continue
            if random.random() < 0.12:      # faltas ocasionales
                continue
            entrada = datetime(dia.year, dia.month, dia.day,
                               random.randint(8, 9), random.randint(0, 55), 0, tzinfo=TZ_EC)
            salida = datetime(dia.year, dia.month, dia.day,
                              random.randint(17, 19), random.randint(0, 59), 0, tzinfo=TZ_EC)
            for tipo, dt in (("Entrada", entrada), ("Salida", salida)):
                db_query(
                    "INSERT INTO attendance (employee_id, employee_name, dept, local, punch_type, timestamp) "
                    "VALUES (%s,%s,%s,%s,%s,%s)",
                    (emp["id"], emp["name"], emp["dept"], emp["dept"], tipo,
                     dt.strftime("%Y-%m-%d %H:%M:%S")), commit=True)
                creadas += 1
    # Algunos ya entraron hoy (así se puede demostrar la Salida)
    for emp in empleados[: max(1, len(empleados) // 3)]:
        dt = datetime(hoy.year, hoy.month, hoy.day,
                      random.randint(8, 9), random.randint(0, 55), 0, tzinfo=TZ_EC)
        db_query(
            "INSERT INTO attendance (employee_id, employee_name, dept, local, punch_type, timestamp) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            (emp["id"], emp["name"], emp["dept"], emp["dept"], "Entrada",
             dt.strftime("%Y-%m-%d %H:%M:%S")), commit=True)
        creadas += 1
    print(f"  [DEMO] ✓ {creadas} marcaciones de ejemplo creadas")


def seed_demo():
    creados = seed_demo_employees()
    row = db_query("SELECT COUNT(*) AS cnt FROM attendance", fetchone=True)
    if creados or not row or row["cnt"] == 0:
        seed_demo_attendance()


# ─── Estado del scanner ───────────────────────────────────────────────────────
scanner_state = {
    "active": False,
    "mode": "punch",
    "enroll_id": None,
    "enroll_name": None,
    "enroll_templates": 0,
    "last_event": None,
    "message": "Agente desconectado",
    "status": "offline",
    "agent_id": None,
    "agent_name": "—",
    "agent_local": "—",
    "last_heartbeat": 0,
}

# En modo demo el "lector" siempre está en línea: es el navegador quien simula
# las capturas, así que no existe un agente local al que esperar.
if DEMO_MODE:
    scanner_state.update({
        "active":         True,
        "status":         "ready",
        "message":        "Lector simulado listo — toca la huella en pantalla",
        "agent_id":       "demo-simulador",
        "agent_name":     "Simulador Casa Perú",
        "agent_local":    "Todas las sedes",
        "last_heartbeat": time.time(),
    })

state_lock = threading.Lock()

AGENT_API_KEY = os.environ.get("AGENT_API_KEY", "cambia-esta-clave-secreta")
AGENT_TIMEOUT = 15


def demo_auto_ready(delay=6):
    """En demo, el 'lector' vuelve a LISTO unos segundos después del resultado."""
    if not DEMO_MODE:
        return
    def _run():
        time.sleep(delay)
        with state_lock:
            if scanner_state["mode"] == "punch":
                scanner_state["status"]  = "ready"
                scanner_state["message"] = "Lector simulado listo — toca la huella en pantalla"
    threading.Thread(target=_run, daemon=True).start()


def agent_timeout_loop():
    while True:
        time.sleep(5)
        with state_lock:
            if scanner_state["active"]:
                if DEMO_MODE:
                    # El simulador nunca se "desconecta"
                    scanner_state["last_heartbeat"] = time.time()
                    continue
                elapsed = time.time() - scanner_state["last_heartbeat"]
                if elapsed > AGENT_TIMEOUT:
                    scanner_state["active"]           = False
                    scanner_state["status"]           = "offline"
                    scanner_state["message"]          = "Agente desconectado (sin respuesta)"
                    scanner_state["mode"]             = "punch"
                    scanner_state["enroll_id"]        = None
                    scanner_state["enroll_name"]      = None
                    scanner_state["enroll_templates"] = 0
                    scanner_state["agent_local"]      = "—"


# ─── Autenticación del agente ─────────────────────────────────────────────────
def require_agent_key(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        key = request.headers.get("X-Agent-Key") or (
            request.json.get("api_key", "") if request.is_json else ""
        )
        # En modo demo el navegador actúa como "agente simulado" (sin lector físico)
        demo_call = DEMO_MODE and request.headers.get("X-Demo") == "1"
        if key != AGENT_API_KEY and not demo_call:
            return jsonify({"ok": False, "message": "Clave inválida"}), 401
        return f(*args, **kwargs)
    return decorated


# ─── Contexto de plantillas (marca y modo demo) ──────────────────────────────
@app.context_processor
def inject_demo_globals():
    return {
        "demo_mode":    DEMO_MODE,
        "demo_company": DEMO_COMPANY,
        "company_name": DEMO_COMPANY if DEMO_MODE else "Restaurant Eddy's BBQ",
    }


# ─── API del simulador (solo demo) ───────────────────────────────────────────
@app.route("/api/demo/config")
def api_demo_config():
    if not DEMO_MODE:
        return jsonify({"demo": False}), 404
    row = db_query("SELECT COUNT(*) AS cnt FROM employees", fetchone=True)
    return jsonify({
        "demo":      True,
        "company":   DEMO_COMPANY,
        "employees": row["cnt"] if row else 0,
    })


@app.route("/api/demo/reset", methods=["POST"])
def api_demo_reset():
    """Restaura las marcaciones de ejemplo (útil después de una demostración)."""
    if not DEMO_MODE:
        return jsonify({"ok": False, "message": "Solo disponible en modo demo"}), 404
    db_query("DELETE FROM attendance", commit=True)
    seed_demo_attendance()
    with state_lock:
        scanner_state.update({
            "status":           "ready",
            "message":          "Datos de ejemplo restaurados",
            "last_event":       None,
            "mode":             "punch",
            "enroll_templates": 0,
            "enroll_id":        None,
            "enroll_name":      None,
        })
    return jsonify({"ok": True})


# ─── Rutas principales ────────────────────────────────────────────────────────
@app.route("/api/verify_code", methods=["POST"])
def api_verify_code():
    code = (request.json or {}).get("code", "").strip()
    if not code:
        return jsonify({"ok": False, "message": "Contraseña requerida"})
    row = db_query(
        "SELECT id FROM access_codes WHERE code=%s AND activo=1",
        (code,), fetchone=True
    )
    if row:
        return jsonify({"ok": True})
    return jsonify({"ok": False, "message": "Contraseña incorrecta"})


@app.route("/")
def index():
    locales = db_query("SELECT id, nombre FROM locales ORDER BY nombre", fetchall=True) or []
    return render_template("index.html", locales=locales)

@app.route("/empleados")
def empleados():
    locales = db_query("SELECT id, nombre FROM locales ORDER BY nombre", fetchall=True) or []
    cargos  = db_query("SELECT id, nombre FROM cargos ORDER BY nombre", fetchall=True) or []
    return render_template("empleados.html", locales=locales, cargos=cargos)

@app.route("/registros")
def registros():
    return render_template("registros.html")


# ─── API web (frontend) ───────────────────────────────────────────────────────
@app.route("/api/scanner/status")
def api_status():
    with state_lock:
        return jsonify(dict(scanner_state))

@app.route("/api/scanner/init", methods=["POST"])
def api_init():
    with state_lock:
        active = scanner_state["active"]
    if active:
        return jsonify({"ok": True, "message": "Agente ya conectado"})
    return jsonify({
        "ok": False,
        "message": "El agente local no está conectado. Inicia ¨INICIAR.bat¨ en la PC con el ZK9500."
    })

@app.route("/api/enroll/start", methods=["POST"])
def api_enroll_start():
    data   = request.json
    name   = data.get("name", "").strip()
    dept   = data.get("dept", "General").strip()
    cargo  = data.get("cargo", "").strip()
    emp_id = data.get("id")

    if not name:
        return jsonify({"ok": False, "message": "El nombre es requerido"})

    with state_lock:
        if not scanner_state["active"]:
            return jsonify({"ok": False, "message": "El agente local no está conectado"})
        scanner_state["mode"]             = "enroll"
        scanner_state["enroll_id"]        = emp_id
        scanner_state["enroll_name"]      = [name, dept, cargo]
        scanner_state["enroll_templates"] = 0
        scanner_state["status"]           = "scanning"
        scanner_state["message"]          = "Pon el dedo 3 veces — captura 1/3"

    return jsonify({"ok": True})

@app.route("/api/enroll/cancel", methods=["POST"])
def api_enroll_cancel():
    with state_lock:
        scanner_state["mode"]             = "punch"
        scanner_state["enroll_templates"] = 0
        scanner_state["status"]           = "ready"
        scanner_state["message"]          = "Lector listo — pon tu dedo"
    return jsonify({"ok": True})

@app.route("/api/employee/delete/<int:emp_id>", methods=["DELETE"])
def api_delete_emp(emp_id):
    db_query("DELETE FROM employees WHERE id=%s", (emp_id,), commit=True)
    return jsonify({"ok": True})

@app.route("/api/attendance")
def api_attendance():
    date_from = request.args.get("from", datetime.now(TZ_EC).date().isoformat())
    date_to   = request.args.get("to",   datetime.now(TZ_EC).date().isoformat())
    emp_id    = request.args.get("employee_id")
    local_id  = request.args.get("local")

    date_to_end = date_to + " 23:59:59"
    q = "SELECT * FROM attendance WHERE timestamp >= %s AND timestamp <= %s"
    p = [date_from, date_to_end]
    if emp_id:
        q += " AND employee_id=%s"
        p.append(emp_id)
    if local_id:
        # Busca por local O por dept para no perder registros donde el agente
        # guardó el nombre del local de forma diferente (ej: "Oficina Principal"
        # vs "Vermont Plaza") pero el dept sí coincide.
        q += " AND (TRIM(local)=TRIM(%s) OR TRIM(dept)=TRIM(%s))"
        p.append(local_id)
        p.append(local_id)
    q += " ORDER BY timestamp DESC"

    print(f"[DEBUG attendance] from={date_from} to={date_to_end} emp={emp_id} local={local_id}")
    print(f"[DEBUG attendance] SQL: {q}")
    print(f"[DEBUG attendance] params: {p}")

    rows = db_query(q, p, fetchall=True) or []

    print(f"[DEBUG attendance] rows returned: {len(rows)}")
    if rows:
        timestamps = [r.get("timestamp","") for r in rows]
        print(f"[DEBUG attendance] min_ts={min(timestamps)}  max_ts={max(timestamps)}")

    return jsonify([dict(r) for r in rows])

@app.route("/api/debug/attendance")
def api_debug_attendance():
    """Diagnóstico: muestra min/max fechas, valores de 'local' existentes y
    cuántos registros hay por local en el rango de fechas solicitado."""
    date_from = request.args.get("from", "")
    date_to   = request.args.get("to",   "")
    rows = db_query("SELECT id, timestamp FROM attendance ORDER BY id DESC LIMIT 20", fetchall=True) or []
    mn   = db_query("SELECT MIN(timestamp) as mn, MAX(timestamp) as mx, COUNT(*) as total FROM attendance", fetchone=True) or {}

    # Valores únicos de local en toda la tabla
    local_rows = db_query(
        "SELECT COALESCE(local, dept) as local_val, COUNT(*) as cnt FROM attendance GROUP BY local_val ORDER BY local_val",
        fetchall=True
    ) or []

    # Si se pasó rango, también muestra por rango
    range_locals = []
    if date_from and date_to:
        date_to_end = date_to + " 23:59:59"
        range_locals = db_query(
            "SELECT COALESCE(local, dept) as local_val, dept, COUNT(*) as cnt FROM attendance "
            "WHERE timestamp >= %s AND timestamp <= %s "
            "GROUP BY local_val, dept ORDER BY local_val",
            (date_from, date_to_end), fetchall=True
        ) or []

    return jsonify({
        "total": mn.get("total"),
        "min_timestamp": mn.get("mn"),
        "max_timestamp": mn.get("mx"),
        "locales_en_bd": [dict(r) for r in local_rows],
        "locales_en_rango": [dict(r) for r in range_locals],
        "last_20": [dict(r) for r in rows]
    })

@app.route("/api/employees/list")
def api_employees_list():
    dept = request.args.get("dept", "").strip()
    # Optimizado: no trae el blob template (pesado), solo calcula has_template en SQL
    if dept:
        rows = db_query(
            "SELECT id, name, dept, cargo, (template IS NOT NULL AND LENGTH(template) > 0) AS has_template "
            "FROM employees WHERE dept=%s ORDER BY name", (dept,), fetchall=True) or []
    else:
        rows = db_query(
            "SELECT id, name, dept, cargo, (template IS NOT NULL AND LENGTH(template) > 0) AS has_template "
            "FROM employees ORDER BY name", fetchall=True) or []
    # Normalizar has_template a bool (MySQL devuelve 0/1, SQLite 0/1)
    result = []
    for r in rows:
        d = dict(r)
        d["has_template"] = bool(d.get("has_template"))
        result.append(d)
    return jsonify(result)

@app.route("/api/export/csv")
def api_export():
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    date_from  = request.args.get("from", datetime.now(TZ_EC).date().isoformat())
    date_to    = request.args.get("to",   datetime.now(TZ_EC).date().isoformat())
    emp_id_csv = request.args.get("employee_id")
    local_csv  = request.args.get("local")

    date_to_end = date_to + " 23:59:59"
    q_csv = "SELECT id, employee_id, employee_name, dept, local, punch_type, timestamp FROM attendance WHERE timestamp >= %s AND timestamp <= %s"
    p_csv = [date_from, date_to_end]
    if emp_id_csv:
        q_csv += " AND employee_id=%s"; p_csv.append(emp_id_csv)
    if local_csv:
        q_csv += " AND (TRIM(local)=TRIM(%s) OR TRIM(dept)=TRIM(%s))"; p_csv.append(local_csv); p_csv.append(local_csv)
    q_csv += " ORDER BY employee_name, timestamp"
    try:
        rows = db_query(q_csv, p_csv, fetchall=True) or []
    except Exception as e:
        import traceback
        print(f"[EXPORT ERROR] db_query failed: {e}", flush=True)
        print(traceback.format_exc(), flush=True)
        return jsonify({"ok": False, "message": f"Error en consulta: {e}"}), 500

    # ── Agrupar por empleado + sesión (termina 04:00 AM día siguiente) ─────
    # Una sesión inicia con la primera Entrada del empleado y termina a las
    # 04:00 AM del día siguiente a esa primera Entrada. Las marcaciones
    # que caigan dentro de esa ventana pertenecen a la misma sesión.
    grupos = defaultdict(lambda: {"E": None, "S": None})
    employees_in_rows = sorted(set(r["employee_name"] for r in rows))

    for name in employees_in_rows:
        emp_rows = [r for r in rows if r["employee_name"] == name]
        entradas = sorted(
            [r for r in emp_rows if r["punch_type"] == "Entrada"],
            key=lambda r: r["timestamp"]
        )
        for entrada in entradas:
            entrada_dt = datetime.strptime(entrada["timestamp"], "%Y-%m-%d %H:%M:%S")
            # session_end = 04:00 AM del día siguiente a la 1ª Entrada
            session_end = entrada_dt.replace(hour=4, minute=0, second=0, microsecond=0) \
                                 + timedelta(days=1)
            session_key = (name, entrada["timestamp"][:10])
            g = grupos[session_key]
            g["E"] = entrada["timestamp"]
            for r in emp_rows:
                if r["id"] == entrada["id"]:
                    continue
                try:
                    r_dt = datetime.strptime(r["timestamp"], "%Y-%m-%d %H:%M:%S")
                except Exception:
                    continue
                if entrada_dt <= r_dt < session_end:
                    if r["punch_type"] == "Salida":
                        if g["S"] is None or r["timestamp"] > g["S"]:
                            g["S"] = r["timestamp"]

    # ── Calcular horas/minutos totales del turno ──────────────────────────────
    def calc_horas_mins(g):
        if not (g["E"] and g["S"]):
            return 0, 0
        try:
            e = datetime.strptime(g["E"], "%Y-%m-%d %H:%M:%S")
            s = datetime.strptime(g["S"], "%Y-%m-%d %H:%M:%S")
            diff = (s - e).total_seconds()
            if diff <= 0:
                return 0, 0
        except Exception:
            return 0, 0
        h = int(diff // 3600)
        m = int((diff % 3600) // 60)
        return h, m

    # ── Construir Excel ───────────────────────────────────────────────────────
    wb = Workbook()
    ws = wb.active
    ws.title = "Asistencia"

    # Estilos
    hdr_font    = Font(name="Arial", bold=True, color="FFFFFF", size=10)
    hdr_fill    = PatternFill("solid", start_color="2B5DBE")
    cell_font   = Font(name="Arial", size=10)
    center_aln  = Alignment(horizontal="center", vertical="center")
    left_aln    = Alignment(horizontal="left",   vertical="center")
    thin_side   = Side(style="thin", color="CCCCCC")
    thin_border = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)

    alt_fill  = PatternFill("solid", start_color="EEF3FB")
    none_fill = PatternFill("solid", start_color="FFF3CD")  # amarillo si falta dato

    headers    = ["NOMBRE", "ENTRADA", "SALIDA", "HORAS", "MINUTOS"]
    col_widths = [28, 22, 22, 10, 10]

    # Fila de encabezado
    for col_idx, (hdr, width) in enumerate(zip(headers, col_widths), start=1):
        cell = ws.cell(row=1, column=col_idx, value=hdr)
        cell.font      = hdr_font
        cell.fill      = hdr_fill
        cell.alignment = center_aln
        cell.border    = thin_border
        ws.column_dimensions[get_column_letter(col_idx)].width = width
    ws.row_dimensions[1].height = 20

    # Filas de datos
    for row_idx, ((name, fecha), g) in enumerate(sorted(grupos.items()), start=2):
        horas, mins = calc_horas_mins(g)
        valores = [name, g["E"] or "", g["S"] or "", horas if horas else "", mins if (horas or mins) else ""]
        fill = alt_fill if row_idx % 2 == 0 else None
        for col_idx, val in enumerate(valores, start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=val)
            cell.font   = cell_font
            cell.border = thin_border
            # Nombre: alinear a la izquierda; resto centrado
            cell.alignment = left_aln if col_idx == 1 else center_aln
            # Celda vacía donde debería haber dato → fondo amarillo
            if col_idx in (2, 3) and val == "":
                cell.fill = none_fill
            elif fill:
                cell.fill = fill
        ws.row_dimensions[row_idx].height = 16

    # Fila de totales al final
    last_row = len(grupos) + 2
    total_h = sum(calc_horas_mins(g)[0] for g in grupos.values())
    total_m = sum(calc_horas_mins(g)[1] for g in grupos.values())
    # Normalizar minutos > 60
    total_h += total_m // 60
    total_m  = total_m  % 60

    tot_fill = PatternFill("solid", start_color="2B5DBE")
    for col_idx in range(1, 6):
        cell = ws.cell(row=last_row, column=col_idx)
        cell.fill   = tot_fill
        cell.font   = Font(name="Arial", bold=True, color="FFFFFF", size=10)
        cell.border = thin_border
        cell.alignment = center_aln
    ws.cell(row=last_row, column=1, value="TOTAL").alignment = center_aln
    ws.cell(row=last_row, column=4, value=total_h)
    ws.cell(row=last_row, column=5, value=total_m)
    ws.row_dimensions[last_row].height = 18

    # Freeze encabezado
    ws.freeze_panes = "A2"

    try:
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        return send_file(
            buf,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name=f"asistencia_{date_from}_{date_to}.xlsx"
        )
    except Exception as e:
        import traceback
        print(f"[EXPORT ERROR] save/send failed: {e}", flush=True)
        print(traceback.format_exc(), flush=True)
        return jsonify({"ok": False, "message": f"Error generando Excel: {e}"}), 500

@app.route("/api/attendance/manual", methods=["POST"])
def api_manual_punch():
    data          = request.json
    emp_id        = data.get("employee_id")
    punch_type    = data.get("punch_type", "Entrada")
    dept_override = data.get("dept", "").strip()
    ts            = data.get("timestamp", now_ec())

    emp = db_query("SELECT * FROM employees WHERE id=%s", (emp_id,), fetchone=True)
    if not emp:
        return jsonify({"ok": False, "message": "Colaborador no encontrado"})

    # ── Timestamp de la marcación actual ────────────────────────────────────
    try:
        curr_dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
    except Exception:
        curr_dt = datetime.now(TZ_EC)

    # ── Sesión: termina a las 04:00 AM del día siguiente a la 1ª Entrada ──
    # ── Bloquear marcación < 5 min desde la última del empleado ───────────
    last_in_day = db_query(
        "SELECT id, punch_type, timestamp FROM attendance "
        "WHERE employee_id=%s "
        "ORDER BY id DESC LIMIT 1",
        (emp_id,), fetchone=True)
    if last_in_day and last_in_day["timestamp"]:
        try:
            last_dt  = datetime.strptime(last_in_day["timestamp"], "%Y-%m-%d %H:%M:%S")
            diff_seg = abs((curr_dt - last_dt).total_seconds())
            if diff_seg < 300:
                return jsonify({"ok": False, "message": "Marcación ignorada: menos de 5 min desde la anterior"})
        except Exception:
            pass

    # Buscar la primera Entrada (inicio de la sesión activa)
    first_entrada = db_query(
        "SELECT id, timestamp FROM attendance "
        "WHERE employee_id=%s AND punch_type='Entrada' "
        "ORDER BY id DESC LIMIT 1",
        (emp_id,), fetchone=True)

    session_active = False
    if first_entrada is not None:
        first_dt = datetime.strptime(first_entrada["timestamp"], "%Y-%m-%d %H:%M:%S")
        # session_end = 04:00 AM del día siguiente a la 1ª Entrada
        session_end = first_dt.replace(hour=4, minute=0, second=0, microsecond=0) \
                             + timedelta(days=1)
        if curr_dt < session_end:
            session_active = True

    # Buscar si la sesión activa tiene Entrada y/o Salida
    has_entrada = False
    has_salida  = False
    salida_id   = None
    if session_active and first_entrada is not None:
        session_start = first_entrada["timestamp"]
        rows = db_query(
            "SELECT id, punch_type FROM attendance "
            "WHERE employee_id=%s AND timestamp >= %s "
            "ORDER BY id ASC",
            (emp_id, session_start), fetchall=True) or []
        has_entrada = any(r["punch_type"] == "Entrada" for r in rows)
        has_salida  = any(r["punch_type"] == "Salida"  for r in rows)
        salida_row  = next((r for r in rows if r["punch_type"] == "Salida"), None)
        salida_id   = salida_row["id"] if salida_row else None

    dept  = dept_override if dept_override else emp["dept"]
    local = data.get("local", emp.get("dept", ""))

    # Reglas marcación manual (cerradas):
    #   * Si eligió Entrada y ya tiene Entrada en la sesión → rechazo
    #   * Si eligió Entrada y NO tiene Entrada en la sesión → INSERT Entrada
    #   * Si eligió Salida y NO tiene Entrada en la sesión → rechazo
    #   * Si eligió Salida y solo tiene Entrada → INSERT Salida
    #   * Si eligió Salida y tiene Salida → UPDATE Salida
    if punch_type == "Entrada":
        if session_active and has_entrada:
            return jsonify({
                "ok":      False,
                "message": f"{emp['name']} ya tiene una Entrada registrada en esta sesión."
            })
        # INSERT Entrada (1ª marcación o nueva sesión)
        db_query(
            "INSERT INTO attendance (employee_id, employee_name, dept, local, punch_type, timestamp) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            (emp_id, emp["name"], dept, local, "Entrada", ts), commit=True)
        return jsonify({"ok": True, "action": "inserted", "punch_type": "Entrada"})

    # punch_type == "Salida"
    if not session_active or not has_entrada:
        return jsonify({
            "ok":      False,
            "message": f"{emp['name']} no tiene Entrada registrada en esta sesión. Marca la Entrada primero."
        })

    if has_salida:
        # UPDATE Salida
        db_query("UPDATE attendance SET timestamp=%s WHERE id=%s",
                 (ts, salida_id), commit=True)
        return jsonify({
            "ok":          True,
            "action":      "updated",
            "punch_type":  "Salida",
            "message":     f"Salida de {emp['name']} actualizada",
        })

    # INSERT Salida (1ª vez de la sesión)
    db_query(
        "INSERT INTO attendance (employee_id, employee_name, dept, local, punch_type, timestamp) "
        "VALUES (%s,%s,%s,%s,%s,%s)",
        (emp_id, emp["name"], dept, local, "Salida", ts), commit=True)
    return jsonify({"ok": True, "action": "inserted", "punch_type": "Salida"})



@app.route("/api/locales/list")
def api_locales_list():
    rows = db_query("SELECT id, nombre FROM locales ORDER BY nombre", fetchall=True) or []
    return jsonify([dict(r) for r in rows])

@app.route("/api/cargos/list")
def api_cargos_list():
    rows = db_query("SELECT id, nombre FROM cargos ORDER BY nombre", fetchall=True) or []
    return jsonify([dict(r) for r in rows])

@app.route("/api/employee/update_info", methods=["POST"])
def api_update_employee_info():
    data  = request.json
    emp_id = data.get("id")
    name  = data.get("name", "").strip()
    dept  = data.get("dept", "General").strip()
    cargo = data.get("cargo", "").strip()

    if not emp_id or not name:
        return jsonify({"ok": False, "message": "Datos incompletos"})

    db_query(
        "UPDATE employees SET name=%s, dept=%s, cargo=%s WHERE id=%s",
        (name, dept, cargo, emp_id), commit=True
    )
    return jsonify({"ok": True})

@app.route("/api/employee/create", methods=["POST"])
def api_create_employee():
    data  = request.json
    name  = data.get("name", "").strip()
    dept  = data.get("dept", "General").strip()
    cargo = data.get("cargo", "").strip()
    if not name:
        return jsonify({"ok": False, "message": "El nombre es requerido"})
    new_id = db_query(
        "INSERT INTO employees (name, dept, cargo, template) VALUES (%s,%s,%s,NULL)",
        (name, dept, cargo), commit=True
    )
    return jsonify({"ok": True, "employee_id": new_id})

# ─── API exclusiva del agente local ──────────────────────────────────────────
@app.route("/api/agent/heartbeat", methods=["POST"])
@require_agent_key
def agent_heartbeat():
    data       = request.json
    agent_name = data.get("name", "Agente")
    agent_id   = data.get("id", "default")

    with state_lock:
        scanner_state["active"]         = True
        scanner_state["agent_id"]       = agent_id
        scanner_state["agent_name"]     = agent_name
        scanner_state["agent_local"]    = agent_name   # el agente envía el local en el campo "name"
        scanner_state["last_heartbeat"] = time.time()
        if scanner_state["status"] == "offline":
            scanner_state["status"]  = "ready"
            scanner_state["message"] = "Lector listo — pon tu dedo"

        command = {
            "mode":        scanner_state["mode"],
            "enroll_id":   scanner_state["enroll_id"],
            "enroll_name": scanner_state["enroll_name"],
        }
    return jsonify({"ok": True, "command": command})


@app.route("/api/agent/disconnect", methods=["POST"])
@require_agent_key
def agent_disconnect():
    with state_lock:
        scanner_state["active"]         = False
        scanner_state["status"]         = "offline"
        scanner_state["message"]        = "Agente desconectado"
        scanner_state["last_heartbeat"] = 0
        scanner_state["agent_local"]    = "—"
    return jsonify({"ok": True})


@app.route("/api/agent/unknown_finger", methods=["POST"])
@require_agent_key
def agent_unknown_finger():
    with state_lock:
        scanner_state["status"]  = "error"
        scanner_state["message"] = "⚠ Huella no registrada en el sistema"
    demo_auto_ready()
    return jsonify({"ok": True})


@app.route("/api/agent/punch", methods=["POST"])
@require_agent_key
def agent_punch():
    data  = request.json
    fid   = data["employee_id"]
    score = data.get("score", 100)
    ts    = data.get("timestamp", now_ec())
    # El servidor deduce automáticamente Entrada vs Salida según el estado
    # de la jornada del empleado. El cliente puede enviar punch_type pero
    # se ignora (compatibilidad con versiones anteriores).

    emp = db_query("SELECT * FROM employees WHERE id=%s", (fid,), fetchone=True)
    if not emp:
        with state_lock:
            scanner_state["status"]  = "error"
            scanner_state["message"] = "⚠ Huella no registrada en el sistema"
        return jsonify({"ok": False, "message": "Colaborador no encontrado en servidor"})

    # ── Día calendario de la marcación actual ─────────────────────────────
    try:
        curr_dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
    except Exception:
        curr_dt = datetime.now(TZ_EC)

    # ── Buscar la última marcación del empleado (sin filtro de día) ───────
    last = db_query(
        "SELECT id, punch_type, timestamp FROM attendance "
        "WHERE employee_id=%s "
        "ORDER BY id DESC LIMIT 1",
        (fid,), fetchone=True)

    # ── Bloquear doble marcación en menos de 5 minutos ────────────────────────
    # En demo no se bloquea la doble marcación: permite mostrar Entrada y
    # Salida seguidas durante la presentación.
    if last and last["timestamp"] and not DEMO_MODE:
        try:
            last_dt  = datetime.strptime(last["timestamp"], "%Y-%m-%d %H:%M:%S")
            diff_seg = abs((curr_dt - last_dt).total_seconds())
            if diff_seg < 300:
                with state_lock:
                    scanner_state["status"]  = "warning"
                    scanner_state["message"] = f"⚠ Marcación ignorada — {emp['name']} (menos de 5 min)"
                return jsonify({
                    "ok":      False,
                    "message": f"Marcación ignorada: la última fue hace {int(diff_seg)}s (mín. 5 min)",
                    "employee": emp["name"]
                })
        except Exception:
            pass

    # ── Modelo de "sesión que termina a las 04:00 AM del día siguiente" ────
    # Una sesión inicia con la 1ª marcación (Entrada) y termina a las
    # 04:00 AM del día siguiente a esa primera marcación. Dentro de la
    # sesión:
    #   * 1ª marcación → INSERT Entrada
    #   * 2ª marcación (misma sesión) → INSERT Salida
    #   * 3ª+ marcaciones (misma sesión) → UPDATE Salida
    # Si la marcación cae a las 04:00 AM o después del día siguiente, se
    # inicia una nueva sesión con la siguiente marcación.

    # Buscar la primera marcación (Entrada) del empleado.
    first_entrada = db_query(
        "SELECT id, punch_type, timestamp FROM attendance "
        "WHERE employee_id=%s AND punch_type='Entrada' "
        "ORDER BY id DESC LIMIT 1",
        (fid,), fetchone=True)

    session_active = False
    if first_entrada is not None:
        first_dt = datetime.strptime(first_entrada["timestamp"], "%Y-%m-%d %H:%M:%S")
        # session_end = 04:00 AM del día siguiente a la 1ª Entrada
        session_end = first_dt.replace(hour=4, minute=0, second=0, microsecond=0) \
                             + timedelta(days=1)
        if curr_dt < session_end:
            session_active = True

    # Buscar la última marcación del empleado (sin filtro de día)
    last = db_query(
        "SELECT id, punch_type, timestamp FROM attendance "
        "WHERE employee_id=%s "
        "ORDER BY id DESC LIMIT 1",
        (fid,), fetchone=True)

    # ── Deducir Entrada/Salida automáticamente ──────────────────────────────
    #   * Sin marcaciones previas → INSERT Entrada (1ª de la historia)
    #   * Sin sesión activa (después de 04:00 del día siguiente) → INSERT Entrada
    #   * Sesión activa y última fue Entrada → INSERT Salida
    #   * Sesión activa y última fue Salida → UPDATE Salida
    rejected     = False
    reject_msg   = ""
    is_update    = False
    new_session  = False
    target_id    = None
    effective_type = "Entrada"

    if last is None:
        # 1ª marcación de la historia → Entrada
        pass
    elif not session_active:
        # Después de las 04:00 AM del día siguiente a la 1ª Entrada → nueva sesión
        new_session = True
    else:
        # Sesión activa
        if last["punch_type"] == "Entrada":
            # 1ª Salida de la sesión
            effective_type = "Salida"
        else:
            # 2ª+ Salida → UPDATE de la última Salida
            effective_type = "Salida"
            is_update     = True
            target_id     = last["id"]

    # ── (Fin de la deducción) ────────────────────────────────────────────

    local_biometrico = data.get("local", "") or scanner_state.get("agent_local", "") or emp["dept"]

    if rejected:
        with state_lock:
            scanner_state["status"]  = "warning"
            scanner_state["message"] = f"⚠ {reject_msg}"
        return jsonify({
            "ok":          False,
            "message":     reject_msg,
            "employee":    emp["name"],
        })

    if is_update:
        db_query(
            "UPDATE attendance SET timestamp=%s WHERE id=%s",
            (ts, target_id), commit=True)
        punch_type = "Salida"
    else:
        db_query(
            "INSERT INTO attendance (employee_id, employee_name, dept, local, punch_type, timestamp) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            (fid, emp["name"], emp["dept"], local_biometrico, effective_type, ts), commit=True)
        punch_type = effective_type

    event = {"id": fid, "name": emp["name"], "dept": emp["dept"],
             "local": local_biometrico,
             "punch_type": punch_type, "timestamp": ts, "score": score}

    if is_update:
        msg = f"↻ Salida actualizada — {emp['name']}\nbiometrico: {local_biometrico}"
    elif new_session:
        msg = f"✓ Nueva sesión — {emp['name']}\nbiometrico: {local_biometrico}"
    else:
        icon = "✓ Entrada" if punch_type == "Entrada" else "✓ Salida"
        msg  = f"{icon} — {emp['name']}\nbiometrico: {local_biometrico}"
    with state_lock:
        scanner_state["status"]     = "success"
        scanner_state["message"]    = msg
        scanner_state["last_event"] = event

    demo_auto_ready()
    return jsonify({
        "ok":          True,
        "punch_type":  punch_type,
        "employee":    emp["name"],
        "updated":     is_update,
        "new_session": new_session,
    })


@app.route("/api/agent/enroll_done", methods=["POST"])
@require_agent_key
def agent_enroll_done():
    data         = request.json
    name         = data["name"]
    dept         = data.get("dept", "General")
    cargo        = data.get("cargo", "")
    template_b64 = data["template"]
    emp_id       = data.get("employee_id")

    import base64
    template_bytes = base64.b64decode(template_b64)

    if emp_id:
        db_query("UPDATE employees SET template=%s WHERE id=%s", (template_bytes, emp_id), commit=True)
        new_id = emp_id
    else:
        # cargo puede venir directo o desde enroll_name
        if not cargo and scanner_state.get("enroll_name") and len(scanner_state["enroll_name"]) >= 3:
            cargo = scanner_state["enroll_name"][2]
        new_id = db_query(
            "INSERT INTO employees (name, dept, cargo, template) VALUES (%s,%s,%s,%s)",
            (name, dept, cargo, template_bytes), commit=True)

    with state_lock:
        scanner_state["status"]           = "success"
        scanner_state["mode"]             = "punch"
        scanner_state["message"]          = f"✓ Huella de {name} registrada"
        scanner_state["last_event"]       = {"enrolled": name, "id": new_id}
        scanner_state["enroll_templates"] = 3
        scanner_state["enroll_id"]        = None
        scanner_state["enroll_name"]      = None

    return jsonify({"ok": True, "employee_id": new_id})


@app.route("/api/agent/enroll_progress", methods=["POST"])
@require_agent_key
def agent_enroll_progress():
    data = request.json
    step = data.get("step", 1)
    msg  = data.get("message", f"Huella {step}/3 capturada")

    with state_lock:
        scanner_state["enroll_templates"] = step
        scanner_state["message"]          = msg
        scanner_state["status"]           = "scanning"

    return jsonify({"ok": True})


@app.route("/api/agent/templates")
@require_agent_key
def agent_get_templates():
    rows = db_query("SELECT id, template FROM employees", fetchall=True) or []

    import base64
    result = []
    for r in rows:
        tpl = r.get("template")
        if tpl is None:
            continue
        try:
            b = bytes(tpl)
        except Exception:
            try:
                b = bytes(tpl) if not isinstance(tpl, str) else tpl.encode()
            except Exception:
                continue
        if len(b) == 0:
            continue
        result.append({"id": r["id"], "template": base64.b64encode(b).decode()})
    return jsonify(result)


# ─── Arranque ─────────────────────────────────────────────────────────────────
with app.app_context():
    init_db()
    if DEMO_MODE:
        seed_demo()
    if USE_POSTGRES:
        db_label = "PostgreSQL (DATABASE_URL)"
    elif USE_MYSQL:
        db_label = f"MySQL ({MYSQL_DB}@{MYSQL_HOST})"
    else:
        db_label = f"SQLite ({DB})"
    print(f"  Base de datos: {db_label}")
    if DEMO_MODE:
        print(f"  [DEMO] Modo demostración activo — empresa: {DEMO_COMPANY}")

threading.Thread(target=agent_timeout_loop, daemon=True).start()

# ─── Corrección masiva de campo 'local' ──────────────────────────────────────
@app.route("/api/admin/fix-local", methods=["POST"])
def api_fix_local():
    """Permite corregir en masa el campo 'local' de registros que tienen un
    valor incorrecto. Solo accesible con API key de admin.
    Body JSON: { "local_incorrecto": "Oficina Principal",
                 "local_correcto":   "Vermont Plaza",
                 "date_from": "2026-05-07",   (opcional)
                 "date_to":   "2026-05-14" }  (opcional)
    """
    data           = request.get_json(force=True) or {}
    local_wrong    = (data.get("local_incorrecto") or "").strip()
    local_right    = (data.get("local_correcto")   or "").strip()
    date_from      = (data.get("date_from") or "").strip()
    date_to        = (data.get("date_to")   or "").strip()

    if not local_wrong or not local_right:
        return jsonify({"ok": False, "message": "Faltan local_incorrecto o local_correcto"}), 400

    q = "UPDATE attendance SET local=%s WHERE TRIM(local)=TRIM(%s)"
    p = [local_right, local_wrong]
    if date_from:
        q += " AND timestamp >= %s"; p.append(date_from)
    if date_to:
        q += " AND timestamp <= %s"; p.append(date_to + " 23:59:59")

    try:
        if USE_MYSQL or USE_POSTGRES:
            conn = get_db()
            with conn.cursor() as cur:
                cur.execute(q, p)
                affected = cur.rowcount
            conn.commit()
            conn.close()
        else:
            import sqlite3
            con = sqlite3.connect(DB)
            cur = con.execute(q.replace("%s", "?"), p)
            affected = cur.rowcount
            con.commit()
            con.close()
        return jsonify({"ok": True, "registros_actualizados": affected,
                        "de": local_wrong, "a": local_right})
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500


@app.route("/api/admin/clear-attendance", methods=["POST"])
def api_clear_attendance():
    """Elimina marcaciones de un empleado en un rango de fechas.
    Solo para admin. Útil para limpiar datos de prueba.
    Body JSON: {
        "employee_id":  35,         # requerido
        "date_from":    "2026-08-10" # opcional (default: 1970-01-01)
        "date_to":      "2026-08-12" # opcional (default: hoy)
    }
    """
    data       = request.get_json(force=True) or {}
    emp_id     = data.get("employee_id")
    date_from  = (data.get("date_from") or "1970-01-01").strip()
    date_to    = (data.get("date_to")   or datetime.now(TZ_EC).date().isoformat()).strip()

    if not emp_id:
        return jsonify({"ok": False, "message": "Falta employee_id"}), 400

    emp = db_query("SELECT id, name FROM employees WHERE id=%s", (emp_id,), fetchone=True)
    if not emp:
        return jsonify({"ok": False, "message": f"Colaborador id={emp_id} no existe"}), 404

    try:
        if USE_MYSQL or USE_POSTGRES:
            conn = get_db()
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) AS cnt FROM attendance "
                    "WHERE employee_id=%s AND timestamp >= %s AND timestamp <= %s",
                    (emp_id, date_from, date_to + " 23:59:59"))
                cnt = cur.fetchone()["cnt"]
                cur.execute(
                    "DELETE FROM attendance "
                    "WHERE employee_id=%s AND timestamp >= %s AND timestamp <= %s",
                    (emp_id, date_from, date_to + " 23:59:59"))
                affected = cur.rowcount
            conn.commit()
            conn.close()
        else:
            con = sqlite3.connect(DB)
            cur = con.execute(
                "SELECT COUNT(*) FROM attendance "
                "WHERE employee_id=? AND timestamp >= ? AND timestamp <= ?",
                (emp_id, date_from, date_to + " 23:59:59"))
            cnt = cur.fetchone()[0]
            cur = con.execute(
                "DELETE FROM attendance "
                "WHERE employee_id=? AND timestamp >= ? AND timestamp <= ?",
                (emp_id, date_from, date_to + " 23:59:59"))
            affected = cur.rowcount
            con.commit()
            con.close()
        return jsonify({
            "ok":              True,
            "employee_id":     emp_id,
            "employee_name":   emp["name"],
            "registros_encontrados": cnt,
            "registros_eliminados":   affected,
            "rango":           {"desde": date_from, "hasta": date_to},
        })
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"\n{'='*50}")
    print(f"  Servidor en http://0.0.0.0:{port}")
    print(f"  AGENT_API_KEY = {AGENT_API_KEY}")
    print(f"  DB: {'PostgreSQL' if USE_POSTGRES else ('MySQL' if USE_MYSQL else 'SQLite (local)')}")
    print(f"  DEMO_MODE = {DEMO_MODE}")
    print(f"{'='*50}\n")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)

