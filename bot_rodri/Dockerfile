# Imagen con Python 3.12 + todas las dependencias del bot ya instaladas,
# para que el workflow de GitHub Actions no tenga que hacer "pip install"
# en cada ejecución (eso es lo que consumía los ~20s extra).
#
# Se reconstruye solo cuando cambia requirements.txt (ver
# .github/workflows/build_bot_image.yml), no en cada corrida del bot.
FROM python:3.12-slim

# git: lo necesita el workflow para el commit/push de state_rodri.json
# (python:3.12-slim no lo trae instalado por defecto).
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
