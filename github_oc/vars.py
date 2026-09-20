# {{$...}} token resolution. Rewrites {{$.a.b}} tokens in free-text inputs
# against the flow scope, so any string field can reference upstream data the
# same way. A per-call cache fetches each distinct path from the runtime only
# once, however many fields reference it. Ported from telegram-oc's vars.go.
from __future__ import annotations

import json
import re
from typing import Any

from inflow_plugin_sdk import Job

# {{ $.a.b }} — capture the JSON path inside the mustaches.
_VAR_RE = re.compile(r"\{\{\s*(\$[^}]+?)\s*\}\}")


class _Resolver:
    def __init__(self, job: Job):
        self._job = job
        self._cache: dict[str, str] = {}

    async def resolve(self, text: str) -> str:
        """Substitute every {{$...}} token in `text`. Tokens the scope can't
        supply are left verbatim so nothing is silently dropped."""
        if "{{" not in text:
            return text
        out: list[str] = []
        last = 0
        for m in _VAR_RE.finditer(text):
            out.append(text[last : m.start()])
            path = m.group(1).strip()
            if path not in self._cache:
                self._cache[path] = await self._fetch(path)
            out.append(self._cache[path])
            last = m.end()
        out.append(text[last:])
        return "".join(out)

    async def _fetch(self, json_path: str) -> str:
        """Read a JSON path from the flow context. A JSON string is unwrapped to
        its value; anything else is returned raw so it can be inlined."""
        raw = await self._job.cmd_get_scope(json_path)
        if not isinstance(raw, (bytes, bytearray)) or len(raw) == 0:
            return f"{{{{{json_path}}}}}"  # leave the token in place
        try:
            value = json.loads(raw.decode())
        except Exception:
            return raw.decode(errors="replace")
        if isinstance(value, str):
            return value
        if value is None:
            return f"{{{{{json_path}}}}}"
        return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


async def resolve_input_vars(job: Job, data: dict[str, Any]) -> None:
    """Walk the decoded action input and rewrite {{$...}} tokens in every string
    (and every string inside a list) in place. Plain fields never hit the
    runtime, so this is safe to run over every action's input uniformly."""
    if not isinstance(data, dict):
        return
    resolver = _Resolver(job)
    for key, value in list(data.items()):
        if isinstance(value, str):
            data[key] = await resolver.resolve(value)
        elif isinstance(value, list):
            data[key] = [
                await resolver.resolve(v) if isinstance(v, str) else v for v in value
            ]
