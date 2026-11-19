# Demo — Sistema de Asistencia para Casa Perú

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/sistemaseddys-maker/casa-peru-demo)

> Repositorio: <https://github.com/sistemaseddys-maker/casa-peru-demo>
>
> **Deploy en 1 clic:** el botón crea el servicio web y la base PostgreSQL gratis
> en Render usando `render.yaml` (no hay que configurar nada a mano).

Copia de demostración del sistema de asistencia (marcación con huella, colaboradores
y registros) preparada para que **Casa Perú** la pruebe sin instalar nada.

> **No requiere el lector ZK9500 ni el DigitalPersona.** En modo demo la huella se
> simula desde la pantalla, pero el flujo de negocio es exactamente el real:
> enrolamiento en 3 capturas, deducción automática de Entrada/Salida, reglas de
> sesión, reportes y exportación.

---

## 1. Qué incluye la demo

| Módulo | Qué puede probar Casa Perú |
|---|---|
| **Marcación** | Tocar la huella simulada, elegir colaborador y ver Entrada/Salida en vivo. |
| **Dedo no registrado** | Botón que muestra el rechazo real del sistema. |
| **Colaboradores** | Crear colaborador, registrar/actualizar huella (3 capturas simuladas), ver badge "Sin huella". |
| **Registros** | Historial de marcaciones por fecha, sede y colaborador, con exportación a Excel/CSV. |
| **Multi-sede** | Lima, Arequipa y Cusco con filtros por sede. |
| **Datos de ejemplo** | 16 colaboradores y ~10 días de marcaciones para que los reportes se vean reales. |

La demo **no pide contraseña** (en producción sí: `/api/verify_code`).

---

## 2. Ejecutar localmente

```powershell
cd CASA_PERU_DEMO
pip install -r requirements.txt

$env:DEMO_MODE="1"
$env:DEMO_COMPANY="Casa Perú"
$env:AGENT_API_KEY="demo-casa-peru-2026"
python app.py
```

Abrir: <http://localhost:5000>

La base local es `attendance.db` (SQLite). Para reiniciar los datos, borrar ese
archivo o usar el botón **"Restaurar datos de ejemplo"** del banner superior.

---

## 3. Desplegar gratis (Render + PostgreSQL)

### Opción A — Blueprint (recomendado)

1. Subir esta carpeta a un repositorio de GitHub.
2. En Render: **New → Blueprint** → elegir el repositorio.
3. Render lee `render.yaml` y crea:
   - Web service `casa-peru-demo` (plan free)
   - PostgreSQL `casa-peru-db` (plan free)
   - Variables `DEMO_MODE=1`, `DEMO_COMPANY=Casa Perú` y `DATABASE_URL` conectada.
4. Esperar el deploy y compartir la URL `https://casa-peru-demo.onrender.com`.

> El PostgreSQL free de Render tiene vigencia limitada (30 días). Para una demo
> permanente usar **Neon** (gratis, sin tarjeta) y pegar su cadena en `DATABASE_URL`.

### Opción B — Neon (base de datos permanente) + Render

1. Crear proyecto en <https://neon.tech> (free) y copiar la cadena
   `postgresql://...?sslmode=require`.
2. En Render: **New → Web Service** → repositorio.
   - Build: `pip install -r requirements.txt`
   - Start: `gunicorn app:app --workers 1 --threads 8 --bind 0.0.0.0:$PORT`
3. Variables de entorno:
   - `DEMO_MODE=1`
   - `DEMO_COMPANY=Casa Perú`
   - `AGENT_API_KEY=<una clave larga>`
   - `DATABASE_URL=<cadena de Neon>`
4. Deploy.

> **Importante:** usar **1 worker**. El estado del lector simulado se guarda en
> memoria del proceso; con varios workers la pantalla podría mostrar estados
> distintos.

### Opción C — Sin base externa (solo prueba rápida)

Render free no tiene disco persistente: si se usa SQLite, los datos se reinician
cuando el servicio se duerme o redeploya. Sirve para una reunión, no para dejar la
demo abierta varios días.

---

## 4. Guion sugerido para la reunión (5 minutos)

1. **Abrir la demo** y mostrar el banner: "lector simulado, sin hardware".
2. **Marcación → tocar la huella** → elegir "María Fernanda Quispe" → se registra
   la Salida (ya tenía Entrada de ejemplo). Mostrar la tarjeta "Última marcación".
3. **Probar dedo no registrado** → aparece "Huella no registrada en el sistema".
4. **Colaboradores → Registrar huella** → crear "Invitado Casa Perú" y mostrar las
   3 capturas simuladas y el badge verde de huella.
5. **Colaboradores** → mostrar los badges amarillos "Sin huella".
6. **Registros** → filtrar por sede y fecha, exportar a Excel.
7. Cerrar con: "Con el lector instalado, estos mismos pasos los hace el colaborador
   solo, sin pedir contraseña".

---

## 5. Diferencias con producción

- No hay agente local ni lector físico: el navegador simula las capturas
  (`X-Demo: 1`).
- No se aplica el bloqueo de 5 minutos entre marcaciones (para poder demostrar
  Entrada y Salida seguidas).
- Las plantillas de huella son aleatorias; no identifican personas reales.
- Los datos son de ejemplo y se pueden restaurar desde el banner.
