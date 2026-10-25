"""Bounded personal text marks; no generated content or model calls."""
import json
import re

COLORS = {"amber", "sage", "blue", "rose"}
MAX_MARKS = 500
MAX_BYTES = 400000


def block_keys(module):
    package = module.get("package")
    if not isinstance(package, dict):
        return set()
    keys = {"intro"} | {f"objective:{i}" for i, _ in enumerate(package.get("objectives", []))}
    for i, section in enumerate(package.get("sections", [])):
        keys.update((f"heading:{i}", f"section:{i}"))
        if section.get("lesson_id") and (not i or package["sections"][i-1].get("lesson_id") != section["lesson_id"]):
            keys.add(f"lesson:{i}")
    return keys


def text(value, maximum, empty=False):
    if (not isinstance(value, str) or len(value) > maximum or (not empty and not value.strip())
            or any(0xd800 <= ord(c) <= 0xdfff for c in value)):
        raise ValueError("This text mark contains invalid or oversized text.")
    return value


def mark_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{32}", value):
        raise ValueError("This text mark has an invalid identity.")
    return value


def validate_marks(value, module):
    if not isinstance(value, list) or len(value) > MAX_MARKS:
        raise ValueError("Keep up to 500 text marks in a module.")
    keys, ids, result = block_keys(module), set(), []
    for mark in value:
        if not isinstance(mark, dict):
            raise ValueError("Invalid text mark.")
        identity = mark_id(mark.get("id"))
        if identity in ids or mark.get("style") not in ("highlight", "underline") or mark.get("color") not in COLORS:
            raise ValueError("This text mark has an invalid style, colour, or duplicate identity.")
        ids.add(identity)
        segments = mark.get("segments")
        if not isinstance(segments, list) or not 1 <= len(segments) <= 16:
            raise ValueError("Select a shorter passage, covering up to 16 text blocks.")
        anchors, blocks, size = [], set(), 0
        for segment in segments:
            if not isinstance(segment, dict) or not isinstance(segment.get("block"), str) or segment["block"] not in keys or segment["block"] in blocks:
                raise ValueError("This text mark does not belong to saved lesson content.")
            blocks.add(segment["block"])
            exact = text(segment.get("exact"), 12000)
            prefix, suffix = text(segment.get("prefix"), 32, True), text(segment.get("suffix"), 32, True)
            signature = text(segment.get("signature"), 40)
            if not re.fullmatch(r"[1-9][0-9]{0,6}:[0-9a-f]{8}", signature):
                raise ValueError("This text mark has an invalid text anchor.")
            length = int(signature.split(":", 1)[0])
            start, end = segment.get("start"), segment.get("end")
            units = len(exact.encode("utf-16-le")) // 2
            if type(start) is not int or type(end) is not int or not 0 <= start < end <= length <= 2000000 or end-start != units:
                raise ValueError("This text mark has an invalid text range.")
            size += units
            anchors.append(dict(block=segment["block"], start=start, end=end, exact=exact,
                                prefix=prefix, suffix=suffix, signature=signature))
        if size > 12000:
            raise ValueError("Select a passage shorter than 12,000 characters.")
        result.append(dict(id=identity, style=mark["style"], color=mark["color"], segments=anchors))
    if len(json.dumps(result, ensure_ascii=False).encode()) > MAX_BYTES:
        raise ValueError("This module has too many saved text marks. Remove a few before adding more.")
    return result


def update_marks(module, body):
    """Apply one idempotent operation while Store holds its update lock."""
    current = module.get("annotations", [])
    if body.get("operation") == "upsert":
        mark = validate_marks([body.get("annotation")], module)[0]
        updated = [mark if m["id"] == mark["id"] else m for m in current]
        if not any(m["id"] == mark["id"] for m in current):
            updated.append(mark)
    elif body.get("operation") == "delete":
        identity = mark_id(body.get("id"))
        updated = [m for m in current if m["id"] != identity]
    else:
        raise ValueError("Choose whether to save or remove this text mark.")
    return validate_marks(updated, module)
