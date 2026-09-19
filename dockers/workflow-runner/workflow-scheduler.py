#!/usr/bin/env python3
"""
Entry point for the workflow runner container.

Wires the container to the framework: imports the workflow module so its classes
register themselves, reads `app.schedule` from the YAML, and hands the run to
`SchedulerCronJob`. The adapter is built here because the YAML adapter belongs to
this distribution and the scheduler's own distribution must not import it.

  app:
    schedule:
      enabled: true      # false, or absent, runs the workflow once
      heartbeat: 20      # seconds between passes
"""

# region Imports
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import yaml

from wattleflow.helpers.config_yaml import YAMLConfig
from wattleflow.schedulers import SchedulerCronJob

# endregion Imports

__all__ = ["WorkflowRunner"]

# region Implementation


class WorkflowRunner:
    """Register the workflow's classes, build it, and run it on a heartbeat."""

    WORKFLOW = Path(__file__).parent / "01_synthetic_data.py"
    FALLBACK_HEARTBEAT = 300

    @staticmethod
    def register_classes(path: Path) -> None:
        """Execute the workflow module; importing it is what registers its classes."""
        spec = importlib.util.spec_from_file_location(path.stem, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[path.stem] = module
        spec.loader.exec_module(module)

    @staticmethod
    def read_schedule(path: Path) -> dict:
        """Return the `app.schedule` mapping, or an empty one when absent."""
        with open(path, encoding="utf-8") as handle:
            return (yaml.safe_load(handle) or {}).get("app", {}).get("schedule", {}) or {}

    @classmethod
    def heartbeat_of(cls, schedule: dict) -> int:
        """Seconds between passes, from `heartbeat` or from hours/minutes/seconds."""
        if "heartbeat" in schedule:
            return int(schedule["heartbeat"])
        total = (
            int(schedule.get("hours", 0)) * 3600
            + int(schedule.get("minutes", 0)) * 60
            + int(schedule.get("seconds", 0))
        )
        return total or cls.FALLBACK_HEARTBEAT

    @classmethod
    def run(cls) -> None:
        """Run the workflow: once, or on a heartbeat when the YAML enables it."""
        config = cls.WORKFLOW.with_suffix(".yaml")
        if not config.exists():
            print(f"Workflow configuration not found: {config}", file=sys.stderr)
            sys.exit(1)

        cls.register_classes(cls.WORKFLOW)
        schedule = cls.read_schedule(config)

        # No basicConfig here. Every framework class attaches its own stream
        # handler with the format from `infrastructure.<env>.logging`, and that
        # record also propagates; a root handler would print each line twice.
        scheduler = SchedulerCronJob(
            adapter=YAMLConfig(config.absolute()),
            heartbeat=cls.heartbeat_of(schedule),
        )
        scheduler.run(cycles=None if schedule.get("enabled", False) else 1)


# endregion Implementation

if __name__ == "__main__":
    WorkflowRunner.run()
