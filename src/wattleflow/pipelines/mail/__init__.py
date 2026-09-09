# Module name: pipelines/mail/__init__.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

# --------------------------------------------------------------------------- #
# One mail domain, one package: the reader family (extract — the shared step
# and both container readers, RFC 822 .eml and OLE2 .msg) and the attachment
# fan-out (attachments). Each reader is a `read()` override on the shared step,
# so the three share one module (CLAUDE.md §2.6). The RFC 822 parser they use
# is a capability, not a pipeline step — it lives in helpers/parsers/mail.py.
# Eager aggregation is safe here — every module imports stdlib and wattleflow
# only; extract-msg is imported inside `MailParser._from_ole2`, not at module
# level, so the OLE2 dependency never reaches this aggregate (DR-WFL-007).
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region imports                                                              #
# --------------------------------------------------------------------------- #
from . import attachments  # noqa: F401
from . import extract  # noqa: F401
from .attachments import *  # noqa: F403
from .extract import *  # noqa: F403

# --------------------------------------------------------------------------- #
# endregion imports                                                           #
# --------------------------------------------------------------------------- #

__all__ = [
    *extract.__all__,
    *attachments.__all__,
]
