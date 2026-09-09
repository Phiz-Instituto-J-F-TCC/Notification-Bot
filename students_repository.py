import re

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import config


class StudentLookupError(RuntimeError):
    pass


def _format_cpf(cpf):
    digits = re.sub(r"\D", "", str(cpf or ""))
    if len(digits) != 11:
        raise StudentLookupError("CPF inválido: informe exatamente 11 dígitos")
    return f"{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}"


def _normalize_phone(value):
    digits = re.sub(r"\D", "", str(value or ""))

    if len(digits) in (10, 11):
        digits = f"55{digits}"

    if len(digits) not in (12, 13) or not digits.startswith("55"):
        raise StudentLookupError(
            "A API acadêmica não retornou um telefone brasileiro válido"
        )

    return f"+{digits}"


def _session_with_retry():
    retry = Retry(
        total=2,
        connect=2,
        read=2,
        status=2,
        backoff_factor=1,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.mount("http://", HTTPAdapter(max_retries=retry))
    return session


def find_phone_by_cpf(cpf):
    formatted_cpf = _format_cpf(cpf)
    url = f"{config.ACADEMIC_API_BASE_URL}/aluno/numero-phiz-por-cpf"

    try:
        with _session_with_retry() as session:
            response = session.get(
                url,
                params={"cpf": formatted_cpf},
                timeout=(5, config.ACADEMIC_API_TIMEOUT_SECONDS),
            )
    except requests.RequestException as exc:
        raise StudentLookupError(f"Falha ao consultar telefone do aluno: {exc}") from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise StudentLookupError(
            f"API acadêmica retornou conteúdo inválido (HTTP {response.status_code})"
        ) from exc

    if response.status_code == 404:
        raise StudentLookupError("Aluno não encontrado para o CPF informado")
    if response.status_code >= 400:
        detail = data.get("detail") or data.get("erro") or data.get("message")
        raise StudentLookupError(
            f"Consulta do aluno falhou (HTTP {response.status_code}): {detail or data}"
        )

    return _normalize_phone(data.get("numero_phiz"))
