"""Локальные проверки парсера; ответы создаются в памяти, без стенда."""

import json

import pytest
import requests

from api_client import check_registered_user, item_id, json_body, request


def response(body, status=200):
    result = requests.Response()
    result.status_code = status
    result.headers["Content-Type"] = "application/json"
    result._content = json.dumps(body).encode()
    return result


def test_uuid_extracted_from_status():
    identifier = "550e8400-e29b-41d4-a716-446655440000"
    assert item_id(response({"status": "Сохранили объявление - " + identifier})) == identifier


def test_creation_without_uuid_is_rejected():
    with pytest.raises(AssertionError, match="UUID"):
        item_id(response({"status": "Сохранили объявление"}))


@pytest.mark.parametrize("body", [{"likes": 0}, [{"likes": 0}]])
def test_statistics_json_accepts_documented_variants(body):
    assert json_body(response(body), (dict, list)) == body


def test_registration_does_not_accept_wrong_success_code():
    with pytest.raises(AssertionError, match="201"):
        check_registered_user(response({"id": 1, "username": "test"}), {"username": "test"})


def test_public_request_does_not_send_bearer(monkeypatch):
    with requests.Session() as session:
        seen = {}

        def capture(method, url, **kwargs):
            seen.update(kwargs)
            return response({})

        monkeypatch.setattr(session, "request", capture)
        request(session, "POST", "/api/1/register", json={})
        assert "Authorization" not in seen["headers"]
        assert all(value > 0 for value in seen["timeout"])
        assert seen["allow_redirects"] is False
