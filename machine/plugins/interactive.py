from __future__ import annotations

from typing import Any, Sequence, List

from slack_sdk.models.attachments import Attachment
from slack_sdk.models.blocks import Block
from slack_sdk.webhook import WebhookResponse
from slack_sdk.webhook.async_client import AsyncWebhookClient
from slack_sdk.web.async_slack_response import AsyncSlackResponse

from machine.clients.slack import SlackClient
from machine.models import User, Channel


class Interactive:
    """A Slack interactive message that was received by the bot

    This class represents a Slack interactive message that was received by the bot and passed to a plugin.
    It contains the state that was included when the interactive item was invoked, and metadata about
    the interactive message, such as the user that invoked the command, the channel the command was invoked
    in.

    The `Interactive` class also contains convenience methods for sending messages in the right
    channel, opening modals etc.
    """

    # TODO: create proper class for cmd_event
    def __init__(self, client: SlackClient, cmd_payload: dict[str, Any]):
        self._client = client
        self._cmd_payload = cmd_payload
        self._webhook_client = AsyncWebhookClient(self._cmd_payload["response_url"])

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
        return (
            self._cmd_payload["state"]
            if "state" in self._cmd_payload
            else self._cmd_payload["view"]["state"] if "view" in self._cmd_payload else None
        )

    @property
    def view(self) -> dict[str, Any] | None:
        """The view from the actual message

        :return: the view (dict) of the actual message
        """
        return self._cmd_payload.get("view")

    @property
    def actions(self) -> List:
        """The actions from the actual message

        :return: the actions (list of dict) of the actual message
        """
        return self._cmd_payload["actions"]

    @property
    def response_url(self) -> str:
        """The response url associated with the command

        This is a unique url for this specific command invocation.
        It can be used for sending messages in response to the command.
        This can only be used 5 times within 30 minutes of receiving the payload.

        :return: the response url associated with the command
        """
        return self._cmd_payload["response_url"]

    @property
    def trigger_id(self) -> str:
        """The trigger id associated with the command

        The trigger id can be used to trigger modals

        :return: the trigger id associated with the command
        """
        return self._cmd_payload["trigger_id"]

    async def say(
        self,
        text: str | None = None,
        attachments: Sequence[Attachment] | Sequence[dict[str, Any]] | None = None,
        blocks: Sequence[Block] | Sequence[dict[str, Any]] | None = None,
        thread_ts: str | None = None,
        ephemeral: bool = False,
        **kwargs: Any,
    ) -> AsyncSlackResponse:
        """Send a new message to the channel the original message was received in

        Send a new message to the channel the original message was received in, using the WebAPI.
        Allows for rich formatting using `blocks`_ and/or `attachments`_. You can provide blocks
        and attachments as Python dicts or you can use the `convenient classes`_ that the
        underlying slack client provides.
        Can also reply to a thread and send an ephemeral message only visible to the sender of the
        original message. Ephemeral messages and threaded messages are mutually exclusive, and
        ``ephemeral`` takes precedence over ``thread_ts``
        Any extra kwargs you provide, will be passed on directly to the `chat.postMessage`_ or
        `chat.postEphemeral`_ request.

        .. _attachments: https://api.slack.com/docs/message-attachments
        .. _blocks: https://api.slack.com/reference/block-kit/blocks
        .. _convenient classes:
            https://github.com/slackapi/python-slackclient/tree/master/slack/web/classes

        :param text: message text
        :param attachments: optional attachments (see `attachments`_)
        :param blocks: optional blocks (see `blocks`_)
        :param thread_ts: optional timestamp of thread, to send a message in that thread
        :param ephemeral: ``True/False`` wether to send the message as an ephemeral message, only
            visible to the sender of the original message
        :return: Dictionary deserialized from `chat.postMessage`_ request, or `chat.postEphemeral`_
            if `ephemeral` is True.

        .. _chat.postMessage: https://api.slack.com/methods/chat.postMessage
        .. _chat.postEphemeral: https://api.slack.com/methods/chat.postEphemeral
        """
        if ephemeral:
            ephemeral_user = self.sender.id
        else:
            ephemeral_user = None

        return await self._client.send(
            self.channel.id,
            text=text,
            attachments=attachments,
            blocks=blocks,
            thread_ts=thread_ts,
            ephemeral_user=ephemeral_user,
            **kwargs,
        )

    async def replace(
        self,
        text: str | None = None,
        attachments: Sequence[Attachment] | Sequence[dict[str, Any]] | None = None,
        blocks: Sequence[Block] | Sequence[dict[str, Any]] | None = None,
        ephemeral: bool = True,
        **kwargs: Any,
    ) -> WebhookResponse:
        """Send a interactive replacment message to the channel the command was invoked in

        Send a response message to the channel the command was invoked in, using the response_url as a webhook.
        Allows for rich formatting using [blocks] and/or [attachments] . You can provide blocks
        and attachments as Python dicts or you can use the [convenient classes] that the
        underlying slack client provides.
        This will send an ephemeral message by default, only visible to the user that invoked the command.
        You can set `ephemeral` to `False` to make the message visible to everyone in the channel
        Any extra kwargs you provide, will be passed on directly to `AsyncWebhookClient.send()`

        [attachments]: https://api.slack.com/docs/message-attachments
        [blocks]: https://api.slack.com/reference/block-kit/blocks
        [convenient classes]: https://github.com/slackapi/python-slack-sdk/tree/main/slack/web/classes

        :param text: message text
        :param attachments: optional attachments (see [attachments])
        :param blocks: optional blocks (see [blocks])
        :param ephemeral: `True/False` wether to send the message as an ephemeral message, only
            visible to the sender of the original message
        :return: Dictionary deserialized from `AsyncWebhookClient.send()`

        """
        if ephemeral:
            response_type = "ephemeral"
        else:
            response_type = "in_channel"

        return await self._webhook_client.send(
            text=text, attachments=attachments, blocks=blocks, response_type=response_type, **kwargs
        )

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
