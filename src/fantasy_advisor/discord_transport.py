"""Small Discord REST client used by scheduled, non-gateway jobs.

The scheduled launchd jobs do not need to keep a Discord gateway connection
open. They post completed Codex reports to one configured server channel, so
this module intentionally uses the Python standard library instead of importing
discord.py.
"""

from __future__ import annotations

import json
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .automation import AutomationError, split_discord_message


class DiscordTransport:
    """Send messages to one Discord user through the bot REST API."""

    def __init__(self, bot_token: str, *, api_base: str = "https://discord.com/api/v10"):
        if not bot_token.strip():
            raise AutomationError("Discord bot token is empty")
        self.bot_token = bot_token
        self.api_base = api_base.rstrip("/")

    def _request(self, method: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        for attempt in range(3):
            request = Request(
                f"{self.api_base}{path}",
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Authorization": f"Bot {self.bot_token}",
                    "Content-Type": "application/json",
                    "User-Agent": "fantasy-epl-advisor/0.1",
                },
                method=method,
            )
            try:
                with urlopen(request, timeout=30) as response:
                    body = response.read().decode("utf-8")
                break
            except HTTPError as exc:
                try:
                    detail = exc.read().decode("utf-8")
                except OSError:
                    detail = ""
                if exc.code in {429, 500, 502, 503, 504} and attempt < 2:
                    retry_after = 1.0
                    try:
                        retry_after = min(float(json.loads(detail).get("retry_after", 1.0)), 10.0)
                    except (ValueError, TypeError, AttributeError, json.JSONDecodeError):
                        pass
                    time.sleep(max(retry_after, 0.1))
                    continue
                detail = detail[-1000:] if detail else str(exc.reason)
                raise AutomationError(f"Discord API {method} {path} failed ({exc.code}): {detail}") from exc
            except URLError as exc:
                if attempt < 2:
                    time.sleep(1.0)
                    continue
                raise AutomationError(f"Discord API {method} {path} was unreachable: {exc.reason}") from exc
        else:
            raise AutomationError(f"Discord API {method} {path} failed after retries")
        try:
            decoded = json.loads(body) if body else {}
        except json.JSONDecodeError as exc:
            raise AutomationError(f"Discord API returned invalid JSON for {method} {path}") from exc
        if not isinstance(decoded, dict):
            raise AutomationError(f"Discord API returned an unexpected response for {method} {path}")
        return decoded

    def open_dm(self, user_id: str) -> str:
        if not user_id.isdigit():
            raise AutomationError("Discord user ID must be numeric")
        response = self._request("POST", "/users/@me/channels", {"recipient_id": user_id})
        channel_id = response.get("id")
        if not isinstance(channel_id, str) or not channel_id.isdigit():
            raise AutomationError("Discord did not return a valid DM channel ID")
        return channel_id

    def send_channel(self, channel_id: str, text: str) -> None:
        if not channel_id.isdigit():
            raise AutomationError("Discord channel ID must be numeric")
        for chunk in split_discord_message(text):
            self._request(
                "POST",
                f"/channels/{channel_id}/messages",
                {
                    "content": chunk,
                    "allowed_mentions": {"parse": []},
                },
            )

    def send_dm(self, user_id: str, text: str) -> None:
        self.send_channel(self.open_dm(user_id), text)
