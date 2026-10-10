FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Mine rules once at build time so the cache ships with the image and the
# first request doesn't pay the mining cost. Harmless if it's skipped (the
# app mines on startup either way).
RUN python -c "from arm.pipeline import pipeline; pipeline.load_data(); pipeline.run()"

ENV PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "gunicorn app:app --workers 1 --threads 4 --timeout 60 --bind 0.0.0.0:${PORT}"]
