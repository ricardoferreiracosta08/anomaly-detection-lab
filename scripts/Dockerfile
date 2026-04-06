FROM python:3.11-slim

WORKDIR /analysis

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY export_metrics.py .
COPY detectors.py .
COPY run_experiment.sh .
RUN chmod +x run_experiment.sh

ENTRYPOINT ["python"]
