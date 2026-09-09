# Module name: connections/spark.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2025 WattleFlow. All rights reserved.
# License: Apache 2 Licence

# --------------------------------------------------------------------------- #
# Dependency:
#   pip install pyspark
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
import os
import shutil
import subprocess
import sys
from contextlib import contextmanager
from typing import ClassVar, Generator, Optional, Tuple
from wattleflow.concrete.connection import Connection
from wattleflow.concrete.connection import (
    ConnectionAction,
    ConnectionState,
    GenericConnection,
)
from wattleflow.concrete.exception import ConnectionException
from wattleflow.enums.event import Event

try:
    from pyspark.sql import SparkSession  # noqa: F401
except Exception as e:
    raise ModuleNotFoundError(
        f"Missing required package to run this code: [{__file__}].\n"
        "Please install it with `pip install pyspark`"
    ) from e

from wattleflow.decorators.oscal import oscal_connection
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Helpers                                                              #
# --------------------------------------------------------------------------- #


def _check_java() -> tuple[Optional[str], Optional[str]]:
    """Check Java availability.

    Returns:
        (error_message, None) — Java is not usable; error_message explains why.
        (None, version_line)  — Java is OK; version_line is the first line of
                                ``java -version`` output.
    """
    java_home = os.environ.get("JAVA_HOME")

    if java_home:
        java_bin = os.path.join(java_home, "bin", "java")
        if not os.path.isfile(java_bin):
            return (
                f"JAVA_HOME is set to '{java_home}' but '{java_bin}' was not found. "
                "Verify that JAVA_HOME points to a valid JDK/JRE installation.",
                None,
            )
        java_exe = java_bin
    else:
        java_exe = shutil.which("java")
        if java_exe is None:
            return (
                "Java executable was not found on PATH and JAVA_HOME is not set. "
                "Install Java 8, 11, or 17 and set the JAVA_HOME environment variable "
                "before starting a Spark session.",
                None,
            )

    try:
        result = subprocess.run(
            [java_exe, "-version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        version_output = (result.stderr or result.stdout).strip().splitlines()
        version_line = version_output[0] if version_output else ""
        return None, version_line
    except Exception as e:
        return (
            f"Java was found at '{java_exe}' but could not be executed: {e}",
            None,
        )


# --------------------------------------------------------------------------- #
# endregion Helpers                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Exceptions                                                           #
# --------------------------------------------------------------------------- #


class SparkConnectionError(ConnectionException):
    pass


# --------------------------------------------------------------------------- #
# endregion Exceptions                                                        #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Classes                                                              #
# --------------------------------------------------------------------------- #


@oscal_connection(strict=False)
class SparkConnection(GenericConnection):
    ALLOWED = [
        "connection_name",
        "lazy_loading",
        "app_name",
        "master",
        "config",
        "log_connection",
    ]
    # OSCAL: app_name/master/config only — no authenticator, no transport setting and no
    # cryptography in this class. An empty declaration is an explicit opt-out of the
    # gate (FR-OSCAL-14.13), not an omission.
    OSCAL_CONTROLS: ClassVar[Tuple[str, ...]] = ()

    def create_connection(self) -> None:
        self.debug(
            msg=Event.Create.name,
            step=Event.Started.name,
            name=self.connection_name,
            state=self.state.value,
        )

        if self.state in (
            ConnectionState.CREATED,
            ConnectionState.CONNECTED,
            ConnectionState.CONNECTING,
        ):
            self.debug(
                msg=Event.Create.name,
                step=Event.Check.name,
                reason="connection already created",
                state=self.state.value,
            )
            return

        if self.state is ConnectionState.FAILED:
            raise SparkConnectionError(
                caller=self,
                error=f"Cannot create connection in state '{self.state.value}'",
            )

        error, java_version = _check_java()
        if error:
            raise SparkConnectionError(caller=self, error=error)
        self.debug(msg=Event.Create.name, java=java_version)

        # Ensure the gateway subprocess uses the same Python interpreter as the
        # calling process. On conda environments this is critical — without it
        # PySpark resolves to the system Python and the gateway import fails.
        os.environ.setdefault("PYSPARK_PYTHON", sys.executable)
        os.environ.setdefault("PYSPARK_DRIVER_PYTHON", sys.executable)

        # On WSL2, PySpark cannot reliably resolve the machine hostname to an
        # address that the gateway socket can bind to. Pinning to loopback
        # prevents the JAVA_GATEWAY_EXITED race condition.
        os.environ.setdefault("SPARK_LOCAL_IP", "127.0.0.1")

        self.debug(
            msg=Event.Create.name,
            pyspark_python=os.environ["PYSPARK_PYTHON"],
            spark_local_ip=os.environ["SPARK_LOCAL_IP"],
        )

        try:
            # Copy to avoid mutating the preset values dict on repeated calls.
            spark_config: dict = dict(self._preset._values.get("config") or {})
            log_level: str = spark_config.pop("loglevel", "FATAL")

            builder = SparkSession.builder.master(self.master).appName(self.app_name)
            for key, value in spark_config.items():
                builder = builder.config(key, value)

            session: SparkSession = builder.getOrCreate()
            session.sparkContext.setLogLevel(log_level)

            self._engine = session
            self._version = session.version
            self._connection = None

        except SparkConnectionError:
            raise
        except Exception as e:
            self.notify(
                self,
                error=f"SparkSession can not be created: {e}",
                connection_name=self.connection_name,
                state=self.state.value,
            )
            self.debug(msg=Event.Create.name, step=Event.Failed.name, error=str(e))
            raise SparkConnectionError(
                caller=self,
                error=f"SparkSession can not be created: {e}",
            ) from e

        self.debug(
            msg=Event.Create.name,
            step=Event.Completed.name,
            name=self.connection_name,
            state=self.state.value,
            spark_version=self._version,
        )

    @contextmanager
    def connect(self) -> Generator[Connection, None, None]:
        self._ensure_created()

        self.debug(
            msg=Event.Connect.name,
            connection_name=self.connection_name,
            state=self.state.value,
        )

        if self.state is not ConnectionState.CREATED:
            self.notify(
                self,
                error=f"Cannot connect in state '{self.state.value}'",
                connection_name=self.connection_name,
                state=self.state.value,
            )
            raise SparkConnectionError(
                caller=self,
                error=f"Cannot connect in state '{self.state.value}'",
            )

        if self._engine is None:
            self.notify(
                self,
                error="SparkSession is not initialised",
                connection_name=self.connection_name,
                state=self.state.value,
            )
            raise SparkConnectionError(
                caller=self,
                error=f"{self.name}.connect: engine is None",
            )

        self._fsm.apply(ConnectionAction.CONNECT)

        try:
            self._connection = self._engine
            self._fsm.apply(ConnectionAction.CONNECT_OK)
        except Exception as e:
            self._fsm.apply(ConnectionAction.CONNECT_FAIL)
            self.debug(msg=Event.Connect.name, step=Event.Failed.name, error=str(e))
            raise SparkConnectionError(caller=self, error=str(e)) from e

        self.debug(
            msg=Event.Connected.name,
            connection_name=self.connection_name,
            state=self.state.value,
        )

        try:
            yield self._connection
        except Exception as e:
            self.notify(
                self,
                error=f"Error during connection use: {e}",
                connection_name=self.connection_name,
                state=self.state.value,
            )
            self.debug(msg=Event.Connect.name, step=Event.Failed.name, error=str(e))
            raise
        finally:
            self._connection = None
            self._fsm.apply(ConnectionAction.DISCONNECT)
            self.debug(
                msg=Event.Disconnected.name,
                connection_name=self.connection_name,
                note="session still alive; call ensure_closed() to stop",
            )

    def disconnect(self) -> None:
        self.debug(
            msg=Event.Disconnect.name,
            connection_name=self.connection_name,
            state=self.state.value,
        )

        try:
            if self._connection:
                self._connection = None
            if self._engine is not None:
                try:
                    self._engine.stop()
                except Exception as e:
                    self.notify(
                        self,
                        error=f"Error stopping SparkSession: {e}",
                        connection_name=self.connection_name,
                        state=self.state.value,
                    )
                finally:
                    self._engine = None
        finally:
            self._version = ""
            self.debug(
                msg=Event.Disconnected.name,
                connection_name=self.connection_name,
                state=self.state.value,
            )

    def __repr__(self) -> str:
        return (
            f"{self.name}:{self.state.value}"
            f"[master={getattr(self, 'master', '?')} app={getattr(self, 'app_name', '?')}]"
        )


# --------------------------------------------------------------------------- #
# endregion Classes                                                       #
# --------------------------------------------------------------------------- #
