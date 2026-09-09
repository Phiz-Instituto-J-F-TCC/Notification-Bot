import hmac
import os
import re
import threading
from html import unescape
from urllib.parse import urlsplit

import requests
from flask import Flask, jsonify, request

import config
from outbound_queue import QueueFullError, outbound_queue


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = config.MAX_JSON_SIZE_BYTES

notification_jobs = {}
notification_jobs_lock = threading.Lock()


def _authorized():
    if not config.SECRETARY_INBOUND_API_KEY:
        return False

    expected = f"API-Key {config.SECRETARY_INBOUND_API_KEY}"
    received = request.headers.get("Authorization", "")
    return hmac.compare_digest(received, expected)


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
    topic = payload.get("topic") or "Notificação"
    if not isinstance(topic, str) or not topic.strip():
        raise ValueError("topic deve ser uma string não vazia")

    message = payload.get("message")
    if message is not None:
        if not isinstance(message, str) or not message.strip():
            raise ValueError("message deve ser uma string não vazia")
        text = message.strip()
    else:
        content_url = payload.get("content")
        if not isinstance(content_url, str) or not content_url.strip():
            raise ValueError("Informe message ou content com a URL do HTML")
        text = _get_content_text(content_url.strip())
        if not text:
            raise ValueError("O conteúdo da notificação está vazio")

    return f"{topic.strip()}\n\n{text}"


@app.get("/")
@app.get("/health")
def health():
    missing = config.missing_required_settings()
    return jsonify({
        "status": "ok" if not missing else "configuration_error",
        "service": "notificacao-phiz",
        "missing_settings": missing,
    }), 200 if not missing else 503


@app.post("/webhook/aluno-notificacao")
def notification_webhook():
    if not _authorized():
        return jsonify({"error": "unauthorized"}), 401

    missing = config.missing_required_settings()
    if missing:
        return jsonify({"error": "configuration_error", "missing_settings": missing}), 503

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Envie um objeto JSON válido"}), 400

    notification_id = payload.get("notificationId")
    if not isinstance(notification_id, str) or not notification_id.strip():
        return jsonify({"error": "notificationId deve ser uma string não vazia"}), 400
    notification_id = notification_id.strip()

    students = payload.get("students")
    if not isinstance(students, list) or not students:
        return jsonify({"error": "students deve ser uma lista não vazia"}), 400

    cpfs = []
    seen_cpfs = set()
    for index, student in enumerate(students):
        if not isinstance(student, dict):
            return jsonify({"error": f"students[{index}] deve ser um objeto"}), 400
        try:
            cpf = _format_cpf(student.get("cpf"))
        except ValueError as exc:
            return jsonify({"error": f"students[{index}].cpf: {exc}"}), 400
        if cpf not in seen_cpfs:
            seen_cpfs.add(cpf)
            cpfs.append(cpf)

    try:
        body = _build_message(payload)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except requests.RequestException as exc:
        return jsonify({"error": f"Falha ao obter content: {exc}"}), 502

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
                    errors.append({
                        "cpf_final": cpf_final,
                        "erro": "Fila temporariamente cheia",
                    })
                    continue
                notification_jobs[key] = job_id
                job_status = "enfileirado"

        jobs.append({
            "cpf_final": cpf_final,
            "job_id": job_id,
            "status": job_status,
        })

    if not jobs:
        return jsonify({
            "received": False,
            "notificationId": notification_id,
            "status": "falha",
            "jobs": [],
            "errors": errors,
        }), 503

    return jsonify({
        "received": True,
        "notificationId": notification_id,
        "status": "parcial" if errors else "enfileirado",
        "jobs": jobs,
        "errors": errors,
    }), 202


@app.get("/jobs/<job_id>")
def get_job(job_id):
    if not _authorized():
        return jsonify({"error": "unauthorized"}), 401

    result = outbound_queue.get_result(job_id)
    if result is None:
        return jsonify({"error": "job_not_found"}), 404
    return jsonify(result), 200


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5000")),
        debug=False,
    )
