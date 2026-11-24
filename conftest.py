"""Независимые данные каждого теста и очистка собственных объявлений."""

from uuid import uuid4

import pytest
import requests

from api_client import check_registered_user, check_status, check_token, item_id, request


def pytest_addoption(parser):
    parser.addoption("--reverse", action="store_true", help="Запустить тесты в обратном порядке")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--reverse"):
        items.reverse()


@pytest.fixture
def api():
    with requests.Session() as session:
        yield session


@pytest.fixture
def credentials():
    return {"username": f"student_{uuid4().hex}", "password": "strong-password"}


@pytest.fixture
def registered_user(api, credentials):
    check_registered_user(request(api, "POST", "/api/1/register", json=credentials), credentials)
    return credentials


@pytest.fixture
def users(api):
    def create():
        credentials = {"username": f"student_{uuid4().hex}", "password": "strong-password"}
        body = check_registered_user(
            request(api, "POST", "/api/1/register", json=credentials), credentials,
        )
        token = check_token(request(api, "POST", "/api/1/autorize", json=credentials))
        return {"id": body["id"], "token": token, "credentials": credentials}
    return create


@pytest.fixture
def owner(users):
    return users()


@pytest.fixture
def items(api):
    cleanup = []

    def track(identifier, user):
        cleanup.append((identifier, user["token"]))

    def create(user, **changes):
        payload = {
            "sellerID": user["id"], "name": f"testItem_{uuid4().hex}", "price": 9900,
            "statistics": {"likes": 21, "viewCount": 11, "contacts": 43},
        }
        payload.update(changes)
        response = request(api, "POST", "/api/1/item", token=user["token"], json=payload)
        check_status(response, 200, "Подготовка объявления")
        identifier = item_id(response)
        track(identifier, user)
        return identifier, payload

    create.track = track
    yield create

    errors = []
    for identifier, token in reversed(cleanup):
        try:
            response = request(api, "DELETE", f"/api/2/item/{identifier}", token=token)
            # 404 допустим только при очистке: запись мог удалить сам тест.
            if response.status_code not in (200, 404):
                errors.append(f"{identifier}: HTTP {response.status_code}")
        except pytest.fail.Exception:
            errors.append(f"{identifier}: сетевая ошибка очистки")
    if errors:
        pytest.fail("Не удалось очистить собственные объявления: " + "; ".join(errors), pytrace=False)
