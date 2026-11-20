FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    GREETING="Hello, Docker!" \
    STORAGE=sqlite \
    DATA_FILE=/data/counter.db \
    REDIS_URL=redis://redis:6379/0

WORKDIR /app

COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/app.py .

RUN useradd -m -u 1000 appuser && \
    mkdir -p /data && \
    chown -R 1000:1000 /app /data

USER 1000:1000

EXPOSE 8000

CMD ["python", "app.py"]
