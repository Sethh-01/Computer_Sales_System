FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    APP_ENV=production \
    DATA_DIR=/var/lib/computer-sales

WORKDIR /app
COPY apps /app/apps
RUN mkdir -p /var/lib/computer-sales \
    && chown -R nobody:nogroup /var/lib/computer-sales /app

EXPOSE 8000
CMD ["python", "-m", "apps.api.runtime"]
