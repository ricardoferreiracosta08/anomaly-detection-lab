FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    fastapi==0.115.0 \
    uvicorn[standard]==0.30.0 \
    prometheus-client==0.21.0

COPY main.py .

EXPOSE 8000

# 1 worker por pod: com 2+ workers cada processo tem seu próprio registro do
# prometheus_client e cada scrape lê um processo diferente → contadores "voltam",
# rate() vê resets falsos e a taxa/latência exportada fica distorcida.
# A escala horizontal é responsabilidade do HPA (mais pods), não de mais workers.
ENV UVICORN_WORKERS=1
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port 8000 --workers ${UVICORN_WORKERS}"]
