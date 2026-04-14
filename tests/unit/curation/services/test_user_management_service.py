from unittest.mock import AsyncMock, create_autospec

import pytest

from ers.commons.domain.data_transfer_objects import PaginatedResult, PaginationParams
from ers.commons.services.exceptions import ApplicationError, NotFoundError
from ers.users.adapters import ContentHasher, UserRepository
from ers.users.domain.data_transfer_objects import CreateUserRequest, UserPatchRequest
from ers.users.domain.exceptions import LastAdminError
from ers.users.services import UserManagementService
from tests.unit.factories import UserFactory


@pytest.fixture
def user_repository() -> AsyncMock:
    return create_autospec(UserRepository, instance=True)


@pytest.fixture
def password_hasher() -> AsyncMock:
    return create_autospec(ContentHasher, instance=True)


@pytest.fixture
def service(user_repository: AsyncMock, password_hasher: AsyncMock) -> UserManagementService:
    return UserManagementService(user_repository=user_repository, password_hasher=password_hasher)


class TestCreateUser:
    async def test_creates_user_with_hashed_password(
        self,
        service: UserManagementService,
        user_repository: AsyncMock,
        password_hasher: AsyncMock,
    ) -> None:
        user_repository.find_by_email.return_value = None
        password_hasher.hash.return_value = "hashed"
        user_repository.save.side_effect = lambda u: u

        result = await service.create_user(
            CreateUserRequest(
                email="new@example.com",
                password="securepassword",
                is_verified=True,
            )
        )

        assert result.email == "new@example.com"
        assert result.is_verified is True
        user_repository.save.assert_called_once()

    async def test_duplicate_email_raises_error(
        self,
        service: UserManagementService,
        user_repository: AsyncMock,
    ) -> None:
        user_repository.find_by_email.return_value = UserFactory.build()

        with pytest.raises(ApplicationError, match="already exists"):
            await service.create_user(
                CreateUserRequest(email="existing@example.com", password="securepassword")
            )


class TestListUsers:
    async def test_returns_paginated_users(
        self,
        service: UserManagementService,
        user_repository: AsyncMock,
    ) -> None:
        users = UserFactory.batch(3)
        user_repository.find_paginated.return_value = PaginatedResult(
            count=3,
            previous=None,
            next=None,
            results=users,
        )

        result = await service.list_users(PaginationParams(page=1, per_page=20))

        assert result.count == 3
        assert len(result.results) == 3
        assert result.results[0].email == users[0].email

    async def test_returns_empty_when_no_users(
        self,
        service: UserManagementService,
        user_repository: AsyncMock,
    ) -> None:
        user_repository.find_paginated.return_value = PaginatedResult(
            count=0,
            previous=None,
            next=None,
            results=[],
        )

        result = await service.list_users(PaginationParams(page=1, per_page=20))

        assert result.count == 0
        assert result.results == []

    async def test_passes_email_search_to_repository(
        self,
        service: UserManagementService,
        user_repository: AsyncMock,
    ) -> None:
        user_repository.find_paginated.return_value = PaginatedResult(
            count=0,
            previous=None,
            next=None,
            results=[],
        )

        await service.list_users(PaginationParams(page=1, per_page=20), email_search="test")

        user_repository.find_paginated.assert_called_once_with(
            PaginationParams(page=1, per_page=20), email_search="test"
        )


class TestPatchUser:
    async def test_updates_user_flags(
        self,
        service: UserManagementService,
        user_repository: AsyncMock,
    ) -> None:
        user = UserFactory.build(is_verified=False)
        user_repository.find_by_id.return_value = user
        user_repository.save.side_effect = lambda u: u

        result = await service.patch_user(user.id, UserPatchRequest(is_verified=True))

        assert result.is_verified is True
        user_repository.save.assert_called_once()

    async def test_patch_no_changes_skips_save(
        self,
        service: UserManagementService,
        user_repository: AsyncMock,
    ) -> None:
        user = UserFactory.build()
        user_repository.find_by_id.return_value = user

        result = await service.patch_user(user.id, UserPatchRequest())

        assert result.email == user.email
        user_repository.save.assert_not_called()

    async def test_patch_nonexistent_user_raises(
        self,
        service: UserManagementService,
        user_repository: AsyncMock,
    ) -> None:
        user_repository.find_by_id.return_value = None

        with pytest.raises(NotFoundError):
            await service.patch_user("missing-id", UserPatchRequest(is_active=False))


class TestPatchUserPassword:
    async def test_patch_password_hashes_and_stores(
        self,
        service: UserManagementService,
        user_repository: AsyncMock,
        password_hasher: AsyncMock,
    ) -> None:
        user = UserFactory.build()
        user_repository.find_by_id.return_value = user
        user_repository.save.side_effect = lambda u: u
        password_hasher.hash.return_value = "hashed:newpassword"

        result = await service.patch_user(user.id, UserPatchRequest(password="newpassword"))

        password_hasher.hash.assert_called_once_with("newpassword")
        saved_user = user_repository.save.call_args.args[0]
        assert saved_user.hashed_password == "hashed:newpassword"
        assert result.email == user.email

    async def test_patch_password_with_flags(
        self,
        service: UserManagementService,
        user_repository: AsyncMock,
        password_hasher: AsyncMock,
    ) -> None:
        user = UserFactory.build(is_verified=False)
        user_repository.find_by_id.return_value = user
        user_repository.save.side_effect = lambda u: u
        password_hasher.hash.return_value = "hashed:newpassword"

        result = await service.patch_user(
            user.id, UserPatchRequest(password="newpassword", is_verified=True)
        )

        saved_user = user_repository.save.call_args.args[0]
        assert saved_user.hashed_password == "hashed:newpassword"
        assert result.is_verified is True

    async def test_patch_without_password_does_not_hash(
        self,
        service: UserManagementService,
        user_repository: AsyncMock,
        password_hasher: AsyncMock,
    ) -> None:
        user = UserFactory.build()
        user_repository.find_by_id.return_value = user
        user_repository.save.side_effect = lambda u: u

        await service.patch_user(user.id, UserPatchRequest(is_verified=True))

        password_hasher.hash.assert_not_called()


class TestLastAdminGuard:
    async def test_patch_deactivate_last_admin_raises(
        self,
        service: UserManagementService,
        user_repository: AsyncMock,
    ) -> None:
        user = UserFactory.build(id="admin-1", is_active=True, is_superuser=True)
        user_repository.find_by_id.return_value = user
        user_repository.count_active_admins.return_value = 1

        with pytest.raises(LastAdminError):
            await service.patch_user("admin-1", UserPatchRequest(is_active=False))

    async def test_patch_remove_superuser_from_last_admin_raises(
        self,
        service: UserManagementService,
        user_repository: AsyncMock,
    ) -> None:
        user = UserFactory.build(id="admin-1", is_active=True, is_superuser=True)
        user_repository.find_by_id.return_value = user
        user_repository.count_active_admins.return_value = 1

        with pytest.raises(LastAdminError):
            await service.patch_user("admin-1", UserPatchRequest(is_superuser=False))

    async def test_patch_deactivate_non_admin_succeeds(
        self,
        service: UserManagementService,
        user_repository: AsyncMock,
    ) -> None:
        user = UserFactory.build(id="user-1", is_active=True, is_superuser=False)
        user_repository.find_by_id.return_value = user
        user_repository.save.side_effect = lambda u: u

        result = await service.patch_user("user-1", UserPatchRequest(is_active=False))

        assert result.is_active is False
