FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi uvicorn sqlalchemy
COPY main.py ./main.py
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"]
