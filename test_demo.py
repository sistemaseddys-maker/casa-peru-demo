"""Pruebas rápidas del modo demo (ejecutar con el servidor en :5001)."""
import base64
import os
import random
import sys

import requests

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

B = "http://127.0.0.1:5001"
H = {"X-Demo": "1"}


def main():
    cfg = requests.get(f"{B}/api/demo/config", timeout=5).json()
    print("config:", cfg)

    import time
    st = {}
    for _ in range(20):
        st = requests.get(f"{B}/api/scanner/status", timeout=5).json()
        if st.get("status") == "ready":
            break
        time.sleep(0.5)
    assert st["active"] and st["status"] == "ready", st
    print("status: OK ->", st["message"])

    emps = requests.get(f"{B}/api/employees/list", timeout=5).json()
    con = [e for e in emps if e["has_template"]]
    sin = [e for e in emps if not e["has_template"]]
    print(f"empleados: {len(emps)} | con huella {len(con)} | sin huella {len(sin)}")
    assert len(emps) == 16 and con and sin

    # Marcación simulada (mismo endpoint que usa el navegador)
    emp = con[0]
    r = requests.post(f"{B}/api/agent/punch", headers=H,
                      json={"employee_id": emp["id"], "local": emp["dept"]}, timeout=5)
    print("punch:", r.status_code, r.json())
    assert r.json()["ok"]

    # Dedo no registrado
    r = requests.post(f"{B}/api/agent/unknown_finger", headers=H, timeout=5)
    assert r.json()["ok"]
    st = requests.get(f"{B}/api/scanner/status", timeout=5).json()
    assert st["status"] == "error"
    print("unknown: OK ->", st["message"])

    # Enrolamiento simulado completo
    r = requests.post(f"{B}/api/enroll/start", headers=H,
                      json={"name": "Invitado Casa Perú",
                            "dept": "Casa Perú — Lima",
                            "cargo": "Invitado", "id": None}, timeout=5)
    assert r.json()["ok"], r.text
    for step in (1, 2, 3):
        r = requests.post(f"{B}/api/agent/enroll_progress", headers=H,
                          json={"step": step}, timeout=5)
        assert r.json()["ok"]
    tpl = base64.b64encode(bytes(random.getrandbits(8) for _ in range(768))).decode()
    r = requests.post(f"{B}/api/agent/enroll_done", headers=H,
                      json={"name": "Invitado Casa Perú",
                            "dept": "Casa Perú — Lima",
                            "cargo": "Invitado",
                            "employee_id": None,
                            "template": tpl}, timeout=5)
    assert r.json()["ok"], r.text
    nuevo = r.json()["employee_id"]
    emps = requests.get(f"{B}/api/employees/list", timeout=5).json()
    inv = [e for e in emps if e["id"] == nuevo]
    assert inv and inv[0]["has_template"], inv
    print("enroll: OK -> id", nuevo, inv[0]["name"])

    # Páginas
    for path in ("/", "/empleados", "/registros"):
        r = requests.get(B + path, timeout=10)
        assert r.status_code == 200, (path, r.status_code)
        if path == "/":
            assert "Simulador de huella" in r.text
    print("paginas: OK")

    # Reset de datos
    r = requests.post(f"{B}/api/demo/reset", headers=H, timeout=10)
    assert r.json()["ok"]
    print("reset: OK")

    print("\nTODO OK")


if __name__ == "__main__":
    main()
