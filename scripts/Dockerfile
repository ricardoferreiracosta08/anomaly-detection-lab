FROM python:3.11-slim

WORKDIR /analysis

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# PyTorch só CPU (LSTM, 6º detector): o índice /whl/cpu evita as bibliotecas CUDA (vários GB)
RUN pip install --no-cache-dir torch==2.5.1 --index-url https://download.pytorch.org/whl/cpu

# Todos os scripts de análise + detector online (mesma imagem no notebook e no cluster)
COPY *.py ./

# Matplotlib sem display; usuário sem privilégios dentro do cluster
ENV MPLBACKEND=Agg PYTHONUNBUFFERED=1
RUN useradd -u 10001 -m analysis
USER 10001

ENTRYPOINT ["python"]
