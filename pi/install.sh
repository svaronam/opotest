#!/usr/bin/env bash
# Instala o actualiza OpoTest en la Raspberry (homelab2).
# Se lanza solo desde el script del PC, o a mano:  bash ~/opotest/pi/install.sh
set -euo pipefail

APP="$HOME/opotest"
USER_NAME="$(whoami)"
UNIT=/etc/systemd/system/opotest.service

# ---- Elección del puerto -------------------------------------------------
# 1) Si se pasa OPOTEST_PORT, se usa ese.  2) Si ya estaba instalado, se conserva el suyo.
# 3) Si no, el primero libre desde 8790, saltando los que estén escuchando ahora
#    y los que aparezcan en otros servicios (bots que solo corren a ratos).
listening_ports() {
  if command -v ss >/dev/null 2>&1; then
    ss -ltnH 2>/dev/null | awk '{print $4}' | sed -E 's/.*[:.]([0-9]+)$/\1/'
  else   # sin ss: se leen los sockets en escucha (estado 0A) del kernel
    awk 'FNR>1 && $4=="0A" {split($2,a,":"); print a[2]}' /proc/net/tcp /proc/net/tcp6 2>/dev/null \
      | while read -r h; do echo $((16#$h)); done
  fi | sort -un
}
port_taken() {
  local p=$1
  listening_ports | grep -qx "$p" && return 0
  grep -rlsE "(:|=|--port[ =]|-p[ =]?|PORT=)$p\b" /etc/systemd/system/*.service "$HOME"/*/.env "$HOME"/*/config* 2>/dev/null \
    | grep -v "opotest" | grep -q . && return 0
  docker ps --format '{{.Ports}}' 2>/dev/null | grep -qE "[:.]$p->" && return 0
  return 1
}

if [ -n "${OPOTEST_PORT:-}" ]; then
  PORT="$OPOTEST_PORT"
  if port_taken "$PORT" && ! grep -q -- "--port $PORT" "$UNIT" 2>/dev/null; then
    echo "AVISO: el puerto $PORT parece estar en uso por otro servicio."
  fi
elif [ -f "$UNIT" ] && grep -qoE -- "--port [0-9]+" "$UNIT"; then
  PORT="$(grep -oE -- "--port [0-9]+" "$UNIT" | awk '{print $2}')"
else
  PORT=8790
  while port_taken "$PORT"; do PORT=$((PORT + 1)); done
fi
echo "$PORT" > "$APP/port"

echo "== OpoTest: instalando en $(hostname) como $USER_NAME (puerto $PORT) =="
echo "   Puertos ya en uso en esta Pi:"
echo "   $(listening_ports | tr '\n' ' ')"

echo "-> Paquetes del sistema (te pedirá la contraseña de sudo)"
sudo apt-get update -qq
sudo apt-get install -y -qq python3-venv python3-pip poppler-utils tesseract-ocr tesseract-ocr-spa sqlite3 >/dev/null

echo "-> Entorno de Python"
if [ ! -d "$APP/venv" ]; then
  python3 -m venv "$APP/venv"
fi
"$APP/venv/bin/pip" install -q --upgrade pip
"$APP/venv/bin/pip" install -q "starlette>=0.40" "uvicorn>=0.30"

mkdir -p "$APP/temario/A1" "$APP/temario/A2" "$APP/server/var"

echo "-> Cargando preguntas y catálogo de temas"
cd "$APP/server"
OPOTEST_DATA="$APP/server/var" OPOTEST_TEMARIO="$APP/temario" "$APP/venv/bin/python" importer.py

echo "-> Servicios"
sudo tee /etc/systemd/system/opotest.service >/dev/null <<EOF
[Unit]
Description=OpoTest - servidor de tests
After=network-online.target
Wants=network-online.target

[Service]
User=$USER_NAME
WorkingDirectory=$APP/server
Environment=OPOTEST_DATA=$APP/server/var
Environment=OPOTEST_TEMARIO=$APP/temario
Environment=TZ=Europe/Madrid
ExecStart=$APP/venv/bin/uvicorn app:app --host 0.0.0.0 --port $PORT --workers 1
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/opotest-ocr.service >/dev/null <<EOF
[Unit]
Description=OpoTest - indexado y OCR del temario (baja prioridad)
After=opotest.service

[Service]
User=$USER_NAME
WorkingDirectory=$APP/server
Environment=OPOTEST_DATA=$APP/server/var
Environment=OPOTEST_TEMARIO=$APP/temario
Environment=OMP_THREAD_LIMIT=2
ExecStart=$APP/venv/bin/python ingest.py --watch
Nice=19
CPUQuota=150%
IOSchedulingClass=idle
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now opotest.service opotest-ocr.service
sudo systemctl restart opotest.service opotest-ocr.service

sleep 3
if curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null; then
  echo
  echo "== Listo =="
  TS_NAME="$(tailscale status --self --json 2>/dev/null | python3 -c 'import json,sys;print(json.load(sys.stdin)["Self"]["DNSName"].split(".")[0])' 2>/dev/null || hostname)"
  TS_IP="$(tailscale ip -4 2>/dev/null || true)"
  echo "En la app del móvil pon:  http://$TS_NAME:$PORT"
  [ -n "$TS_IP" ] && echo "   (o con la IP de Tailscale: http://$TS_IP:$PORT)"
  echo "Estado del OCR:  journalctl -u opotest-ocr -f"
else
  echo "El servidor no responde. Mira el log:  journalctl -u opotest -n 50"
  exit 1
fi
