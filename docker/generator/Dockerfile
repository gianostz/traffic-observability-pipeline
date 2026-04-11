FROM python:3.11-slim

WORKDIR /app

COPY docker/generator/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/common/ src/common/
COPY src/generator/ src/generator/
COPY src/__init__.py src/__init__.py
COPY data/ data/

ENV SERVER_REGISTRY_PATH=/app/data/servers.csv
ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "src.generator.producer"]
