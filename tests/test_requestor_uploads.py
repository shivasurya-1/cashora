import io
from types import SimpleNamespace
from fastapi.testclient import TestClient
import pytest

from app.main import app
from app.api.v1.requestor import cloudinary_service
from app.services.expense_service import ExpenseService
from app.core.security import get_current_user
from app.models.user import UserRole
from app.db.session import get_db

client = TestClient(app)

class FakeUser(SimpleNamespace):
    pass

class FakeResult:
    def __init__(self, expense):
        self._expense = expense
    def scalar_one_or_none(self):
        return self._expense
    def scalars(self):
        return SimpleNamespace(all=lambda: [self._expense])

class FakeSession:
    def __init__(self, expense):
        self._expense = expense
    async def execute(self, *args, **kwargs):
        if hasattr(self._expense, "__iter__"):
             return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: self._expense))
        return FakeResult(self._expense)
    async def commit(self):
        return None
    async def refresh(self, *args, **kwargs):
        return None


@pytest.fixture(autouse=True)
def _cleanup_overrides():
    # Ensure dependency overrides are cleaned up between tests
    yield
    app.dependency_overrides.clear()


def test_submit_with_files(monkeypatch):
    # Fake user
    user = FakeUser(id=7, org_id=1, first_name="Test", last_name="User", role=UserRole.REQUESTOR)
    app.dependency_overrides[get_current_user] = lambda: user

    # Mock Cloudinary to return predictable URLs
    def fake_upload(file_content, filename, expense_id=None):
        return {"url": f"https://res/{filename}", "public_id": filename, "format": "jpg", "size": 123}

    monkeypatch.setattr(cloudinary_service, "upload_receipt", fake_upload)

    # Mock ExpenseService.create_new_request to assert inputs and return a fake expense object
    async def fake_create_new_request(db, expense_data, user_id, org_id):
        assert user_id == user.id
        return SimpleNamespace(
            id=101,
            request_id="EXP-FAKE",
            request_type=expense_data.request_type,
            amount=expense_data.amount,
            purpose=expense_data.purpose,
            description=expense_data.description,
            category=expense_data.category,
            status="pending",
            created_at=datetime.datetime.now(),
            clarifications=[],
            requestor={"first_name": "Test", "last_name": "User", "email": "t@example.com"},
            receipt_url=expense_data.receipt_url
        )

    import datetime
    monkeypatch.setattr(ExpenseService, "create_new_request", staticmethod(fake_create_new_request))

    # Prepare files: receipt_file
    files = [
        ("receipt_file", ("receipt.jpg", io.BytesIO(b"receipt"), "image/jpeg")),
    ]

    data = {"amount": "100.50", "purpose": "Travel", "category": "travel"}

    response = client.post("/requestor/submit", data=data, files=files)
    assert response.status_code == 200
    body = response.json()
    assert body["receipt_url"] == "https://res/receipt.jpg"


def test_preapproved_without_files(monkeypatch):
    # Pre-approved request should be allowed without any proof
    user = FakeUser(id=9, org_id=3, first_name="Bob", last_name="B", role=UserRole.REQUESTOR)
    app.dependency_overrides[get_current_user] = lambda: user

    async def fake_create_new_request(db, expense_data, user_id, org_id):
        assert expense_data.request_type == "pre_approved"
        return SimpleNamespace(
            id=300,
            request_id="EXP-PA-300",
            request_type=expense_data.request_type,
            amount=expense_data.amount,
            purpose=expense_data.purpose,
            description=expense_data.description,
            category=expense_data.category,
            status="pending",
            created_at=datetime.datetime.now(),
            clarifications=[],
            requestor={"first_name": "Bob", "last_name": "B", "email": "b@example.com"},
            receipt_url=None
        )

    import datetime
    monkeypatch.setattr(ExpenseService, "create_new_request", staticmethod(fake_create_new_request))

    data = {"amount": "50", "purpose": "Taxi", "category": "travel", "request_type": "pre_approved"}
    res = client.post("/requestor/submit", data=data)
    assert res.status_code == 200
    body = res.json()
    assert body["receipt_url"] is None


def test_postapproved_without_files_should_fail():
    # Post-approved request must include at least one payment proof
    user = FakeUser(id=10, org_id=4, first_name="Eve", last_name="E", role=UserRole.REQUESTOR)
    app.dependency_overrides[get_current_user] = lambda: user

    data = {"amount": "200", "purpose": "Reimbursement", "category": "meals", "request_type": "post_approved"}
    res = client.post("/requestor/submit", data=data)
    assert res.status_code == 400
    body = res.json()
    assert "Receipt required" in body["detail"]


def test_get_my_requests(monkeypatch):
    user = FakeUser(id=11, org_id=5, first_name="Test", last_name="User", role=UserRole.REQUESTOR)
    app.dependency_overrides[get_current_user] = lambda: user

    import datetime
    expense = SimpleNamespace(
        id=400,
        request_id="EXP-400",
        request_type="pre_approved",
        amount=10.0,
        purpose="Snack",
        description="test",
        category="meals",
        status="pending",
        created_at=datetime.datetime.now(),
        clarifications=[],
        requestor={"first_name":"Test","last_name":"User","email":"t@example.com"},
        receipt_url=None
    )

    app.dependency_overrides[get_db] = lambda: FakeSession(expense)

    res = client.get("/requestor/my-requests")
    assert res.status_code == 200
    body = res.json()
    assert isinstance(body, list)
    assert body[0]["id"] == 400
