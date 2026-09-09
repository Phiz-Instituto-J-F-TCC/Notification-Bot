import hmac
import os
import re
import threading
from html import unescape
from typing import Any
from urllib.parse import urlsplit

import requests
from fastapi import FastAPI, HTTPException, Security, status
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, ConfigDict, Field

import config
from outbound_queue import QueueFullError, outbound_queue


class StudentRequest(BaseModel):
    cpf: str = Field(
        min_length=11,
        max_length=14,
        examples=["522.839.868-69"],
        description="CPF do aluno. Pode chegar formatado ou somente com dígitos.",
    )


class NotificationRequest(BaseModel):
    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={
            "example": {
                "notificationId": "notificacao-001",
                "topic": "Aviso importante",
                "message": "Esta mensagem será enviada aos alunos.",
                "category": {"categoryId": 6, "name": "SCHEDULE"},
                "alert": False,
                "important": True,
                "shippingTime": "2026-09-09T12:00:00.000Z",
                "students": [
                    {"cpf": "522.839.868-69"},
                    {"cpf": "420.703.128-81"},
                ],
            }
        },
    )

    notificationId: str = Field(
        min_length=1,
        max_length=200,
        description="Identificador único usado para impedir envios duplicados.",
    )
    topic: str = Field(default="Notificação", min_length=1, max_length=300)
    message: str | None = Field(
        default=None,
        min_length=1,
        description="Texto da mensagem. Use message ou content.",
    )
    content: str | None = Field(
        default=None,
        description="URL HTTPS de um HTML. Use content ou message.",
    )
    students: list[StudentRequest] = Field(min_length=1)
    category: dict[str, Any] | None = None
    alert: bool | None = None
    important: bool | None = None
    shippingTime: str | None = None


class JobCreated(BaseModel):
    cpf_final: str
    job_id: str
    status: str


class ProcessingError(BaseModel):
    cpf_final: str
    erro: str


class NotificationResponse(BaseModel):
    received: bool
    notificationId: str
    status: str
    jobs: list[JobCreated]
    errors: list[ProcessingError]


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    cpf_final: str
    message_id: str | None = None
    telefone_final: str | None = None
    erro: str | None = None


class HealthResponse(BaseModel):
    status: str
    service: str
    missing_settings: list[str]


app = FastAPI(
    title="API de Notificações Phiz",
    summary="Envio de notificações para alunos por CPF",
    description=(
        "Recebe uma notificação com um ou vários CPFs, cria jobs assíncronos, "
        "consulta os telefones na API acadêmica e envia as mensagens pela Phiz.\n\n"
        "Nos endpoints protegidos, clique em **Authorize** e informe "
        "`API-Key SUA_CHAVE`."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    openapi_tags=[
        {"name": "Sistema", "description": "Saúde e configuração da API."},
        {"name": "Notificações", "description": "Recebimento das notificações."},
        {"name": "Jobs", "description": "Acompanhamento dos envios assíncronos."},
    ],
)

api_key_header = APIKeyHeader(
    name="Authorization",
    scheme_name="InboundApiKey",
    description="Informe no formato: API-Key SUA_CHAVE",
    auto_error=False,
)

notification_jobs = {}
notification_jobs_lock = threading.Lock()


def verify_api_key(api_key: str | None = Security(api_key_header)):
    if not config.SECRETARY_INBOUND_API_KEY or not api_key:
        raise HTTPException(status_code=401, detail="unauthorized")

    expected = f"API-Key {config.SECRETARY_INBOUND_API_KEY}"
    if not hmac.compare_digest(api_key, expected):
        raise HTTPException(status_code=401, detail="unauthorized")
    return api_key


def _format_cpf(cpf):
    digits = re.sub(r"\D", "", str(cpf or ""))
    if len(digits) != 11:
        raise ValueError("CPF deve conter exatamente 11 dígitos")
    return f"{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}"


def _html_to_text(html):
    html = re.sub(
        r"<(script|style)\b[^>]*>.*?</\1>",
        "",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", html)).split())


def _get_content_text(content_url):
    parsed = urlsplit(content_url)
    hostname = (parsed.hostname or "").lower()

    if (
        parsed.scheme != "https"
        or not hostname
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or hostname not in config.CONTENT_ALLOWED_HOSTS
    ):
        raise ValueError(
            "content deve ser uma URL HTTPS de um domínio listado em "
            "CONTENT_ALLOWED_HOSTS"
        )

    response = requests.get(
        content_url,
        timeout=(5, config.CONTENT_TIMEOUT_SECONDS),
        allow_redirects=False,
    )
    if response.status_code != 200:
        raise ValueError(f"Falha ao obter content: HTTP {response.status_code}")
    if len(response.content) > config.MAX_CONTENT_SIZE_BYTES:
        raise ValueError("O conteúdo da notificação excede o limite permitido")

    return _html_to_text(response.text)


def _build_message(payload):
    if payload.message is not None:
        text = payload.message.strip()
    elif payload.content is not None and payload.content.strip():
        text = _get_content_text(payload.content.strip())
        if not text:
            raise ValueError("O conteúdo da notificação está vazio")
    else:
        raise ValueError("Informe message ou content com a URL do HTML")

    return f"{payload.topic.strip()}\n\n{text}"


@app.get(
    "/",
    response_model=HealthResponse,
    tags=["Sistema"],
    summary="Verificar a API",
)
@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["Sistema"],
    summary="Health check do Render",
)
def health():
    missing = config.missing_required_settings()
    response = HealthResponse(
        status="ok" if not missing else "configuration_error",
        service="notificacao-phiz",
        missing_settings=missing,
    )
    if missing:
        return JSONResponse(status_code=503, content=response.model_dump())
    return response


@app.post(
    "/webhook/aluno-notificacao",
    response_model=NotificationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["Notificações"],
    summary="Receber e enfileirar uma notificação",
    description=(
        "Aceita um ou vários CPFs. Um job independente é criado para cada CPF "
        "não repetido. A resposta 202 significa que os jobs foram enfileirados."
    ),
    responses={
        400: {"description": "Mensagem, conteúdo ou CPF inválido."},
        401: {"description": "Chave da API ausente ou inválida."},
        503: {"description": "Configuração incompleta ou fila cheia."},
    },
)
def notification_webhook(
    payload: NotificationRequest,
    _api_key: str = Security(verify_api_key),
):
    missing = config.missing_required_settings()
    if missing:
        raise HTTPException(
            status_code=503,
            detail={"error": "configuration_error", "missing_settings": missing},
        )

    notification_id = payload.notificationId.strip()
    cpfs = []
    seen_cpfs = set()

    for index, student in enumerate(payload.students):
        try:
            cpf = _format_cpf(student.cpf)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"students[{index}].cpf: {exc}",
            ) from exc
        if cpf not in seen_cpfs:
            seen_cpfs.add(cpf)
            cpfs.append(cpf)

    try:
        body = _build_message(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except requests.RequestException as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Falha ao obter content: {exc}",
        ) from exc

    jobs = []
    errors = []

    for cpf in cpfs:
        key = (notification_id, cpf)
        cpf_final = re.sub(r"\D", "", cpf)[-4:]

        with notification_jobs_lock:
            previous_job_id = notification_jobs.get(key)
            if previous_job_id:
                job_id = previous_job_id
                job_status = "ja_enfileirado"
            else:
                try:
                    job_id = outbound_queue.enqueue(cpf, body)
                except QueueFullError:
                    errors.append(
                        ProcessingError(
                            cpf_final=cpf_final,
                            erro="Fila temporariamente cheia",
                        )
                    )
                    continue
                notification_jobs[key] = job_id
                job_status = "enfileirado"

        jobs.append(
            JobCreated(
                cpf_final=cpf_final,
                job_id=job_id,
                status=job_status,
            )
        )

    response = NotificationResponse(
        received=bool(jobs),
        notificationId=notification_id,
        status="parcial" if jobs and errors else ("enfileirado" if jobs else "falha"),
        jobs=jobs,
        errors=errors,
    )

    if not jobs:
        return JSONResponse(status_code=503, content=response.model_dump())
    return response


@app.get(
    "/jobs/{job_id}",
    response_model=JobStatusResponse,
    tags=["Jobs"],
    summary="Consultar o estado de um envio",
    responses={
        401: {"description": "Chave da API ausente ou inválida."},
        404: {"description": "Job não encontrado."},
    },
)
def get_job(job_id: str, _api_key: str = Security(verify_api_key)):
    result = outbound_queue.get_result(job_id)
    if result is None:
        raise HTTPException(status_code=404, detail="job_not_found")
    return result


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
    )
