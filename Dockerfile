FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install .
COPY src/ ./src/
RUN pip install -e . --no-deps

# Runs as root because it talks to the docker socket. The untrusted code runs
# in the sibling container as nobody with every capability dropped, which is
# where the boundary actually sits.
EXPOSE 8000
CMD ["uvicorn", "codegen.api:app", "--host", "0.0.0.0", "--port", "8000"]
