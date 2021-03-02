FROM python:3.9.2-slim-buster

ARG ROOT=/app
ARG POETRY_VERSION=1.1.4

WORKDIR ${ROOT}

COPY pyproject.toml poetry.lock covers.py ./

RUN pip install poetry==${POETRY_VERSION} \
  && poetry config virtualenvs.create false \
  && poetry install

ENTRYPOINT ["python", "covers.py"]
