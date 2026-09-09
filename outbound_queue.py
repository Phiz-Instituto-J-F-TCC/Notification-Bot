import queue
import threading
import uuid

import config
from phiz_client import phiz_client
from students_repository import StudentLookupError, find_phone_by_cpf


class QueueFullError(RuntimeError):
    pass


def _digits(value):
    return "".join(character for character in str(value) if character.isdigit())


class OutboundQueue:
    def __init__(self):
        self.q = queue.Queue(maxsize=config.QUEUE_MAX_SIZE)
        self.jobs = {}
        self.lock = threading.Lock()

        for number in range(config.QUEUE_WORKERS):
            thread = threading.Thread(
                target=self._run,
                name=f"phiz-worker-{number + 1}",
                daemon=True,
            )
            thread.start()

        print(f"[FILA] {config.QUEUE_WORKERS} worker(s) iniciado(s).", flush=True)

    def enqueue(self, cpf, body):
        job_id = str(uuid.uuid4())
        job = {
            "job_id": job_id,
            "status": "PENDING",
            "cpf_final": _digits(cpf)[-4:],
        }

        with self.lock:
            self.jobs[job_id] = job

        try:
            self.q.put_nowait((job_id, cpf, body))
        except queue.Full as exc:
            with self.lock:
                self.jobs.pop(job_id, None)
            raise QueueFullError("Fila cheia") from exc

        print(f"[FILA] Job criado: {job_id}", flush=True)
        return job_id

    def get_result(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            return dict(job) if job else None

    def _update(self, job_id, **values):
        with self.lock:
            if job_id in self.jobs:
                self.jobs[job_id].update(values)

    def _run(self):
        while True:
            job_id, cpf, body = self.q.get()
            try:
                self._update(job_id, status="LOOKING_UP_PHONE")
                phone = find_phone_by_cpf(cpf)

                self._update(job_id, status="SENDING")
                response = phiz_client.send_text(phone, body)
                data = response.get("data") or {}
                contact = (data.get("contacts") or [{}])[0]

                self._update(
                    job_id,
                    status=contact.get("message_status") or "ACCEPTED",
                    message_id=(data.get("message") or {}).get("id"),
                    telefone_final=phone[-4:],
                )
            except StudentLookupError as exc:
                self._update(job_id, status="ERROR", erro=str(exc))
            except Exception as exc:
                self._update(job_id, status="ERROR", erro=str(exc))
            finally:
                result = self.get_result(job_id) or {}
                print(f"[FILA] Resultado: {result.get('status')}", flush=True)
                self.q.task_done()


outbound_queue = OutboundQueue()
