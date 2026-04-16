FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/src

ARG TORCH_VERSION=2.10.0
ARG TORCH_CPU_INDEX_URL=https://download.pytorch.org/whl/cpu

WORKDIR /app

COPY requirements.docker.txt ./
RUN pip install --upgrade pip \
    && pip install "torch==${TORCH_VERSION}" --index-url "${TORCH_CPU_INDEX_URL}" \
    && pip install -r requirements.docker.txt

COPY . .

CMD ["python", "-B", "scripts/task4_repl.py"]
