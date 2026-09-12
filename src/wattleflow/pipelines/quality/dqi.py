# Module name: pipelines/quality/dqi.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
import ast
import operator
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from math import exp, sqrt
from typing import Any, ClassVar
from wattleflow.helpers.dtime import Now
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

__all__ = ["DataQualityIndex", "QualityRules", "RunningAggregate"]

# --------------------------------------------------------------------------- #
# region Data quality                                                         #
# --------------------------------------------------------------------------- #


@dataclass
class DataQualityIndex:
    """Quality of one record at one checkpoint: the dimension vector and the rules it failed.

    `dqi` is the declared weighted index; without weights it stays None and only the vector is
    reported. An unmeasured dimension is absent from the vector, never 1.0 (V3).
    """

    record_id: str
    checkpoint: str
    dimensions: dict[str, float] = field(default_factory=dict)
    failed_rules: list[str] = field(default_factory=list)
    dqi: float | None = None
    timestamp: datetime = field(default_factory=Now.utc)

    def row(self) -> dict[str, Any]:
        """Flat report row: one column per measured dimension, failed rules joined."""
        return {
            "record_id": self.record_id,
            "checkpoint": self.checkpoint,
            "dqi": None if self.dqi is None else round(self.dqi, 4),
            **{name: round(value, 4) for name, value in self.dimensions.items()},
            "failed_rules": "; ".join(self.failed_rules),
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class RunningAggregate:
    """Running count, mean, variance, minimum and maximum of the index, and per-dimension means."""

    count: int = 0
    mean: float = 0.0
    minimum: float = float("inf")
    maximum: float = float("-inf")
    dimension_means: dict[str, float] = field(default_factory=dict)
    _m2: float = 0.0
    _dimension_counts: dict[str, int] = field(default_factory=dict)

    def update(self, dqi: float | None, dimensions: dict[str, float] | None = None) -> None:
        """Add one measurement."""
        # Welford (1962): one pass, O(1) memory, numerically stable.
        if dqi is not None:
            self.count += 1
            delta = dqi - self.mean
            self.mean += delta / self.count
            self._m2 += delta * (dqi - self.mean)
            self.minimum = min(self.minimum, dqi)
            self.maximum = max(self.maximum, dqi)
        for name, value in (dimensions or {}).items():
            count = self._dimension_counts.get(name, 0) + 1
            previous = self.dimension_means.get(name, 0.0)
            self.dimension_means[name] = previous + (value - previous) / count
            self._dimension_counts[name] = count

    @property
    def variance(self) -> float:
        """Sample variance, with Bessel's correction."""
        return self._m2 / (self.count - 1) if self.count > 1 else 0.0

    @property
    def stdev(self) -> float:
        """Sample standard deviation."""
        return sqrt(self.variance)

    def snapshot(self) -> dict[str, Any]:
        """The aggregate as a serialisable mapping."""
        measured = self.count > 0
        return {
            "count": self.count,
            "mean": round(self.mean, 4) if measured else None,
            "minimum": round(self.minimum, 4) if measured else None,
            "maximum": round(self.maximum, 4) if measured else None,
            "variance": round(self.variance, 4),
            "stdev": round(self.stdev, 4),
            "dimension_means": {k: round(v, 4) for k, v in self.dimension_means.items()},
        }


@dataclass
class QualityRules:
    """Rules declared per ISO/IEC 25012 dimension, and the measurement of one record against them.

    Each dimension is the ratio of rules the record satisfies (ISO 8000-8); a dimension with no
    rule is not measured.
    """

    identifier: str | None = None
    mandatory: list[str] = field(default_factory=list)
    patterns: dict[str, str] = field(default_factory=dict)
    ranges: dict[str, list[float]] = field(default_factory=dict)
    formats: dict[str, str] = field(default_factory=dict)
    enumerations: dict[str, list[Any]] = field(default_factory=dict)
    expressions: list[str] = field(default_factory=list)
    reference: dict[str, dict[str, Any]] = field(default_factory=dict)
    timestamp: str | None = None
    decay: float = 0.0
    keys: list[str] = field(default_factory=list)
    weights: dict[str, float] = field(default_factory=dict)

    DIMENSIONS: ClassVar[tuple[str, ...]] = (
        "completeness", "validity", "consistency", "accuracy", "currentness", "uniqueness",
    )
    OPERATORS: ClassVar[dict[type, Any]] = {
        ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt, ast.LtE: operator.le,
        ast.Gt: operator.gt, ast.GtE: operator.ge, ast.Add: operator.add, ast.Sub: operator.sub,
        ast.Mult: operator.mul, ast.Div: operator.truediv, ast.USub: operator.neg,
        ast.Not: operator.not_,
        ast.In: lambda a, b: operator.contains(b, a),
        ast.NotIn: lambda a, b: not operator.contains(b, a),
    }
    FUNCTIONS: ClassVar[dict[str, Any]] = {"float": float, "int": int, "str": str, "len": len}
    NODES: ClassVar[tuple[type, ...]] = (
        ast.Expression, ast.Constant, ast.Name, ast.Load, ast.Tuple, ast.List, ast.BoolOp,
        ast.And, ast.Or, ast.UnaryOp, ast.BinOp, ast.Compare, ast.Call,
    )

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> QualityRules:
        """Rules from configuration; an unknown key, pattern, expression or weight fails here."""
        rules = cls(**(data or {}))
        for pattern in rules.patterns.values():
            re.compile(pattern)
        for expression in rules.expressions:
            cls.check(expression)
        if rules.weights:
            if not set(rules.weights) <= set(cls.DIMENSIONS):
                raise ValueError(f"weights name unknown dimensions: {sorted(rules.weights)}")
            if abs(sum(rules.weights.values()) - 1.0) > 1e-9:
                raise ValueError("weights must sum to 1.0")
        return rules

    def measure(
        self,
        record: dict[str, Any],
        checkpoint: str,
        seen: set[tuple[str, ...]] | None = None,
    ) -> DataQualityIndex:
        """Quality of one record at a checkpoint; the record is only read."""
        failed: list[str] = []
        vector = {
            "completeness": self.completeness(record, failed),
            "validity": self.validity(record, failed),
            "consistency": self.consistency(record, failed),
            "accuracy": self.accuracy(record, failed),
            "currentness": self.currentness(record, failed),
            "uniqueness": self.uniqueness(record, failed, seen),
        }
        dimensions = {name: value for name, value in vector.items() if value is not None}
        return DataQualityIndex(
            record_id=str(record.get(self.identifier) or "") if self.identifier else "",
            checkpoint=checkpoint,
            dimensions=dimensions,
            failed_rules=failed,
            dqi=self.index(dimensions),
        )

    def index(self, dimensions: dict[str, float]) -> float | None:
        """Declared weighted index; None without weights or with a weighted dimension unmeasured."""
        if not self.weights or not set(self.weights) <= set(dimensions):
            return None
        return sum(weight * dimensions[name] for name, weight in self.weights.items())

    def completeness(self, record: dict[str, Any], failed: list[str]) -> float | None:
        """Mandatory fields that are filled."""
        results = [
            (f"completeness:missing:{name}", not self.empty(record.get(name)))
            for name in self.mandatory
        ]
        return self.ratio(results, failed)

    def validity(self, record: dict[str, Any], failed: list[str]) -> float | None:
        """Filled fields that pass their pattern, range, date format or enumeration."""
        declared = (
            ("pattern", self.patterns),
            ("range", self.ranges),
            ("format", self.formats),
            ("enumeration", self.enumerations),
        )
        results: list[tuple[str, bool]] = []
        for kind, rules in declared:
            for name, rule in rules.items():
                value = record.get(name)
                if not self.empty(value):
                    results.append((f"validity:{kind}:{name}", self.passes(kind, value, rule)))
        return self.ratio(results, failed)

    def consistency(self, record: dict[str, Any], failed: list[str]) -> float | None:
        """Cross-field expressions that hold."""
        results = [(f"consistency:{e}", self.holds(e, record)) for e in self.expressions]
        return self.ratio(results, failed)

    def accuracy(self, record: dict[str, Any], failed: list[str]) -> float | None:
        """Fields equal to the reference held for this record, compared as text."""
        key = str(record.get(self.identifier)) if self.identifier else None
        expected = self.reference.get(key, {}) if key else {}
        results = [
            (f"accuracy:{name}", str(record.get(name)) == str(value))
            for name, value in expected.items()
        ]
        return self.ratio(results, failed)

    def currentness(self, record: dict[str, Any], failed: list[str]) -> float | None:
        """exp(-decay × age in hours) of the record's timestamp."""
        if not self.timestamp:
            return None
        try:
            moment = datetime.fromisoformat(str(record.get(self.timestamp)))
        except ValueError:
            failed.append(f"currentness:unreadable:{self.timestamp}")
            return None
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        age = max((Now.utc() - moment).total_seconds() / 3600, 0.0)
        return exp(-self.decay * age)

    def uniqueness(
        self,
        record: dict[str, Any],
        failed: list[str],
        seen: set[tuple[str, ...]] | None,
    ) -> float | None:
        """1.0 for a key combination not seen before in the pass, 0.0 for a repeat."""
        if not self.keys or seen is None:
            return None
        key = tuple(str(record.get(name)) for name in self.keys)
        if key in seen:
            failed.append("uniqueness:duplicate:" + "|".join(key))
            return 0.0
        seen.add(key)
        return 1.0

    @classmethod
    def check(cls, expression: str) -> None:
        """Refuse an expression that uses anything beyond the allowed nodes and functions."""
        for node in ast.walk(ast.parse(expression, mode="eval")):
            if not isinstance(node, cls.NODES + tuple(cls.OPERATORS)):
                raise ValueError(f"not allowed in a rule: {type(node).__name__} in {expression!r}")
            if isinstance(node, ast.Call) and (
                not isinstance(node.func, ast.Name) or node.func.id not in cls.FUNCTIONS
                or node.keywords
            ):
                raise ValueError(f"only {sorted(cls.FUNCTIONS)} may be called: {expression!r}")

    @classmethod
    def holds(cls, expression: str, record: dict[str, Any]) -> bool:
        """Truth of a checked expression over the record; a missing field or bad type is false."""
        try:
            return bool(cls.value(ast.parse(expression, mode="eval").body, record))
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            return False

    @classmethod
    def value(cls, node: ast.AST, record: dict[str, Any]) -> Any:
        """Value of one node of a checked expression; walked, never passed to eval."""
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            return record[node.id]
        if isinstance(node, (ast.Tuple, ast.List)):
            return [cls.value(item, record) for item in node.elts]
        if isinstance(node, ast.Call):
            return cls.FUNCTIONS[node.func.id](*(cls.value(a, record) for a in node.args))
        if isinstance(node, ast.BoolOp):
            values = (cls.value(item, record) for item in node.values)
            return all(values) if isinstance(node.op, ast.And) else any(values)
        if isinstance(node, ast.UnaryOp):
            return cls.OPERATORS[type(node.op)](cls.value(node.operand, record))
        if isinstance(node, ast.BinOp):
            left, right = cls.value(node.left, record), cls.value(node.right, record)
            return cls.OPERATORS[type(node.op)](left, right)
        if isinstance(node, ast.Compare):
            left = cls.value(node.left, record)
            for op, comparator in zip(node.ops, node.comparators):
                right = cls.value(comparator, record)
                if not cls.OPERATORS[type(op)](left, right):
                    return False
                left = right
            return True
        raise ValueError(f"not allowed in a rule: {type(node).__name__}")

    @staticmethod
    def empty(value: Any) -> bool:
        """None, a blank string or an empty collection."""
        if isinstance(value, str):
            return not value.strip()
        return value is None or (isinstance(value, (list, tuple, set, dict)) and not value)

    @staticmethod
    def ratio(results: list[tuple[str, bool]], failed: list[str]) -> float | None:
        """Share of results that hold, recording the failed ones; None when nothing was checked."""
        if not results:
            return None
        failed.extend(rule for rule, holds in results if not holds)
        return sum(holds for _, holds in results) / len(results)

    @classmethod
    def passes(cls, kind: str, value: Any, rule: Any) -> bool:
        """Whether a filled value passes one validity rule of the given kind."""
        if kind == "pattern":
            return re.fullmatch(rule, str(value)) is not None
        if kind == "range":
            return cls.within(value, *rule)
        if kind == "format":
            return cls.dated(value, rule)
        return value in rule

    @staticmethod
    def within(value: Any, low: float, high: float) -> bool:
        """Whether a value reads as a number inside [low, high]."""
        try:
            return low <= float(value) <= high
        except (TypeError, ValueError):
            return False

    @staticmethod
    def dated(value: Any, form: str) -> bool:
        """Whether a value reads as a date in the given strptime format."""
        try:
            datetime.strptime(str(value), form)
        except ValueError:
            return False
        return True


# --------------------------------------------------------------------------- #
# endregion Data quality                                                      #
# --------------------------------------------------------------------------- #
