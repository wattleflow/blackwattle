# Module name: oscal/models.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
from typing import Any, ClassVar, Dict, Iterator, List, Mapping, Optional, Set, Tuple, TypeVar
from wattleflow.core import IElement, IIterator, ISyncAggregate, IVisitor
from wattleflow.concrete.iterator import LazyIterator
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Constants                                                            #
# --------------------------------------------------------------------------- #
__author__ = "WattleFlow"
__copyright__ = "© 2022–2026 WattleFlow. All rights reserved"
# --------------------------------------------------------------------------- #
# endregion Constants                                                         #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Types                                                                #
# --------------------------------------------------------------------------- #
# The element a pruning pass carries through: a control or a group, never mixed.
Element = TypeVar("Element", bound="SelectableElement")
# --------------------------------------------------------------------------- #
# endregion Types                                                             #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Base                                                                 #
# --------------------------------------------------------------------------- #


class ModelBase(ABC):
    """Deserialisation contract shared by every OSCAL value object.

    OSCAL JSON uses kebab-case keys and the reserved Python word `class`, so
    raw keys have to be mapped onto attribute names before construction. That
    mapping is behaviour of the model, not of the module: it lives here as
    inherited members, which a subclass can extend through `KEY_ALIASES` or
    override outright.
    """

    __slots__ = ()

    # Keys whose attribute name is not a plain '-' -> '_' substitution.
    KEY_ALIASES: ClassVar[Mapping[str, str]] = {
        "class": "class_",
        "back-matter": "back_matter",
        "last-modified": "last_modified",
        "oscal-version": "oscal_version",
        "responsible-parties": "responsible_parties",
        "control-id": "control_id",
    }

    @classmethod
    @abstractmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ModelBase":
        """Build an instance from a raw OSCAL JSON object."""

    @classmethod
    def _normalise_key(cls, key: str) -> str:
        return cls.KEY_ALIASES.get(key, key.replace("-", "_"))

    @classmethod
    def _normalise(cls, data: Mapping[str, Any]) -> Dict[str, Any]:
        return {cls._normalise_key(k): v for k, v in data.items()}

    @staticmethod
    def _items(data: Optional[Mapping[str, Any]], key: str) -> List[Dict[str, Any]]:
        if not data:
            return []
        value = data.get(key, [])
        return list(value) if value else []


class OSCALElement(ModelBase, IElement, ABC):
    """An OSCAL node that a visitor can traverse, carrying framework identity.

    `name` mirrors the IWattleflow contract instead of inheriting
    wattleflow.concrete.base.Wattleflow: that root inherits Audit, whose
    __init__ assigns instance attributes, and a frozen dataclass neither calls
    it (the generated __init__ does not chain) nor tolerates it
    (FrozenInstanceError). Audit also exposes `name`, which a dataclass would
    read as a field default — fatal for `Prop`/`Part`, whose `name` is OSCAL
    data, not identity. Hence the mirror, and hence only the nodes without a
    `name` field inherit it.
    """

    __slots__ = ()

    @property
    def name(self) -> str:
        return type(self).__name__

    @abstractmethod
    def accept(self, visitor: IVisitor) -> None: ...


class SelectableElement(OSCALElement, ABC):
    """A catalogue node that a set of control ids can select a subtree from.

    Profile resolution needs to keep the parts of a catalogue a profile
    selects and drop the rest. Which children survive is knowledge of the node
    that holds them, so it lives here rather than in a resolver that would
    have to reach into `controls` and `groups` from outside.

    `pruned` answers for one node; `prune_all` is the sequence pass both
    implementations share. Elements that hold no selectable children (`Catalog`,
    `Profile`) do not inherit this contract.
    """

    __slots__ = ()

    @abstractmethod
    def pruned(self, selected: Set[str]) -> Tuple[Optional["SelectableElement"], Set[str]]:
        """Copy of this node holding only what `selected` reaches.

        Returns (node, ids_found), or (None, empty set) when nothing below
        this node survives.
        """

    @classmethod
    def prune_all(
        cls, nodes: List[Element], selected: Set[str]
    ) -> Tuple[List[Element], Set[str]]:
        """Prune every node in `nodes`, dropping those that do not survive."""
        kept: List[Element] = []
        found: Set[str] = set()
        for node in nodes:
            pruned, node_found = node.pruned(selected)
            if pruned is not None:
                kept.append(pruned)
                found.update(node_found)
        return kept, found


# --------------------------------------------------------------------------- #
# endregion Base                                                              #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Leaf types                                                           #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Prop(ModelBase):
    name: str
    value: str
    ns: Optional[str] = None
    class_: Optional[str] = None
    uuid: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Prop":
        n = cls._normalise(data)
        return cls(
            name=n["name"],
            value=n["value"],
            ns=n.get("ns"),
            class_=n.get("class_"),
            uuid=n.get("uuid"),
        )


@dataclass(frozen=True)
class Link(ModelBase):
    href: str
    rel: Optional[str] = None
    text: Optional[str] = None
    media_type: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Link":
        n = cls._normalise(data)
        return cls(
            href=n["href"],
            rel=n.get("rel"),
            text=n.get("text"),
            media_type=n.get("media_type"),
        )


@dataclass(frozen=True)
class Part(ModelBase):
    name: str
    id: Optional[str] = None
    class_: Optional[str] = None
    title: Optional[str] = None
    prose: Optional[str] = None
    props: List[Prop] = field(default_factory=list)
    links: List[Link] = field(default_factory=list)
    parts: List["Part"] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Part":
        n = cls._normalise(data)
        return cls(
            name=n["name"],
            id=n.get("id"),
            class_=n.get("class_"),
            title=n.get("title"),
            prose=n.get("prose"),
            props=[Prop.from_dict(p) for p in cls._items(n, "props")],
            links=[Link.from_dict(p) for p in cls._items(n, "links")],
            parts=[Part.from_dict(p) for p in cls._items(n, "parts")],
        )


@dataclass(frozen=True)
class Param(ModelBase):
    id: str
    label: Optional[str] = None
    class_: Optional[str] = None
    values: List[str] = field(default_factory=list)
    props: List[Prop] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Param":
        n = cls._normalise(data)
        return cls(
            id=n["id"],
            label=n.get("label"),
            class_=n.get("class_"),
            values=list(n.get("values", []) or []),
            props=[Prop.from_dict(p) for p in cls._items(n, "props")],
        )


# --------------------------------------------------------------------------- #
# endregion Leaf types                                                        #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Tree nodes                                                           #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Control(SelectableElement):
    id: str
    title: str
    class_: Optional[str] = None
    params: List[Param] = field(default_factory=list)
    props: List[Prop] = field(default_factory=list)
    links: List[Link] = field(default_factory=list)
    parts: List[Part] = field(default_factory=list)
    controls: List["Control"] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("Control.id must not be empty")
        if not self.title:
            raise ValueError(f"Control {self.id} has no title")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Control":
        n = cls._normalise(data)
        return cls(
            id=n["id"],
            title=n["title"],
            class_=n.get("class_"),
            params=[Param.from_dict(p) for p in cls._items(n, "params")],
            props=[Prop.from_dict(p) for p in cls._items(n, "props")],
            links=[Link.from_dict(p) for p in cls._items(n, "links")],
            parts=[Part.from_dict(p) for p in cls._items(n, "parts")],
            controls=[Control.from_dict(c) for c in cls._items(n, "controls")],
        )

    def pruned(self, selected: Set[str]) -> Tuple[Optional["Control"], Set[str]]:
        """Copy keeping this control if it is selected or holds a selected
        descendant; surviving children replace the original ones.
        """
        kept, found = self.prune_all(self.controls, selected)
        is_selected = self.id in selected
        if not (is_selected or kept):
            return None, set()
        if is_selected:
            found.add(self.id)
        return (self if kept == self.controls else replace(self, controls=kept)), found

    def walk_controls(self) -> Iterator["Control"]:
        """Depth-first iteration over the nested controls below this one."""
        for child in self.controls:
            yield child
            yield from child.walk_controls()

    def accept(self, visitor: IVisitor) -> None:
        visitor.visit(self)
        for child in self.controls:
            child.accept(visitor)


@dataclass(frozen=True)
class Group(SelectableElement):
    title: str
    id: Optional[str] = None
    class_: Optional[str] = None
    params: List[Param] = field(default_factory=list)
    props: List[Prop] = field(default_factory=list)
    links: List[Link] = field(default_factory=list)
    parts: List[Part] = field(default_factory=list)
    groups: List["Group"] = field(default_factory=list)
    controls: List[Control] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Group":
        n = cls._normalise(data)
        return cls(
            title=n["title"],
            id=n.get("id"),
            class_=n.get("class_"),
            params=[Param.from_dict(p) for p in cls._items(n, "params")],
            props=[Prop.from_dict(p) for p in cls._items(n, "props")],
            links=[Link.from_dict(p) for p in cls._items(n, "links")],
            parts=[Part.from_dict(p) for p in cls._items(n, "parts")],
            groups=[Group.from_dict(g) for g in cls._items(n, "groups")],
            controls=[Control.from_dict(c) for c in cls._items(n, "controls")],
        )

    def pruned(self, selected: Set[str]) -> Tuple[Optional["Group"], Set[str]]:
        """Copy keeping only surviving sub-groups and controls; an empty group
        does not survive.
        """
        groups, group_found = self.prune_all(self.groups, selected)
        controls, control_found = Control.prune_all(self.controls, selected)
        if not (groups or controls):
            return None, set()
        node = replace(self, groups=groups, controls=controls)
        return node, group_found | control_found

    def walk_controls(self) -> Iterator[Control]:
        """Depth-first iteration over every control held by this group."""
        for control in self.controls:
            yield control
            yield from control.walk_controls()
        for group in self.groups:
            yield from group.walk_controls()

    def accept(self, visitor: IVisitor) -> None:
        visitor.visit(self)
        for sub in self.groups:
            sub.accept(visitor)
        for control in self.controls:
            control.accept(visitor)


# --------------------------------------------------------------------------- #
# endregion Tree nodes                                                        #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Metadata / BackMatter                                                #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Metadata(ModelBase):
    title: str
    last_modified: str
    version: str
    oscal_version: str
    props: List[Prop] = field(default_factory=list)
    links: List[Link] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Metadata":
        n = cls._normalise(data)
        return cls(
            title=n["title"],
            last_modified=n["last_modified"],
            version=n["version"],
            oscal_version=n["oscal_version"],
            props=[Prop.from_dict(p) for p in cls._items(n, "props")],
            links=[Link.from_dict(p) for p in cls._items(n, "links")],
        )


@dataclass(frozen=True)
class BackMatter(ModelBase):
    resources: List[Dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BackMatter":
        if not data:
            return cls()
        return cls(resources=list(data.get("resources", []) or []))


# --------------------------------------------------------------------------- #
# endregion Metadata / BackMatter                                             #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Catalog                                                              #
# --------------------------------------------------------------------------- #


class _ControlIterator(LazyIterator[Control]):
    def __init__(self, catalog: "Catalog") -> None:
        super().__init__()
        self._catalog = catalog

    def create_iterator(self) -> Iterator[Control]:
        return self._catalog.walk_controls()


@dataclass(frozen=True)
class Catalog(OSCALElement, ISyncAggregate[Control]):
    uuid: str
    metadata: Metadata
    params: List[Param] = field(default_factory=list)
    controls: List[Control] = field(default_factory=list)
    groups: List[Group] = field(default_factory=list)
    back_matter: Optional[BackMatter] = None

    def __post_init__(self) -> None:
        if not self.uuid:
            raise ValueError("Catalog.uuid must not be empty")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Catalog":
        # Accept either a bare catalog object or the OSCAL wrapper {"catalog": {...}}.
        if "catalog" in data and isinstance(data["catalog"], Mapping):
            data = data["catalog"]
        n = cls._normalise(data)
        bm = n.get("back_matter")
        return cls(
            uuid=n["uuid"],
            metadata=Metadata.from_dict(n["metadata"]),
            params=[Param.from_dict(p) for p in cls._items(n, "params")],
            controls=[Control.from_dict(c) for c in cls._items(n, "controls")],
            groups=[Group.from_dict(g) for g in cls._items(n, "groups")],
            back_matter=BackMatter.from_dict(bm) if bm else None,
        )

    def walk_controls(self) -> Iterator[Control]:
        """Depth-first iteration over every control in the catalogue."""
        for control in self.controls:
            yield control
            yield from control.walk_controls()
        for group in self.groups:
            yield from group.walk_controls()

    def create_iterator(self) -> IIterator[Control]:
        return _ControlIterator(self)

    def accept(self, visitor: IVisitor) -> None:
        visitor.visit(self)
        for control in self.controls:
            control.accept(visitor)
        for group in self.groups:
            group.accept(visitor)


# --------------------------------------------------------------------------- #
# endregion Catalog                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Profile                                                              #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class IncludeControls(ModelBase):
    """Selector inside a profile import that picks controls from the source
    catalog. ASD ISM profiles use ``with_ids`` exclusively; the matching/pattern
    forms are accepted but not exercised here.
    """

    with_ids: List[str] = field(default_factory=list)
    with_child_controls: Optional[str] = None
    matching: List[Dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "IncludeControls":
        n = cls._normalise(data)
        return cls(
            with_ids=list(n.get("with_ids", []) or []),
            with_child_controls=n.get("with_child_controls"),
            matching=list(n.get("matching", []) or []),
        )


@dataclass(frozen=True)
class Import(ModelBase):
    """A single ``imports`` entry inside a Profile.

    ``href`` may be a URI to an external catalog/profile or a fragment
    (``#uuid``) referring to a resource in the profile's ``back-matter``.
    """

    href: str
    include_all: Optional[Dict[str, Any]] = None
    include_controls: List[IncludeControls] = field(default_factory=list)
    exclude_controls: List[IncludeControls] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Import":
        n = cls._normalise(data)
        return cls(
            href=n["href"],
            include_all=n.get("include_all"),
            include_controls=[
                IncludeControls.from_dict(c) for c in cls._items(n, "include_controls")
            ],
            exclude_controls=[
                IncludeControls.from_dict(c) for c in cls._items(n, "exclude_controls")
            ],
        )

    def control_ids(self) -> List[str]:
        ids: List[str] = []
        for inc in self.include_controls:
            ids.extend(inc.with_ids)
        return ids

    def excluded_control_ids(self) -> List[str]:
        ids: List[str] = []
        for exc in self.exclude_controls:
            ids.extend(exc.with_ids)
        return ids


@dataclass(frozen=True)
class Merge(ModelBase):
    as_is: Optional[bool] = None
    combine: Optional[Dict[str, Any]] = None
    flat: Optional[Dict[str, Any]] = None
    custom: Optional[Dict[str, Any]] = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Merge":
        n = cls._normalise(data)
        return cls(
            as_is=n.get("as_is"),
            combine=n.get("combine"),
            flat=n.get("flat"),
            custom=n.get("custom"),
        )


@dataclass(frozen=True)
class Profile(OSCALElement):
    """An OSCAL Profile: a selector document that tailors a source catalog.

    Unlike ``Catalog``, a profile does not own controls directly; it
    references them via ``imports[*].include_controls[*].with_ids``.
    Resolution against a source catalog is a separate concern and is not
    performed here.
    """

    uuid: str
    metadata: Metadata
    imports: List[Import] = field(default_factory=list)
    merge: Optional[Merge] = None
    modify: Optional[Dict[str, Any]] = None
    back_matter: Optional[BackMatter] = None

    def __post_init__(self) -> None:
        if not self.uuid:
            raise ValueError("Profile.uuid must not be empty")
        if not self.imports:
            raise ValueError(f"Profile {self.uuid} has no imports")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Profile":
        if "profile" in data and isinstance(data["profile"], Mapping):
            data = data["profile"]
        n = cls._normalise(data)
        merge = n.get("merge")
        bm = n.get("back_matter")
        return cls(
            uuid=n["uuid"],
            metadata=Metadata.from_dict(n["metadata"]),
            imports=[Import.from_dict(i) for i in cls._items(n, "imports")],
            merge=Merge.from_dict(merge) if merge else None,
            modify=n.get("modify"),
            back_matter=BackMatter.from_dict(bm) if bm else None,
        )

    def control_ids(self) -> List[str]:
        """Flat list of all control IDs selected across all imports."""
        ids: List[str] = []
        for imp in self.imports:
            ids.extend(imp.control_ids())
        return ids

    def excluded_control_ids(self) -> List[str]:
        """Flat list of all control IDs excluded across all imports."""
        ids: List[str] = []
        for imp in self.imports:
            ids.extend(imp.excluded_control_ids())
        return ids

    def accept(self, visitor: IVisitor) -> None:
        visitor.visit(self)


# --------------------------------------------------------------------------- #
# endregion Profile                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Public API                                                           #
# --------------------------------------------------------------------------- #
__all__ = [
    "BackMatter",
    "Catalog",
    "Control",
    "Group",
    "Import",
    "IncludeControls",
    "Link",
    "Merge",
    "Metadata",
    "ModelBase",
    "OSCALElement",
    "Param",
    "Part",
    "Profile",
    "Prop",
    "SelectableElement",
]
# --------------------------------------------------------------------------- #
# endregion Public API                                                        #
# --------------------------------------------------------------------------- #
