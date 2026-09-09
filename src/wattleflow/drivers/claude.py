# Module name: drivers/claude.py
# Author: (wattleflow@outlook.com)
# Copyright: @ 2022-2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# IMPORTANT: This driver requires the anthropic SDK:                          #
#       pip install anthropic                                                 #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #

from __future__ import annotations

from typing import Any, ClassVar, Dict, List, Tuple

from wattleflow.concrete.driver import (
    DriverAction,
    DriverMetadata,
    GenericDriver,
)
from wattleflow.concrete.exception import DriverException
from wattleflow.enums.event import Event
from wattleflow.decorators.oscal import oscal_driver

# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Constants                                                            #
# --------------------------------------------------------------------------- #

# A model is addressed by a complete id — never an id with a date suffix appended.
DEFAULT_MODEL = "claude-opus-5"

# `max_tokens` is a cap, not a spend: a low cap truncates the answer mid-sentence
# and costs a second call. Kept under the SDK's HTTP timeout for non-streaming.
DEFAULT_MAX_TOKENS = 16000

# --------------------------------------------------------------------------- #
# endregion Constants                                                         #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Exceptions                                                           #
# --------------------------------------------------------------------------- #


class DriverClaudeException(DriverException):
    pass


# --------------------------------------------------------------------------- #
# endregion Exceptions                                                        #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Driver                                                               #
# --------------------------------------------------------------------------- #


@oscal_driver(strict=False)
class DriverClaude(GenericDriver):
    """Anthropic API driver.

    Configuration keys fall into two classes, kept apart because they belong to
    different owners once access moves behind a connection: **access** says how
    the service is reached, **call** says what one request carries. Only the
    first class is a connection concern.
    """

    # Access — how the service is reached.
    ACCESS = [
        "api_key",
        "base_url",
        "max_retries",
        "model",
        "timeout",
    ]

    # Call — what one request carries; the caller owns these.
    CALL = [
        "client",
        "create",
        "max_tokens",
        "normalise",
        "prompts",
        "read_path",
        "system_prompt",
        "write_path",
    ]

    ALLOWED = ACCESS + CALL
    # OSCAL: API key handling (configuration, ANTHROPIC_API_KEY, signed-in session);
    # transport crypto belongs to the anthropic SDK, so sc-8 is not claimed here.
    OSCAL_CONTROLS: ClassVar[Tuple[str, ...]] = ("ac-3", "ia-5")

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._client: Any = None
        self._prompt_index: Dict[str, str] = {}
        self.ensure_live()

    def metadata(self) -> DriverMetadata:
        return DriverMetadata(
            name=self.__class__.__name__,
            version="1.0",
            protocol="https",
            capabilities=["read", "write", "complete"],
        )

    # region lifecycle
    def load(self) -> None:
        self.debug(msg=Event.Load.name, step=Event.Started.name)

        try:
            from anthropic import Anthropic
        except ImportError as e:
            raise ModuleNotFoundError(
                "anthropic library is missing. Install:\n\tpip install anthropic"
            ) from e

        # An unset ANTHROPIC_API_KEY does not mean there is no credential: the SDK
        # resolves ANTHROPIC_API_KEY -> ANTHROPIC_AUTH_TOKEN -> OAuth profile ->
        # workload identity federation -> default profile. Demanding a key here
        # would rule out every ambient credential, which is the safer setup.
        options: Dict[str, Any] = {}
        for name in ("api_key", "base_url"):
            value = getattr(self, name, None)
            if value:
                options[name] = value
        if getattr(self, "timeout", None) is not None:
            options["timeout"] = float(self.timeout)
        if getattr(self, "max_retries", None) is not None:
            options["max_retries"] = int(self.max_retries)

        try:
            self._client = Anthropic(**options)
        except Exception as e:
            self.debug(msg=Event.Load.name, step=Event.Failed.name, error=str(e))
            raise DriverClaudeException(
                caller=self,
                error=(
                    f"Cannot construct the Anthropic client: {e}. Provide "
                    "configuration.api_key, set ANTHROPIC_API_KEY, or sign in so the "
                    "SDK resolves a profile."
                ),
            ) from e

        prompts: List[Dict[str, str]] = list(self.prompts or [])
        self._prompt_index = {
            (p.get("name") or "").strip(): (p.get("content") or "")
            for p in prompts
            if p.get("name")
        }

        self.debug(
            msg=Event.Load.name,
            step=Event.Completed.name,
            prompts=list(self._prompt_index.keys()),
        )

    def close(self) -> None:
        self.debug(msg=Event.Close.name, step=Event.Started.name)
        if not self.can(DriverAction.UNLOAD):
            return
        self._client = None
        self.debug(msg=Event.Close.name, step=Event.Completed.name)

    # endregion lifecycle

    # region public API
    def prompt(self, name: str) -> str:
        text = self._prompt_index.get(name)
        if not text:
            raise DriverClaudeException(
                caller=self,
                error=f"Unknown prompt {name!r}; defined: {sorted(self._prompt_index)}",
            )
        return text

    def read(self, uri: str, **kwargs) -> str:
        return self.prompt(uri)

    def write(self, uri: str, **kwargs) -> str:
        prompt_name = kwargs.pop("prompt", uri)
        content = kwargs.pop("content", "") or ""
        if not content.strip():
            raise DriverClaudeException(caller=self, error="content is empty")
        return self.complete(prompt_name=prompt_name, content=content, **kwargs)

    def complete(
        self,
        prompt_name: str,
        content: str,
        cache: bool = True,
        **kwargs,
    ) -> str:
        self.ensure_live()

        instruction = self.prompt(prompt_name)
        client_cfg = self._messages_create_cfg()

        model = kwargs.pop("model", None) or client_cfg.get("model") or self.model or DEFAULT_MODEL
        max_tokens = (
            kwargs.pop("max_tokens", None)
            or client_cfg.get("max_tokens")
            or self.max_tokens
            or DEFAULT_MAX_TOKENS
        )

        system_blocks = self._build_system_blocks(client_cfg, instruction, cache=cache)

        try:
            response = self._client.messages.create(
                model=model,
                max_tokens=int(max_tokens),
                system=system_blocks,
                messages=[{"role": "user", "content": content}],
                # Remaining request options travel on. Dropping them silently made
                # every per-call option unreachable through this driver.
                **kwargs,
            )
        except Exception as e:
            self.debug(
                msg=Event.Write.name, step=Event.Failed.name, error=str(e), prompt=prompt_name
            )
            raise DriverClaudeException(caller=self, error=str(e)) from e

        # A declined request answers 200 with empty text — read the stop reason
        # before the content, or the caller sees "" and calls it an empty answer.
        stop_reason = getattr(response, "stop_reason", None)
        if stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            raise DriverClaudeException(
                caller=self,
                error=(
                    f"Request declined by the model "
                    f"(category={getattr(details, 'category', None)}): "
                    f"{getattr(details, 'explanation', '') or ''}"
                ).strip(),
                prompt=prompt_name,
                model=model,
            )

        text = "".join(
            getattr(block, "text", "") for block in getattr(response, "content", []) or []
        ).strip()

        if stop_reason == "max_tokens":
            self.warning(
                msg=Event.Write.name,
                step=Event.Check.name,
                error="Response truncated: max_tokens reached.",
                max_tokens=int(max_tokens),
                chars=len(text),
            )

        self.debug(
            msg=Event.Write.name,
            step=Event.Completed.name,
            prompt=prompt_name,
            model=model,
            stop_reason=stop_reason,
            chars=len(text),
        )
        return text

    # endregion public API

    # region private
    def _messages_create_cfg(self) -> Dict[str, Any]:
        client = self.client or {}
        try:
            return (client.get("beta", {}).get("messages", {}).get("create", {})) or {}
        except AttributeError:
            return {}

    def _build_system_blocks(
        self,
        client_cfg: Dict[str, Any],
        instruction: str,
        cache: bool,
    ) -> List[Dict[str, Any]]:
        blocks: List[Dict[str, Any]] = []

        # Static system prompt (cacheable across calls — long-lived context).
        sys_prompt = self.system_prompt or instruction
        blocks.append({"type": "text", "text": sys_prompt})

        configured = client_cfg.get("system") or []
        for entry in configured:
            if not isinstance(entry, dict):
                continue
            text = entry.get("text") or ""
            if text in ("SYSTEM_PROMPT", "BIG_CONTEXT"):
                continue
            block = {"type": "text", "text": text}
            if cache and entry.get("cache_control"):
                block["cache_control"] = entry["cache_control"]
            blocks.append(block)

        if cache and len(blocks) == 1:
            blocks[0]["cache_control"] = {"type": "ephemeral"}

        return blocks

    # endregion private


# --------------------------------------------------------------------------- #
# endregion Driver                                                            #
# --------------------------------------------------------------------------- #
