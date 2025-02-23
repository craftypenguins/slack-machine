from __future__ import annotations

import asyncio
import re
from typing import Any, Callable, Awaitable, Mapping, cast, AsyncGenerator, Union

from slack_sdk.models import JsonObject
from structlog.stdlib import get_logger, BoundLogger

from slack_sdk.socket_mode.async_client import AsyncBaseSocketModeClient
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse

from machine.clients.slack import SlackClient
from machine.models.core import RegisteredActions, MessageHandler
from machine.plugins.interactive import Interactive
from machine.plugins.view import View
from machine.plugins.command import Command
from machine.plugins.message import Message

logger = get_logger(__name__)


def create_message_handler(
    plugin_actions: RegisteredActions,
    settings: Mapping,
    bot_id: str,
    bot_name: str,
    slack_client: SlackClient,
) -> Callable[[AsyncBaseSocketModeClient, SocketModeRequest], Awaitable[None]]:
    message_matcher = generate_message_matcher(settings)

    async def handle_message_request(client: AsyncBaseSocketModeClient, request: SocketModeRequest) -> None:
        if request.type == "events_api":
            # Acknowledge the request anyway
            response = SocketModeResponse(envelope_id=request.envelope_id)
            # Don't forget having await for method calls
            await client.send_socket_mode_response(response)

            # only process message events
            if request.payload["event"]["type"] == "message":
                await handle_message(
                    event=request.payload["event"],
                    bot_name=bot_name,
                    bot_id=bot_id,
                    plugin_actions=plugin_actions,
                    message_matcher=message_matcher,
                    slack_client=slack_client,
                    log_handled_message=settings["LOG_HANDLED_MESSAGES"],
                    force_user_lookup=settings["FORCE_USER_LOOKUP"],
                )

    return handle_message_request


def create_slash_command_handler(
    plugin_actions: RegisteredActions,
    slack_client: SlackClient,
) -> Callable[[AsyncBaseSocketModeClient, SocketModeRequest], Awaitable[None]]:
    async def handle_slash_command_request(client: AsyncBaseSocketModeClient, request: SocketModeRequest) -> None:
        if request.type == "slash_commands":
            logger.debug("slash command received", payload=request.payload)
            # We only acknowledge request if we know about this command
            if request.payload["command"] in plugin_actions.command:
                cmd = plugin_actions.command[request.payload["command"]]
                command_obj = _gen_command(request.payload, slack_client)
                if "logger" in cmd.function_signature.parameters:
                    command_logger = create_scoped_logger(
                        cmd.class_name, cmd.function.__name__, command_obj.sender.id, command_obj.sender.name
                    )
                    extra_args = {"logger": command_logger}
                else:
                    extra_args = {}
                # Check if the handler is a generator. In this case we have an immediate response we can send back
                if cmd.is_generator:
                    gen_fn = cast(Callable[..., AsyncGenerator[Union[dict, JsonObject, str], None]], cmd.function)
                    logger.debug("Slash command handler is generator, returning immediate ack")
                    gen = gen_fn(command_obj, **extra_args)
                    # return immediate reponse
                    payload = await gen.__anext__()
                    ack_response = SocketModeResponse(envelope_id=request.envelope_id, payload=payload)
                    await client.send_socket_mode_response(ack_response)
                    # Now run the rest of the function
                    try:
                        await gen.__anext__()
                    except StopAsyncIteration:
                        pass
                else:
                    ack_response = SocketModeResponse(envelope_id=request.envelope_id)
                    await client.send_socket_mode_response(ack_response)
                    fn = cast(Callable[..., Awaitable[None]], cmd.function)
                    await fn(command_obj, **extra_args)

    return handle_slash_command_request


def create_generic_event_handler(
    plugin_actions: RegisteredActions,
) -> Callable[[AsyncBaseSocketModeClient, SocketModeRequest], Awaitable[None]]:
    async def handle_event_request(client: AsyncBaseSocketModeClient, request: SocketModeRequest) -> None:
        if request.type == "events_api":
            # Acknowledge the request anyway
            response = SocketModeResponse(envelope_id=request.envelope_id)
            # Don't forget having await for method calls
            await client.send_socket_mode_response(response)

            # only process message events
            if request.payload["event"]["type"] in plugin_actions.process:
                await dispatch_event_handlers(
                    request.payload["event"], list(plugin_actions.process[request.payload["event"]["type"]].values())
                )

    return handle_event_request


async def log_request(_: AsyncBaseSocketModeClient, request: SocketModeRequest) -> None:
    logger.debug("Request received", type=request.type, request=request.to_dict())


def create_interactive_event_handler(
    plugin_actions: RegisteredActions,
    slack_client: SlackClient,
) -> Callable[[AsyncBaseSocketModeClient, SocketModeRequest], Awaitable[None]]:
    async def interactive_event_handler(client: AsyncBaseSocketModeClient, request: SocketModeRequest) -> None:
        if request.type == "interactive" and request.payload["type"] == "block_actions":
            logger.debug("interactive payload received", payload=request.payload)
            # Ack
            response = SocketModeResponse(envelope_id=request.envelope_id)
            await client.send_socket_mode_response(response)

            # We'll limit ourself to the first action in the array
            # request->payload->actions[0]->action_id
            try:
                action_id = request.payload["actions"][0]["action_id"]
                # You can use action_id here as the value is available
            except (KeyError, IndexError, TypeError):
                logger.warning("interactive block_actions payload no action_id to trigger on")
                return

            logger.debug(f"interactive payload action_id {action_id}")
            logger.debug(f"interactive interactive_actions {plugin_actions.interactive.keys()}")
            if action_id in plugin_actions.interactive:
                cmd = plugin_actions.interactive[action_id]
                interactive_obj = _gen_interactive(request.payload, slack_client)
                fn = cast(Callable[..., Awaitable[None]], cmd.function)
                await fn(interactive_obj)

    return interactive_event_handler


def create_view_event_handler(
    plugin_actions: RegisteredActions,
    slack_client: SlackClient,
) -> Callable[[AsyncBaseSocketModeClient, SocketModeRequest], Awaitable[None]]:
    async def view_event_handler(client: AsyncBaseSocketModeClient, request: SocketModeRequest) -> None:
        if request.type == "interactive" and request.payload["type"] == "view_submission":
            logger.debug("view_submission payload received", payload=request.payload)
            # Ack
            response = SocketModeResponse(envelope_id=request.envelope_id)
            await client.send_socket_mode_response(response)

            try:
                callback_id = request.payload["view"]["callback_id"]
            except (KeyError, IndexError, TypeError):
                logger.warning("view_submission payload no callback_id to trigger on")
                return
            logger.debug(f"view payload callback_id {callback_id}")
            logger.debug(f"view view_submission {plugin_actions.view.keys()}")
            if callback_id in plugin_actions.view:
                cmd = plugin_actions.view[callback_id]
                view_obj = _gen_view(request.payload, slack_client)
                fn = cast(Callable[..., Awaitable[None]], cmd.function)
                await fn(view_obj)

    return view_event_handler


def generate_message_matcher(settings: Mapping) -> re.Pattern[str]:
    alias_regex = ""
    if "ALIASES" in settings:
        logger.debug("Setting aliases to %s", settings["ALIASES"])
        alias_alternatives = "|".join([re.escape(alias) for alias in settings["ALIASES"].split(",")])
        alias_regex = f"|(?P<alias>{alias_alternatives})"
    return re.compile(
        rf"^(?:<@(?P<atuser>\w+)>:?|(?P<username>\w+):{alias_regex}) ?(?P<text>.*)$",
        re.DOTALL,
    )


async def handle_message(
    event: dict[str, Any],
    bot_name: str,
    bot_id: str,
    plugin_actions: RegisteredActions,
    message_matcher: re.Pattern,
    slack_client: SlackClient,
    log_handled_message: bool,
    force_user_lookup: bool,
) -> None:
    # Handle message subtype 'message_changed' to allow the bot to respond to edits
    if "subtype" in event and event["subtype"] == "message_changed":
        channel_type = event["channel_type"]
        channel = event["channel"]
        event = event["message"]
        event["channel_type"] = channel_type
        event["channel"] = channel
        event["subtype"] = "message_changed"
    if "user" in event and not event["user"] == bot_id:
        listeners = list(plugin_actions.listen_to.values())
        respond_to_msg = _check_bot_mention(
            event,
            bot_name,
            bot_id,
            message_matcher,
        )
        if respond_to_msg:
            listeners += list(plugin_actions.respond_to.values())
            await dispatch_listeners(respond_to_msg, listeners, slack_client, log_handled_message, force_user_lookup)
        else:
            await dispatch_listeners(event, listeners, slack_client, log_handled_message, force_user_lookup)


def _check_bot_mention(
    event: dict[str, Any], bot_name: str, bot_id: str, message_matcher: re.Pattern[str]
) -> dict[str, Any] | None:
    full_text = event.get("text", "")
    channel_type = event["channel_type"]
    m = message_matcher.match(full_text)

    if channel_type == "channel" or channel_type == "group":
        if not m:
            return None

        matches = m.groupdict()

        atuser = matches.get("atuser")
        username = matches.get("username")
        text = matches.get("text")
        alias = matches.get("alias")

        if alias:
            atuser = bot_id

        if atuser != bot_id and username != bot_name:
            # a channel message at other user
            return None

        event["text"] = text
    else:
        if m:
            event["text"] = m.groupdict().get("text", None)
    return event


def _gen_message(event: dict[str, Any], slack_client: SlackClient) -> Message:
    return Message(slack_client, event)


def _gen_command(cmd_payload: dict[str, Any], slack_client: SlackClient) -> Command:
    return Command(slack_client, cmd_payload)


def _gen_interactive(interactive_payload: dict[str, Any], slack_client: SlackClient) -> Command:
    return Interactive(slack_client, interactive_payload)


def _gen_view(view_payload: dict[str, Any], slack_client: SlackClient) -> Command:
    return View(slack_client, view_payload)


async def dispatch_listeners(
    event: dict[str, Any],
    message_handlers: list[MessageHandler],
    slack_client: SlackClient,
    log_handled_message: bool,
    force_user_lookup: bool,
) -> None:
    handler_funcs = []
    for handler in message_handlers:
        matcher = handler.regex
        if "subtype" in event and event["subtype"] == "message_changed" and not handler.handle_message_changed:
            continue
        match = matcher.search(event.get("text", ""))
        if match:
            if force_user_lookup and event["user"] not in slack_client.users:
                user = await slack_client.get_user(event["user"])
            message = _gen_message(event, slack_client)
            extra_params = {**match.groupdict()}
            handler_logger = create_scoped_logger(
                handler.class_name, handler.function.__name__, message.sender.id, message.sender.name
            )
            if log_handled_message:
                handler_logger.info("Handling message", message=message.text)
            if "logger" in handler.function_signature.parameters:
                extra_params["logger"] = handler_logger
            handler_funcs.append(handler.function(message, **extra_params))
    await asyncio.gather(*handler_funcs)
    return


async def dispatch_event_handlers(
    event: dict[str, Any], event_handlers: list[Callable[[dict[str, Any]], Awaitable[None]]]
) -> None:
    handler_funcs = [f(event) for f in event_handlers]
    await asyncio.gather(*handler_funcs)


def create_scoped_logger(class_name: str, function_name: str, user_id: str, user_name: str) -> BoundLogger:
    fq_fn_name = f"{class_name}.{function_name}"
    handler_logger = get_logger(fq_fn_name)
    handler_logger = handler_logger.bind(user_id=user_id, user_name=user_name)
    return handler_logger
