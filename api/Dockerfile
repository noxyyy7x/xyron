FROM python:3.12-slim
WORKDIR /srv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
RUN useradd -r -u 10001 xyronapi
USER xyronapi
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
