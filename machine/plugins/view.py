from __future__ import annotations

from typing import Any, Sequence, List

from slack_sdk.models.attachments import Attachment
from slack_sdk.models.blocks import Block
from slack_sdk.webhook import WebhookResponse
from slack_sdk.webhook.async_client import AsyncWebhookClient
from slack_sdk.web.async_slack_response import AsyncSlackResponse

from machine.clients.slack import SlackClient
from machine.models import User, Channel


class View:
    """A Slack interactive view message that was received by the bot

    This class represents a Slack interactive view that was received by the bot and passed to a plugin.
    It contains the state that was included when the interactive view was invoked, and metadata about
    the interactive view, such as the user that invoked the command, the channel the command was invoked
    in.

    The `View` class also contains convenience methods
    """

    # TODO: create proper class for cmd_event
    def __init__(self, client: SlackClient, cmd_payload: dict[str, Any]):
        self._client = client
        self._cmd_payload = cmd_payload

    @property
    def sender(self) -> User:
        """The sender of the message

        :return: the User the message was sent by
        """
        return self._client.users[self._cmd_payload["user"]["id"]]

    @property
    def channel(self) -> Channel:
        """The channel the message was sent to

        :return: the Channel the message was sent to
        """
        return self._client.channels[self._cmd_payload["channel"]["id"]]

    @property
    def is_dm(self) -> bool:
        channel_id = self._cmd_payload["channel"]["id"]
        return not (channel_id.startswith("C") or channel_id.startswith("G"))

    @property
    def state(self) -> dict[str, Any] | None:
        """The state from the actual message

        :return: the state (dict) of the actual message
        """
        return self._cmd_payload.get("view", {}).get("state")

    @property
    def view(self) -> dict[str, Any] | None:
        """The view from the actual message

        :return: the view (dict) of the actual message
        """
        return self._cmd_payload.get("view")

    @property
    def trigger_id(self) -> str:
        """The trigger id associated with the command

        The trigger id can be used to trigger modals

        :return: the trigger id associated with the command
        """
        return self._cmd_payload["trigger_id"]

    # todo: convert to loading a new 'view' into the dialog we received
    async def modal(
        self,
        view: str | None = None,
        **kwargs: Any,
    ) -> AsyncSlackResponse:
        """Opens a Modal View based on the trigger_id associated with this message

        Any extra kwargs you provide, will be passed on directly to the `views.open`_

        .. _view: https://api.slack.com/reference/surfaces/views

        :param view: view payload
        :return: Dictionary deserialized from `view.oopen`_ request

        .. _view.open: https://api.slack.com/methods/views.open
        """
        return await self._client.views_open(
            self.trigger_id,
            view=view,
            **kwargs,
        )
