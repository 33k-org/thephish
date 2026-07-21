FROM python:3.12-slim
WORKDIR /worker
COPY requirements.txt Ollama/
RUN pip install --no-cache-dir -r Ollama/requirements.txt
COPY . Ollama/
ENTRYPOINT ["python3", "Ollama/ollama_analyzer.py"]
