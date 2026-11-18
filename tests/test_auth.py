
import pytest

from profile.database import Database
from profile.account_manager import AccountManager
from profile.profile_manager import ProfileManager
from profile.auth_service import AuthService


@pytest.fixture
def auth_service(tmp_path):
    db_path = tmp_path / "test_auth.db"
    db = Database(str(db_path))

    accounts = AccountManager(db=db)
    profiles = ProfileManager(db=db)

    return AuthService(
        account_manager=accounts,
        profile_manager=profiles
    )


def sample_profile():
    return {
        "full_name": "Test User",
        "date_of_birth": "2004-05-15",
        "age": 22,
        "gender": "FEMALE",
        "state": "Telangana",
        "district": "Hyderabad",
        "annual_income": 300000,
        "occupation": "STUDENT",
        "caste_category": "OBC",
        "is_bpl": False
    }


def test_signup_with_email(auth_service):
    result = auth_service.signup(
        email="student@example.com",
        password="Student@123"
    )

    assert result["success"] is True
    assert result["profile_required"] is True
    assert result["next_step"] == "CREATE_PROFILE"


def test_signup_with_phone(auth_service):
    result = auth_service.signup(
        phone="9876543210",
        password="Student@123"
    )

    assert result["success"] is True


def test_duplicate_account_rejected(auth_service):
    auth_service.signup(
        email="student@example.com",
        password="Student@123"
    )

    with pytest.raises(ValueError):
        auth_service.signup(
            email="student@example.com",
            password="Another@123"
        )


def test_login_with_email(auth_service):
    auth_service.signup(
        email="student@example.com",
        password="Student@123"
    )

    result = auth_service.login(
        identifier="student@example.com",
        password="Student@123"
    )

    assert result["success"] is True
    assert result["profile_required"] is True


def test_login_with_phone(auth_service):
    auth_service.signup(
        phone="9876543210",
        password="Student@123"
    )

    result = auth_service.login(
        identifier="9876543210",
        password="Student@123"
    )

    assert result["success"] is True


def test_invalid_password_rejected(auth_service):
    auth_service.signup(
        email="student@example.com",
        password="Student@123"
    )

    result = auth_service.login(
        identifier="student@example.com",
        password="WrongPassword@123"
    )

    assert result["success"] is False
    assert result["user"] is None


def test_profile_creation_after_signup(auth_service):
    signup = auth_service.signup(
        email="student@example.com",
        password="Student@123"
    )

    user_id = signup["user"]["user_id"]

    result = auth_service.create_profile_for_user(
        user_id=user_id,
        profile_data=sample_profile()
    )

    assert result["success"] is True
    assert result["next_step"] == "DASHBOARD"


def test_existing_profile_retrieved_after_login(auth_service):
    signup = auth_service.signup(
        email="student@example.com",
        password="Student@123"
    )

    user_id = signup["user"]["user_id"]

    auth_service.create_profile_for_user(
        user_id=user_id,
        profile_data=sample_profile()
    )

    result = auth_service.login(
        identifier="student@example.com",
        password="Student@123"
    )

    assert result["success"] is True
    assert result["profile"] is not None
    assert result["profile_required"] is False
    assert result["next_step"] == "DASHBOARD"


def test_duplicate_profile_rejected(auth_service):
    signup = auth_service.signup(
        email="student@example.com",
        password="Student@123"
    )

    user_id = signup["user"]["user_id"]

    auth_service.create_profile_for_user(
        user_id=user_id,
        profile_data=sample_profile()
    )

    with pytest.raises(ValueError):
        auth_service.create_profile_for_user(
            user_id=user_id,
            profile_data=sample_profile()
        )


def test_disabled_account_login_rejected(auth_service):
    signup = auth_service.signup(
        email="student@example.com",
        password="Student@123"
    )

    user_id = signup["user"]["user_id"]

    with auth_service.accounts.db.get_connection() as conn:
        conn.execute(
            """
            UPDATE users
            SET account_status = 'DISABLED'
            WHERE user_id = ?
            """,
            (user_id,)
        )

    result = auth_service.login(
        identifier="student@example.com",
        password="Student@123"
    )

    assert result["success"] is False
