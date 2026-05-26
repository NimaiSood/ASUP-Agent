"""Operational guardrails for mutating ONTAP actions."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field


@dataclass
class Guardrails:
    allow_mutations: bool = field(
        default_factory=lambda: os.environ.get("ONTAP_ALLOW_MUTATIONS", "false").lower() == "true"
    )
    _autosupport_last_invoke: dict[str, float] = field(default_factory=dict)
    autosupport_cooldown_sec: int = 3600

    def check_mutation(self, action: str) -> None:
        if not self.allow_mutations:
            raise PermissionError(
                f"Mutating action '{action}' blocked. Set ONTAP_ALLOW_MUTATIONS=true to enable."
            )

    def check_autosupport_invoke(self, node: str) -> None:
        self.check_mutation("invoke_autosupport")
        now = time.time()
        last = self._autosupport_last_invoke.get(node, 0)
        if now - last < self.autosupport_cooldown_sec:
            remaining = int(self.autosupport_cooldown_sec - (now - last))
            raise PermissionError(
                f"AutoSupport invoke for node '{node}' rate-limited. Retry in {remaining}s."
            )
        self._autosupport_last_invoke[node] = now
