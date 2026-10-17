"""Builders shared by the quiz tests. A plain module, not a conftest, so the
tests can import them by name."""


def choice(text="2 + 2 = ?", options=("3", "4", "5", "22"), correct=1, notes=None):
    return {
        "type": "choice",
        "text": text,
        "options": [
            {"text": t, "note": (notes or {}).get(i, "")} for i, t in enumerate(options)
        ],
        "correct": correct,
        "explanation": "Екі мен екі - төрт.",
    }


def short(text="Массасы 2 кг денеге 10 Н күш әсер етеді. Үдеу?", answer="5", unit="м/с²",
          accept=("5,0",)):
    return {"type": "short", "text": text, "answer": answer, "unit": unit,
            "accept": list(accept), "explanation": "a = F/m"}


def player(client, token):
    """Requests as the student holding `token`."""

    class _As:
        def state(self):
            return client.get("/api/play/state", headers={"X-Player-Token": token})

        def answer(self, **body):
            return client.post("/api/play/answer", json=body,
                               headers={"X-Player-Token": token})

    return _As()
