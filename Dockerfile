FROM python:3.12-slim

# Evita criação de arquivos .pyc e mantém logs imediatamente disponíveis
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Diretório da aplicação
WORKDIR /app

# Instala as dependências
COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copia o restante da aplicação
COPY . .

# Porta padrão local.
# No Render, a variável PORT será fornecida automaticamente.
ENV PORT=10000

# Inicia o Flask usando Gunicorn
CMD ["sh", "-c", "gunicorn main:app --bind 0.0.0.0:${PORT} --workers 1 --threads 8 --timeout 180"]
