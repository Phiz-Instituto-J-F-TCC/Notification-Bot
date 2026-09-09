# API de Notificações Phiz

Web Service que recebe uma notificação em JSON, cria um job para cada CPF,
consulta o telefone na API acadêmica e envia a mensagem pelo canal da Phiz.

## Render

- Runtime: Python
- Build Command: `pip install -r requirements.txt`
- Start Command: `gunicorn main:app --bind 0.0.0.0:$PORT --workers 1 --threads 8 --timeout 180`
- Health Check Path: `/health`

Configure as variáveis do arquivo `.env.example` no painel do Render. Não envie
um arquivo `.env` com credenciais para o repositório.

O projeto usa um processo Gunicorn porque a fila e a deduplicação ainda ficam
em memória. Para múltiplas instâncias, substitua a fila por Redis/RQ, Celery ou
outro serviço persistente.

## Criar notificação

`POST /webhook/aluno-notificacao`

Headers:

```text
Authorization: API-Key SUA_CHAVE
Content-Type: application/json
```

Exemplo usando a mensagem diretamente no JSON:

```json
{
  "notificationId": "notificacao-001",
  "topic": "Aviso importante",
  "message": "Esta mensagem será enviada aos alunos.",
  "students": [
    {"cpf": "522.839.868-69"},
    {"cpf": "420.703.128-81"}
  ]
}
```

Também é possível trocar `message` por `content` contendo uma URL HTTPS. Nesse
caso, o domínio precisa estar em `CONTENT_ALLOWED_HOSTS`.

A resposta `202` contém um `job_id` para cada CPF. Ela confirma que os jobs
foram enfileirados, não que as mensagens já chegaram aos celulares.

## Consultar job

`GET /jobs/{job_id}` usando o mesmo header `Authorization`.

Estados possíveis: `PENDING`, `LOOKING_UP_PHONE`, `SENDING`, `QUEUED`,
`ACCEPTED` ou `ERROR`.

## Saúde

`GET /health`

Retorna `200` quando todas as variáveis obrigatórias estão configuradas e `503`
quando alguma está faltando.
