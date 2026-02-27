FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY dtools_client.py .
COPY dtools_server.py .

EXPOSE 5050

CMD ["python", "dtools_server.py"]
