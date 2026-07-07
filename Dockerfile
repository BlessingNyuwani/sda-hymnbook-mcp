# syntax=docker/dockerfile:1.7
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 62752

CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "62752", "--proxy-headers", "--forwarded-allow-ips=*"]
