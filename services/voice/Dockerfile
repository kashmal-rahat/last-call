FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY shared/ /app/shared/
COPY services/voice/ /app/services/voice/

RUN pip install --no-cache-dir /app/shared /app/services/voice

WORKDIR /app/services/voice

ENV PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
