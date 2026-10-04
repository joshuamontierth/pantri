import re

import pytest
from fastapi.testclient import TestClient

from app import db, models
from app.main import app


@pytest.fixture(autouse=True)
def fresh_db(tmp_path):
    db.init_engine(tmp_path / "test.db")
    yield
    db.engine.dispose()


class User:
    """A logged-in browser session for one user."""

    def __init__(self, username, password="password123"):
        self.client = TestClient(app, follow_redirects=False)
        self.username = username
        r = self.client.post("/signup", data={"username": username, "password": password, "confirm": password})
        assert r.status_code == 303, r.text
        self.csrf = self._csrf()

    def _csrf(self):
        page = self.client.get("/households").text
        return re.search(r'name="csrf-token" content="([^"]+)"', page).group(1)

    def get(self, url, **kw):
        return self.client.get(url, **kw)

    def post(self, url, data=None, htmx=False, **kw):
        headers = {"X-CSRF-Token": self.csrf}
        if htmx:
            headers["HX-Request"] = "true"
        return self.client.post(url, data=data or {}, headers=headers, **kw)

    def create_household(self, name="Home"):
        r = self.post("/households", {"name": name})
        assert r.status_code == 303
        return int(re.search(r"/h/(\d+)/", r.headers["location"]).group(1))

    def add_store(self, hid, name):
        r = self.post(f"/h/{hid}/stores", {"name": name})
        assert r.status_code == 303, r.text
        with db.SessionLocal() as s:
            return s.query(models.Store).filter_by(household_id=hid, name=name).one().id


@pytest.fixture
def make_user():
    return User
