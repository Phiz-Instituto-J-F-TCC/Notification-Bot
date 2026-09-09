import threading
import time

import requests

import config


class PhizClient:
    def __init__(self):
        self.token = None
        self.expires_at = 0
        self.auth_lock = threading.Lock()

    def authenticate(self):
        url = f"{config.PHIZ_BASE_URL}/gateway/openapi/auth"
        payload = {
            "app_id": config.PHIZ_APP_ID,
            "app_secret": config.PHIZ_APP_SECRET,
            "description": "channel bot business api",
            "grant_type": "user_credentials",
            "scope": "channel",
        }

        response = requests.post(url, json=payload, timeout=(8, 30))
        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError(
                f"Autenticação Phiz retornou conteúdo inválido (HTTP {response.status_code})"
            ) from exc

        if response.status_code >= 400 or not data.get("success"):
            raise RuntimeError(f"Autenticação Phiz rejeitada (HTTP {response.status_code})")

        token = (data.get("data") or {}).get("access_token")
        if not token:
            raise RuntimeError("Autenticação Phiz não retornou access_token")

        expires_in = int((data.get("data") or {}).get("expires_in", 0))
        self.token = token
        self.expires_at = time.time() + max(expires_in - 30, 0)
        return token

    def get_token(self):
        if self.token and time.time() < self.expires_at:
            return self.token

        with self.auth_lock:
            if self.token and time.time() < self.expires_at:
                return self.token
            return self.authenticate()

    def send_text(self, phone, body):
        token = self.get_token()
        url = (
            f"{config.PHIZ_BASE_URL}/v4/openapi/oauth/channel/robot/business/"
            f"{config.PHIZ_CHANNEL_ID}/messages"
        )
        payload = {
            "messaging_product": "phiz",
            "recipient_type": "individual",
            "to": [phone],
            "type": "text",
            "text": {"body": body},
        }

        response = requests.post(
            url,
            json=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            timeout=(8, 30),
        )

        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError(
                f"Envio Phiz retornou conteúdo inválido (HTTP {response.status_code})"
            ) from exc

        if response.status_code >= 400 or data.get("success") is False:
            raise RuntimeError(f"Envio Phiz rejeitado (HTTP {response.status_code})")

        return data


phiz_client = PhizClient()
