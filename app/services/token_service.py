"""Validate supplied Instagram Login token. No token storage or automatic exchange."""

from app.clients.instagram_client import InstagramAPIError, InstagramClient


async def validate_token(client: InstagramClient) -> dict:
    identity = await client.get("me", {"fields": "id,username"})
    user_id = str(identity.get("id", ""))
    if not user_id.isdigit():
        raise InstagramAPIError()
    if client.settings.instagram_user_id and client.settings.instagram_user_id != user_id:
        raise ValueError("Configured Instagram user ID differs from authenticated account")
    return identity
