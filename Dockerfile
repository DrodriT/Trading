# syntax=docker/dockerfile:1

# Imagen ligera con Python 3.11. Se instalan las dependencias en esta
# fase de build para que, en producción (GitHub Actions / cron-job.org
# / cualquier host), CADA EJECUCIÓN solo tenga que hacer `docker run`
# — sin `pip install` cada vez, que es justo lo que hace lento y frágil
# ejecutar esto en un runner efímero de CI.

FROM python:3.11-slim

# Evita que pip cachee ni pregunte nada, y que Python genere .pyc
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Copiamos primero SOLO requirements.txt para aprovechar la cache de
# capas de Docker: si el código cambia pero no las dependencias, esta
# capa no se reconstruye (build mucho más rápido).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Ahora sí, el resto del código
COPY . .

# El directorio de estado se sobreescribe en runtime con un volumen
# montado desde el host (ver workflow run-bot.yml) — lo que hay aquí
# es solo para que `docker run` funcione también sin volumen montado
# (por ejemplo en pruebas locales rápidas).
RUN mkdir -p state

# Ejecución única (no es un servidor de larga duración): igual que
# pensado para cron-job.org, el contenedor corre `main.py` una vez
# y termina. El scheduler (GitHub Actions / cron-job.org / cron local)
# es quien decide la periodicidad.
CMD ["python", "main.py"]
