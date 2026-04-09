FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY main.py .

# Data volume mount point
RUN mkdir -p /data

EXPOSE 8096

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8096"]
