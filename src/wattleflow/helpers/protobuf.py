# Module name: helpers/protobuf.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

# --------------------------------------------------------------------------- #
# Helpers for working with Protocol Buffers messages in WattleFlow.
#
#  * resolve_message_class(schema)  — return a generated message class from
#                                     either a pre-compiled module reference
#                                     or a declarative descriptor dict.
#  * encode_delimited_stream(records, message_class) — varint-length prefixed
#                                     binary stream (writeDelimitedTo style).
#  * decode_delimited_stream(buffer, message_class)  — inverse of the above.
#  * record_to_message / message_to_dict — dict <-> message conversion via
#                                     ``google.protobuf.json_format``.
# --------------------------------------------------------------------------- #


from __future__ import annotations
from typing import Any, Dict, List, Optional, Type

try:
    from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
    from google.protobuf import json_format
    from google.protobuf.internal.encoder import _VarintBytes
    from google.protobuf.internal.decoder import _DecodeVarint
    from google.protobuf.message import Message
except ImportError as e:  # pragma: no cover
    raise ModuleNotFoundError(
        "protobuf library is missing. Add it manually: pip install protobuf"
    ) from e


# --------------------------------------------------------------------------- #
# Descriptor-dict → message class
# --------------------------------------------------------------------------- #

_TYPE_MAP = {
    "double": descriptor_pb2.FieldDescriptorProto.TYPE_DOUBLE,
    "float": descriptor_pb2.FieldDescriptorProto.TYPE_FLOAT,
    "int32": descriptor_pb2.FieldDescriptorProto.TYPE_INT32,
    "int64": descriptor_pb2.FieldDescriptorProto.TYPE_INT64,
    "uint32": descriptor_pb2.FieldDescriptorProto.TYPE_UINT32,
    "uint64": descriptor_pb2.FieldDescriptorProto.TYPE_UINT64,
    "sint32": descriptor_pb2.FieldDescriptorProto.TYPE_SINT32,
    "sint64": descriptor_pb2.FieldDescriptorProto.TYPE_SINT64,
    "fixed32": descriptor_pb2.FieldDescriptorProto.TYPE_FIXED32,
    "fixed64": descriptor_pb2.FieldDescriptorProto.TYPE_FIXED64,
    "bool": descriptor_pb2.FieldDescriptorProto.TYPE_BOOL,
    "string": descriptor_pb2.FieldDescriptorProto.TYPE_STRING,
    "bytes": descriptor_pb2.FieldDescriptorProto.TYPE_BYTES,
}

_LABEL_MAP = {
    "optional": descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL,
    "required": descriptor_pb2.FieldDescriptorProto.LABEL_REQUIRED,
    "repeated": descriptor_pb2.FieldDescriptorProto.LABEL_REPEATED,
}

# Per-process pool — schemas with identical fully-qualified names are reused.
_POOL = descriptor_pool.DescriptorPool()
_CACHE: Dict[str, Type[Message]] = {}


def build_message_class(schema: Dict[str, Any]) -> Type[Message]:
    """Build a protobuf message class from a descriptor dict.

    Schema shape::

        {
          "name": "FlightEvent",
          "package": "wattleflow.airtraffic",          # optional
          "syntax": "proto3",                          # optional, default proto3
          "fields": [
            {"name": "flight_no", "number": 1, "type": "string"},
            {"name": "passengers", "number": 2, "type": "int32"},
            {"name": "tags", "number": 3, "type": "string", "label": "repeated"},
            ...
          ]
        }
    """
    if not isinstance(schema, dict):
        raise TypeError("build_message_class: schema must be a dict")
    name = schema.get("name")
    if not name:
        raise ValueError("build_message_class: schema['name'] is required")

    package = (schema.get("package") or "wattleflow.runtime").strip(".")
    fq_name = f"{package}.{name}"

    cached = _CACHE.get(fq_name)
    if cached is not None:
        return cached

    file_proto = descriptor_pb2.FileDescriptorProto()
    file_proto.name = f"{fq_name}.proto"
    file_proto.package = package
    file_proto.syntax = schema.get("syntax", "proto3")

    msg_proto = file_proto.message_type.add()
    msg_proto.name = name

    for field in schema.get("fields", []):
        fname = field.get("name")
        fnumber = field.get("number")
        ftype = (field.get("type") or "string").lower()
        flabel = (field.get("label") or "optional").lower()
        if not fname or fnumber is None:
            raise ValueError(
                f"build_message_class: field requires 'name' + 'number': {field!r}"
            )
        if ftype not in _TYPE_MAP:
            raise ValueError(
                f"build_message_class: unsupported field type {ftype!r} on {fname!r}"
            )

        f = msg_proto.field.add()
        f.name = fname
        f.number = int(fnumber)
        f.type = _TYPE_MAP[ftype]
        f.label = _LABEL_MAP.get(flabel, _LABEL_MAP["optional"])
        # proto3 keeps presence info disabled by default for scalars; keep it
        # implicit unless the user explicitly asks for proto2 semantics.

    try:
        _POOL.Add(file_proto)
    except TypeError:
        # Already added under this name — fetch via the existing descriptor.
        pass

    file_desc = _POOL.FindFileByName(file_proto.name)
    msg_desc = file_desc.message_types_by_name[name]
    msg_cls = message_factory.GetMessageClass(msg_desc)
    _CACHE[fq_name] = msg_cls
    return msg_cls


def resolve_message_class(schema: Optional[Any]) -> Type[Message]:
    """Return a message class from either:

      * a pre-compiled protobuf message class (subclass of ``Message``),
      * an instance of such a class (its ``__class__`` is used),
      * a schema dict consumed by :func:`build_message_class`.
    """
    if schema is None:
        raise ValueError(
            "Protobuf schema is required (message class or descriptor dict)."
        )
    if isinstance(schema, type) and issubclass(schema, Message):
        return schema
    if isinstance(schema, Message):
        return schema.__class__
    if isinstance(schema, dict):
        # Allow the dict to embed a pre-built class as a shortcut.
        cls = schema.get("message_class")
        if isinstance(cls, type) and issubclass(cls, Message):
            return cls
        return build_message_class(schema)
    raise TypeError(
        f"resolve_message_class: cannot resolve schema of type "
        f"{type(schema).__name__}"
    )


# --------------------------------------------------------------------------- #
# dict <-> Message
# --------------------------------------------------------------------------- #


def record_to_message(record: Dict[str, Any], message_class: Type[Message]) -> Message:
    msg = message_class()
    json_format.ParseDict(
        record,
        msg,
        ignore_unknown_fields=True,
    )
    return msg


def message_to_dict(message: Message) -> Dict[str, Any]:
    return json_format.MessageToDict(
        message,
        preserving_proto_field_name=True,
        always_print_fields_with_no_presence=False,
    )


# --------------------------------------------------------------------------- #
# Length-delimited stream codec
# --------------------------------------------------------------------------- #


def encode_delimited_stream(
    records: List[Dict[str, Any]],
    message_class: Type[Message],
) -> bytes:
    """Serialise records as a sequence of <varint length><body> frames."""
    out = bytearray()
    for record in records:
        msg = record_to_message(record, message_class)
        payload = msg.SerializeToString()
        out.extend(_VarintBytes(len(payload)))
        out.extend(payload)
    return bytes(out)


def decode_delimited_stream(
    buffer: bytes,
    message_class: Type[Message],
) -> List[Dict[str, Any]]:
    """Parse a varint-length-prefixed stream into a list of dicts."""
    records: List[Dict[str, Any]] = []
    pos = 0
    n = len(buffer)
    while pos < n:
        size, pos = _DecodeVarint(buffer, pos)
        body = buffer[pos:pos + size]
        pos += size
        msg = message_class()
        msg.ParseFromString(body)
        records.append(message_to_dict(msg))
    return records
