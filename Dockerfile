FROM mcr.microsoft.com/playwright/python:v1.61.0-noble

# Os comparadores recusam o Chromium headless, entao o container roda o
# navegador em modo janela dentro de um display virtual (Xvfb). Nao ha
# falsificacao de identidade: e um Chromium real desenhando numa tela que
# ninguem ve.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    RPA_HEADLESS=false \
    REQUEST_DELAY_SECONDS=3.0

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir .

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /dados \
    && chown appuser:appuser /dados
USER appuser

VOLUME ["/dados"]

ENTRYPOINT ["xvfb-run", "-a", "--server-args=-screen 0 1440x1000x24", "copercitrus-price"]
CMD ["--help"]
