# Module name: helpers/cloud/cloud_secrets.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #

from __future__ import annotations
from typing import Optional

from wattleflow.helpers.config_adapter import ISecretResolver

# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

# NOTE: Cloud secret backends live here, not in the clean core, because each one
# references a third-party SDK (DR-WFL-002 §2.1: a lazy reference still fixes the
# home distribution). The core keeps the stable abstraction (ISecretResolver,
# SecretResolverChain) and its stdlib-only resolvers (env, dotenv); these are the
# third-party adapters behind it (DIP). Register them explicitly:
#
#   from wattleflow.helpers.cloud.cloud_secrets import AwsSecretsResolver
#   chain.add(AwsSecretsResolver(region_name="ap-southeast-2"))

__all__ = [
    "AwsSecretsResolver",
    "AzureKeyVaultResolver",
    "GcpSecretResolver",
    "VaultResolver",
]


# --------------------------------------------------------------------------- #
# region Resolvers                                                            #
# --------------------------------------------------------------------------- #


class AwsSecretsResolver(ISecretResolver):
    """Resolves ${aws:secret-id/key} references from AWS Secrets Manager.

    ref format: secret-id/json-key  (key is optional for plain-string secrets)
    """

    PREFIX = "aws"

    def __init__(self, region_name: str = "us-east-1") -> None:
        self._region = region_name

    def _fetch(self, ref: str) -> Optional[str]:
        try:
            import boto3  # noqa: PLC0415
            import json  # noqa: PLC0415

            client = boto3.client("secretsmanager", region_name=self._region)
            parts = ref.rsplit("/", 1)
            secret_id = parts[0] if len(parts) == 2 else ref
            key = parts[1] if len(parts) == 2 else None
            response = client.get_secret_value(SecretId=secret_id)
            secret = response.get("SecretString", "")
            if key:
                return json.loads(secret).get(key)
            return secret
        except Exception:
            return None


class AzureKeyVaultResolver(ISecretResolver):
    """Resolves ${azure:secret-name} references from Azure Key Vault."""

    PREFIX = "azure"

    def __init__(self, vault_url: str) -> None:
        self._vault_url = vault_url

    def _fetch(self, ref: str) -> Optional[str]:
        try:
            from azure.keyvault.secrets import SecretClient  # noqa: PLC0415
            from azure.identity import DefaultAzureCredential  # noqa: PLC0415

            client = SecretClient(
                vault_url=self._vault_url,
                credential=DefaultAzureCredential(),
            )
            return client.get_secret(ref).value
        except Exception:
            return None


class GcpSecretResolver(ISecretResolver):
    """Resolves ${gcp:projects/P/secrets/S/versions/V} references from GCP Secret Manager."""

    PREFIX = "gcp"

    def _fetch(self, ref: str) -> Optional[str]:
        try:
            from google.cloud import secretmanager  # noqa: PLC0415

            client = secretmanager.SecretManagerServiceClient()
            response = client.access_secret_version(request={"name": ref})
            return response.payload.data.decode("UTF-8")
        except Exception:
            return None


class VaultResolver(ISecretResolver):
    """Resolves ${vault:secret/path/key} references from HashiCorp Vault (KV v2)."""

    PREFIX = "vault"

    def __init__(self, url: str, token: str) -> None:
        self._url = url
        self._token = token

    def _fetch(self, ref: str) -> Optional[str]:
        try:
            import hvac  # noqa: PLC0415

            client = hvac.Client(url=self._url, token=self._token)
            parts = ref.rsplit("/", 1)
            path = parts[0] if len(parts) == 2 else ref
            key = parts[1] if len(parts) == 2 else None
            data = client.secrets.kv.read_secret_version(path=path)["data"]["data"]
            return data.get(key) if key else str(data)
        except Exception:
            return None


# --------------------------------------------------------------------------- #
# endregion Resolvers                                                         #
# --------------------------------------------------------------------------- #
