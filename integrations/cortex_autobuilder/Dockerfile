FROM python:3.12-slim
WORKDIR /app
COPY integrations/cortex_autobuilder/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY . /app/
CMD ["python", "-m", "integrations.cortex_autobuilder.daemon"]
