"""Запросы к учебному API и общие проверки ответов."""

import os
import re
from uuid import UUID

import pytest
import requests


BASE_URL = os.getenv("AVITO_BASE_URL", "https://qa-internship.avito.com").rstrip("/")
# В условии нет SLA по времени ответа. Общий стенд иногда отвечает дольше
# 15 секунд; ограничиваем соединение 10 секундами, чтение - 45 секундами.
# Повторной отправки POST нет: она могла бы создать лишние данные.
TIMEOUT = (10, 45)
UUID_PATTERN = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")


def request(session, method, path, token=None, **kwargs):
    headers = {"Accept": "application/json", **kwargs.pop("headers", {})}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    try:
        return session.request(
            method, BASE_URL + path, headers=headers, timeout=TIMEOUT,
            allow_redirects=False, **kwargs,
        )
    except requests.RequestException as error:
        pytest.fail(
            f"{method} {path}: {type(error).__name__}. Нет ответа стенда. "
            "Проверьте сеть и доступность API; это не подтверждённый дефект API.",
            pytrace=False,
        )


def check_status(response, expected, case=""):
    assert response.status_code == expected, (
        f"{case}: ожидался HTTP {expected}, получен HTTP {response.status_code}. "
        "При повторяемом несоответствии оформите баг-репорт."
    )


def json_body(response, kind):
    assert "application/json" in response.headers.get("Content-Type", "").lower(), (
        "Ожидался Content-Type application/json"
    )
    try:
        body = response.json()
    except requests.exceptions.JSONDecodeError:
        pytest.fail("Ответ не является корректным JSON", pytrace=False)
    names = ", ".join(t.__name__ for t in kind) if isinstance(kind, tuple) else kind.__name__
    assert isinstance(body, kind), f"Ожидался JSON типа {names}"
    return body


def item_id(response):
    status = json_body(response, dict).get("status")
    assert isinstance(status, str), "Ответ создания должен содержать строку status"
    match = UUID_PATTERN.search(status)
    assert match, "В status отсутствует UUID объявления"
    result = match.group()
    UUID(result)
    return result


def check_registered_user(response, credentials):
    check_status(response, 201, "REG-01")
    body = json_body(response, dict)
    assert type(body.get("id")) is int, "id должен быть целым числом"
    assert body.get("username") == credentials["username"], "username не совпадает"
    assert "password" not in body, "Пароль не должен возвращаться в ответе"
    return body


def check_token(response):
    check_status(response, 200, "AUTH-01")
    body = json_body(response, dict)
    assert isinstance(body.get("accessToken"), str), "accessToken должен быть строкой"
    assert body["accessToken"].strip(), "accessToken не должен быть пустым"
    assert body.get("tokenType") == "Bearer", "Ожидался tokenType Bearer"
    return body["accessToken"]


def check_no_token(response):
    # Коллекция не определяет формат тела ошибки, поэтому текст тоже допустим.
    try:
        body = response.json()
    except requests.exceptions.JSONDecodeError:
        return
    if isinstance(body, dict):
        assert "accessToken" not in body, "При ошибке токен не выдаётся"
