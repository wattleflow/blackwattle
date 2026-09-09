# Module name: connections/localmodels.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #

from __future__ import annotations
import os
import glob
from pathlib import Path
from typing import Optional


# --------------------------------------------------------------------------- #
# endregion Imports                                                            #
# --------------------------------------------------------------------------- #


class StoredModels:
    def __init__(self, name: str, path: str | Path):
        self.name = name
        self.base_path = os.path.abspath(
            str(path.absolute()) if isinstance(path, Path) else str(path)
        )

    @property
    def model_name(self) -> str:
        safe_name = self.name.replace("/", "--")
        search_pattern = os.path.join(self.base_path, f"models--{safe_name}", "snapshots", "*")
        matches = glob.glob(search_pattern)

        for match in matches:
            if self._is_valid_model_dir(match):
                return match

        raise FileNotFoundError(f"Model '{self.name}' not found in '{self.base_path}'.")

    def _is_valid_model_dir(self, directory: str) -> bool:
        valid_files = ["pytorch_model.bin", "model.safetensors", "config.json"]
        files = os.listdir(directory)
        return any(file in files for file in valid_files)


class DownloadedModels:
    """Reads the local HuggingFace hub cache: which models are already on disk."""

    def __init__(self, base_path: Optional[str | Path] = None):
        self.base_path = str(base_path) if base_path else self._default_cache()

    @staticmethod
    def _default_cache() -> str:
        """Locate the hub cache without depending on one library's constant.

        `transformers.utils.hub.TRANSFORMERS_CACHE` is deprecated in favour of
        `huggingface_hub`'s `HF_HUB_CACHE`, and neither library is a dependency
        of this package — so each source is tried and the documented default
        (`$HF_HOME/hub`, else `~/.cache/huggingface/hub`) closes the chain.
        """
        try:
            from huggingface_hub.constants import HF_HUB_CACHE

            return str(HF_HUB_CACHE)
        except ImportError:
            pass

        try:
            from transformers.utils.hub import TRANSFORMERS_CACHE

            return str(TRANSFORMERS_CACHE)
        except ImportError:
            pass

        home = os.environ.get("HF_HOME") or os.path.expanduser("~/.cache/huggingface")
        return os.path.join(home, "hub")

    def exists(self, name: str) -> bool:
        """True when `name` (e.g. `Helsinki-NLP/opus-mt-en-hr`) is cached."""
        return any(cached == name for cached, _ in self.list_models())

    def copy_models(self, destination: str):
        destination = os.path.abspath(destination)
        os.makedirs(destination, exist_ok=True)

        import shutil

        for model_name, model_path in self.list_models():
            dest_path = os.path.join(destination, model_name)
            if not os.path.exists(dest_path):
                shutil.copytree(model_path, dest_path)
                print(f"✔ Kopirano: {model_name} → {dest_path}")
            else:
                print(f"ℹ Preskočeno (već postoji): {model_name}")

    def list_models(self) -> list:
        if Path(self.base_path).name != "hub":
            models_dir = os.path.join(self.base_path, "hub")
        else:
            models_dir = self.base_path

        # Correct pattern za HuggingFace models
        search_pattern = os.path.join(models_dir, "models--*", "snapshots", "*")

        model_paths = []
        for path in glob.glob(search_pattern):
            if self._is_valid_model_dir(path):
                model_name = self._extract_model_name(path)
                model_paths.append((model_name, path))

        return model_paths

    def _is_valid_model_dir(self, directory: str) -> bool:
        required_files = ["pytorch_model.bin", "model.safetensors", "config.json"]
        try:
            files = os.listdir(directory)
            return any(f in files for f in required_files)
        except FileNotFoundError:
            return False

    def _extract_model_name(self, path: str) -> str:
        # Retrieve model from path .../models--facebook--bart-base/...
        parts = path.split(os.sep)
        for part in parts:
            if part.startswith("models--"):
                return part.replace("models--", "").replace("--", "/")
        return "unknown"
