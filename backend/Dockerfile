# Use Python 3.11 slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies (if needed for geopy, pillow, shapely)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better layer caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Chromium needs OS-level shared libraries (libnss3, libgbm1, fonts, etc.) that
# this slim base image doesn't have — `pip install` alone never provides these.
# `playwright install-deps` installs just those system libraries via apt (the
# `playwright` package is already present as a CloakBrowser dependency).
RUN python -m playwright install-deps chromium

# CloakBrowser ships its OWN patched Chromium binary (fingerprint-evasion
# patches), separate from Playwright's stock browser — `cloakbrowser install`
# downloads it. Without this, every browser launch fails at runtime.
RUN python -m cloakbrowser install

# Copy the rest of the backend code
COPY . .

# Expose port 8000
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/').read()"

# Run the server
CMD ["python", "server.py"]
