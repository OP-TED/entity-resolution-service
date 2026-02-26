from typing import Annotated

from fastapi import Depends, Request

from ers.config import Settings, get_settings


async def get_current_user(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> str:
    """Resolve the current user identity.

    Placeholder until SSO integration is implemented.
    When SSO is enabled, this will validate the bearer token
    from the Authorization header against the SSO provider.
    """
    # TODO: implement SSO token validation
    return "anonymous"


CurrentUser = Annotated[str, Depends(get_current_user)]
