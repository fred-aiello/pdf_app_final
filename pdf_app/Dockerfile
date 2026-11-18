# Slim Python base image
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# System dependencies required by the app:
#   tesseract-ocr  -> OCR engine (subprocess "tesseract")
#   poppler-utils  -> pdftoppm, renders PDF pages to images for OCR
#   ghostscript    -> PDF processing fallback
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        poppler-utils \
        ghostscript \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (better layer caching)
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copy application code and assets
COPY app.py .
COPY userstore.py .
COPY logo1.png logo3.png ./

# Admin helper to enroll TOTP MFA secrets
COPY enroll_totp.py .

# Run as an unprivileged user, with a writable data dir for the user store
RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /app/data \
    && chown appuser:appuser /app/data
USER appuser

EXPOSE 8501

# Persist the JSON user store across container restarts:
#   docker run -p 8501:8501 -v pdf_data:/app/data pdf_app
VOLUME ["/app/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')" || exit 1

CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]