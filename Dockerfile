FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY manage.py ./

RUN pip install --no-cache-dir .

CMD ["python", "-m", "tracereview_web.worker"]
