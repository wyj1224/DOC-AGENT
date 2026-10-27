FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Override on servers that cannot reach PyPI quickly, e.g. https://mirrors.aliyun.com/pypi/simple/
ARG PIP_INDEX_URL=https://pypi.org/simple
COPY requirements.txt .
RUN pip install --index-url "$PIP_INDEX_URL" -r requirements.txt

COPY app ./app

RUN useradd --create-home appuser \
    && mkdir -p /app/data \
    && chown -R appuser /app/data
USER appuser

EXPOSE 8000
# The same image runs the API (default) and the worker (command override in compose).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
