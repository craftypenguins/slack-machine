from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Callable, Any, Awaitable, AsyncGenerator
from inspect import Signature

from slack_sdk.models import JsonObject

from machine.plugins.base import MachineBasePlugin


@dataclass
class HumanHelp:
    command: str
    help: str


@dataclass
class Manual:
    human: dict[str, dict[str, HumanHelp]]
    robot: dict[str, list[str]]


@dataclass
class MessageHandler:
    class_: MachineBasePlugin
    class_name: str
    function: Callable[..., Awaitable[None]]
    function_signature: Signature
    regex: re.Pattern[str]
    handle_message_changed: bool


@dataclass
class CommandHandler:
    class_: MachineBasePlugin
    class_name: str
    function: Callable[..., Awaitable[None] | AsyncGenerator[dict | JsonObject | str, None]]
    function_signature: Signature
    command: str
    is_generator: bool


@dataclass
class InteractiveHandler:
    class_: MachineBasePlugin
    class_name: str
    function: Callable[..., Awaitable[None] | AsyncGenerator[dict | JsonObject | str, None]]
    function_signature: Signature
    action_id: str


@dataclass
class ViewHandler:
    class_: MachineBasePlugin
    class_name: str
    function: Callable[..., Awaitable[None] | AsyncGenerator[dict | JsonObject | str, None]]
    function_signature: Signature
    callback_id: str


@dataclass
class RegisteredActions:
    listen_to: dict[str, MessageHandler] = field(default_factory=dict)
    respond_to: dict[str, MessageHandler] = field(default_factory=dict)
    interactive: dict[str, InteractiveHandler] = field(default_factory=dict)
    view: dict[str, ViewHandler] = field(default_factory=dict)
    process: dict[str, dict[str, Callable[[dict[str, Any]], Awaitable[None]]]] = field(default_factory=dict)
    command: dict[str, CommandHandler] = field(default_factory=dict)
