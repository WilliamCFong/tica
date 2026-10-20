# syntax=docker/dockerfile:1
#
# TICA container image. Dependencies are installed from hash-pinned lock files
# (see `make lock`), so a given TICA version always gets the same environment.
#
#   runtime: TICA installed as a package; calibration models are mounted at run time
#   dev:     editable install + test/lint tools + DVC, for working on a bind-mounted checkout

ARG PYTHON_VERSION=3.12

FROM python:${PYTHON_VERSION}-slim-bookworm AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore \
    MPLBACKEND=Agg \
    MPLCONFIGDIR=/tmp/matplotlib \
    XDG_CACHE_HOME=/tmp/.cache
WORKDIR /opt/tica


FROM base AS runtime
COPY requirements.lock ./
RUN pip install --require-hashes --no-deps -r requirements.lock
COPY pyproject.toml VERSION README.md LICENSE ./
COPY tica/ tica/
COPY btjd/ btjd/
COPY wcs_build/ wcs_build/
COPY bin/ bin/
RUN pip install --no-deps . \
    && pip check \
    && rm -rf build *.egg-info
ARG TICA_VERSION=unknown
LABEL org.opencontainers.image.title="tica" \
      org.opencontainers.image.version="${TICA_VERSION}" \
      org.opencontainers.image.source="https://github.com/mmfausnaugh/tica" \
      org.opencontainers.image.licenses="MIT"
WORKDIR /data
CMD ["bash"]


FROM base AS dev
# git is needed by DVC to read the .dvc metadata in the mounted checkout
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && git config --system --add safe.directory '*'
COPY requirements-dev.lock ./
RUN pip install --require-hashes --no-deps -r requirements-dev.lock
WORKDIR /app
COPY pyproject.toml VERSION README.md LICENSE ./
COPY tica/ tica/
COPY btjd/ btjd/
COPY wcs_build/ wcs_build/
COPY bin/ bin/
# Editable install: the checkout bind-mounted over /app is what gets imported.
# Scripts are copied at install time, so prefer the live ones from the checkout.
RUN pip install --no-deps -e . && pip check
ENV PATH="/app/bin:/app/btjd:${PATH}"
CMD ["bash"]
