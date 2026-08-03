from uuid import uuid4

from backend.app.api.routes.model_config import ProviderCreate, create_provider


class _Result:
    def __init__(self, row: dict) -> None:
        self._row = row

    def mappings(self):
        return self

    def one(self):
        return self._row


class _Db:
    def __init__(self) -> None:
        self.statements: list[tuple[str, dict]] = []
        self.committed = False

    def execute(self, statement, params=None):
        self.statements.append((str(statement), dict(params or {})))
        return _Result({"id": uuid4(), "provider_name": "Doc2X", "provider_type": "ocr"})

    def commit(self) -> None:
        self.committed = True


def test_ocr_provider_accepts_a_direct_encrypted_key(monkeypatch) -> None:
    monkeypatch.setattr(
        "backend.app.api.routes.model_config._ensure_unique_model_config_name",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "backend.app.api.routes.model_config._encrypt_model_key_or_http_error",
        lambda value: f"encrypted:{value}",
    )
    db = _Db()

    create_provider(
        ProviderCreate(
            provider_name="Doc2X",
            model_name="v3-2026",
            base_url="https://v2.doc2x.noedgeai.com",
            secret_mode="direct",
            api_key="doc2x-secret",
            provider_type="ocr",
            auth_type="bearer",
            extra_config_json={"adapter": "doc2x"},
            is_default=True,
        ),
        db=db,
    )

    insert = next(item for item in db.statements if "insert into model_provider_config" in item[0])
    assert insert[1]["provider_type"] == "ocr"
    assert insert[1]["api_key_encrypted"] == "encrypted:doc2x-secret"
    assert insert[1]["api_key_secret_ref"] is None
    assert db.committed is True
