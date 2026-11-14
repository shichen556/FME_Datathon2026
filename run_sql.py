import os
import sys
from pathlib import Path
import pandas as pd
import requests

# Cargar variables desde .env (busca en carpeta actual o superior)
for env_path in [Path(".env"), Path("../.env")]:
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())
        break

API = os.environ.get("RAWTREE_API_URL", "https://api.rawtree.com")
TEAM = os.environ["TEAM_ID"]
API_KEY = os.environ["RAWTREE_API_KEY"]

http = requests.Session()
http.headers["Authorization"] = f"Bearer {API_KEY}"


def run_sql_file(sql_path: str) -> None:
    raw_sql = Path(sql_path).read_text(encoding="utf-8")

    # Eliminar líneas de comentario (--) y sustituir team_NN por tu TEAM_ID
    clean_lines = [
        line for line in raw_sql.splitlines()
        if not line.strip().startswith("--")
    ]
    cleaned_sql = "\n".join(clean_lines).replace("team_NN", TEAM)

    # Separar por ';' para enviar una consulta cada vez
    statements = [s.strip() for s in cleaned_sql.split(";") if s.strip()]

    for i, stmt in enumerate(statements, start=1):
        print(f"\n{'=' * 60}")
        print(f"QUERY {i}/{len(statements)}:")
        print(stmt[:120].replace("\n", " ") + ("..." if len(stmt) > 120 else ""))
        print("-" * 60)

        resp = http.post(f"{API}/v1/query", json={"sql": stmt}, timeout=60)
        if not resp.ok:
            print(f"ERROR HTTP {resp.status_code}: {resp.text}")
            continue

        data = resp.json().get("data", [])
        if not data:
            print("(0 filas devueltas)")
        else:
            df = pd.DataFrame(data)
            print(df.to_string(index=False))


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "starter/queries.sql"
    run_sql_file(target)