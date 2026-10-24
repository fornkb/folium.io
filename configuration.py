"""Read local configuration without executing .env content or exposing credentials."""
from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path

from core import clean

API_KEY_FIELDS = ("api_key", "api_key_2", "api_key_3")
KEY_ENV_NAMES = tuple(("GEMINI_API_KEY" + suffix, "GOOGLE_API_KEY" + suffix)
                      for suffix in ("", "_2", "_3"))
CONFIG_KEYS = tuple(name for names in KEY_ENV_NAMES for name in names) + ("GEMINI_MODEL", "GEMINI_VISION_MODEL", "FOLIUM_PORT")


def environment_values():
    """Include persisted Windows variables added after the parent app started."""
    values = {key: os.environ.get(key, "").strip() for key in CONFIG_KEYS}
    if os.name == "nt":
        import winreg
        locations = ((winreg.HKEY_CURRENT_USER, "Environment"),
                     (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"))
        for hive, path in locations:
            try:
                with winreg.OpenKey(hive, path) as registry:
                    for key in CONFIG_KEYS:
                        if values[key]:
                            continue
                        try:
                            value, _ = winreg.QueryValueEx(registry, key)
                            if isinstance(value, str):
                                values[key] = value.strip()
                        except OSError:
                            pass
            except OSError:
                pass
    return {key:value for key,value in values.items() if value}


def dotenv_values(path):
    """Support KEY=value, optional export, quotes, and comments; no interpolation."""
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        return {}
    result = {}
    for line in text.splitlines():
        match = re.fullmatch(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*", line)
        if not match or match[1] not in CONFIG_KEYS:
            continue
        value = match[2]
        if value.startswith(('"', "'")):
            quoted = re.fullmatch(r"([\"'])(.*?)\1\s*(?:#.*)?", value)
            if not quoted:
                continue
            value = quoted[2]
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].strip()
        if value:
            result[match[1]] = value
    return result


def env_path(explicit=None):
    configured = explicit or os.environ.get("FOLIUM_ENV_FILE")
    return Path(configured).expanduser().resolve() if configured else Path(__file__).resolve().parent / ".env"


def configured_values(path):
    values = dotenv_values(path)
    sources = {key:"env_file" for key in values}
    inherited = environment_values()
    values.update(inherited)
    sources.update({key:"environment" for key in inherited})
    return values, sources


class Settings:
    def __init__(self, root, env_file=None):
        self.path = Path(root) / "settings.json"
        self.env_file = env_path(env_file)
        self.lock = threading.Lock()

    def _saved(self):
        try:
            value = json.loads(self.path.read_text("utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def get(self):
        with self.lock:
            value = self._saved()
        external, sources = configured_values(self.env_file)
        slots = []
        for slot, (field, env_names) in enumerate(zip(API_KEY_FIELDS, KEY_ENV_NAMES), 1):
            saved_key = str(value.get(field) or "").strip()
            # Resolve each slot independently; a blank entry keeps its environment fallback.
            key_name = next((name for name in env_names if external.get(name)), None)
            value[field] = saved_key or (external[key_name] if key_name else "")
            slots.append(dict(slot=slot, has_key=bool(value[field]),
                              key_source="settings" if saved_key else sources.get(key_name),
                              has_saved_key=bool(saved_key)))
        # Repeated credentials should not receive extra turns in the rotation.
        value["api_keys"] = list(dict.fromkeys(value[field] for field in API_KEY_FIELDS if value[field]))
        value["key_slots"] = slots
        value["key_source"] = slots[0]["key_source"]
        value["has_saved_key"] = slots[0]["has_saved_key"]
        value["model"] = value.get("model") or external.get("GEMINI_MODEL") or "gemini-3.8-flash"
        value["vision_model"] = value.get("vision_model") or external.get("GEMINI_VISION_MODEL") or value["model"]
        value.setdefault("interval", 6)
        return value

    def public(self):
        value = self.get()
        return dict(has_key=bool(value["api_keys"]), model=value["model"], vision_model=value["vision_model"], interval=value["interval"],
                    key_source=value["key_source"], has_saved_key=value["has_saved_key"],
                    key_count=len(value["api_keys"]), key_slots=value["key_slots"],
                    env_file_found=self.env_file.is_file())

    def save(self, body):
        effective = self.get()
        model = clean(body.get("model", effective["model"]), 100)
        if not re.fullmatch(r"gemini-[a-zA-Z0-9.\-]+", model):
            raise ValueError("Enter a valid Gemini model name.")
        vision_model = clean(body.get("vision_model", effective["vision_model"]),100)
        if not re.fullmatch(r"gemini-[a-zA-Z0-9.\-]+",vision_model):
            raise ValueError("Enter a valid Gemini visual model name.")
        interval = max(3, min(60, int(body.get("interval", effective["interval"]))))
        with self.lock:
            # Save only explicit settings. Never copy an external key into this file.
            saved = self._saved()
            for field in API_KEY_FIELDS:
                key = clean(body.get(field), 300)
                if key:
                    saved[field] = key
                if body.get(field.replace("api_key", "clear_key")):
                    saved.pop(field, None)
            saved["model"], saved["interval"] = model, interval
            if "vision_model" in body:
                saved["vision_model"] = vision_model
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(saved), "utf-8")
            tmp.replace(self.path)
        return self.public()
