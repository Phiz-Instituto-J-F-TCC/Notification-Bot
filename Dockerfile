FROM python:3.12-slim

# Impede criação de .pyc e força logs imediatos
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Diretório da aplicação
WORKDIR /app

# Copia as dependências primeiro para aproveitar o cache do Docker
COPY requirements.txt .

# Instala dependências
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copia o código da aplicação
COPY . .

# Porta utilizada pelo Render
EXPOSE 10000

# Inicializa FastAPI com Uvicorn
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-10000}"]
