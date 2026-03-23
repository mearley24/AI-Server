FROM python:3.12-slim

WORKDIR /app

# Install system deps needed by cryptography, ccxt, and other compiled packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libffi-dev \
    libssl-dev \
    wget \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && python -c "from cryptography.hazmat.primitives import serialization; print('cryptography OK')" \
    && python -c "import httpx; print('httpx OK')" \
    && python -c "import ccxt; print('ccxt OK')"

COPY . .

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8430

CMD ["python", "-m", "src.main"]
