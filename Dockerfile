FROM python:3.10-slim

WORKDIR /app

# Install system dependencies for psycopg2 and scientific packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy package files
COPY pyproject.toml VERSION README.md ./
COPY tica/ ./tica/
COPY btjd/ ./btjd/
COPY wcs_build/ ./wcs_build/
COPY bin/ ./bin/

# Install package
RUN pip install --no-cache-dir -e .

# Default command
CMD ["python", "-c", "import tica; print(f'TICA version: {tica.version}')"]
