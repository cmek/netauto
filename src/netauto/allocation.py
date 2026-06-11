"""Fabric-wide allocation of EVPN service identifiers (VNI, RD, RT).

A VNI must be **globally unique across the whole fabric** — it is the
network-wide service identifier in the EVPN control and data plane (see
docs/evpn_service.md). The per-device ``get_vnis()`` check in ``EvpnManager`` is
a *safety net*, not the allocator; this module is the source of truth.

Contents:
  * ``service_number`` / ``make_routing_instance`` — the RD/RT conventions,
    centralised (they were copy-pasted across scripts/examples).
  * ``find_conflicts`` — pure audit over read-back circuits (duplicate VNI / RT
    across *different* services), used by the Prefect ``audit_fabric`` flow.
  * ``VniRegistry`` ABC + ``JsonFileRegistry`` — allocate fabric-unique VNIs and
    track assignments. Pluggable so production swaps a DB-backed implementation.
"""

from __future__ import annotations

import json
import os
import threading
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Iterable, Optional

from .exceptions import RtCollision, VniInUse
from .models import RoutingInstance


# --------------------------------------------------------------------------- #
# Identifier conventions (single source of truth)
# --------------------------------------------------------------------------- #
def service_number(service_key: str) -> str:
    """The numeric part of a service key, e.g. ``SO123456`` -> ``123456``."""
    return service_key.removeprefix("SO")


def make_routing_instance(
    service_key: str,
    device_asn: int,
    rt_asn: int,
    instance_type: str = "mac-vrf",
) -> RoutingInstance:
    """Build the mac-vrf / vlan-aware-bundle for a service.

    RD is device-local (``<device_asn>:<num>``); RT is shared across both ends
    of the circuit (``<rt_asn>:<num>``) and is the customer-isolation key.
    """
    num = service_number(service_key)
    return RoutingInstance(
        instance_name=service_key,
        instance_type=instance_type,
        rd=f"{device_asn}:{num}",
        rt_rd=f"{rt_asn}:{num}",
    )


# --------------------------------------------------------------------------- #
# Fabric audit (pure; operates on read-back circuits)
# --------------------------------------------------------------------------- #
def find_conflicts(circuits: Iterable) -> dict:
    """Flag fabric-wide identifier hazards across read-back ``EvpnCircuit``s.

    The same VNI (or RT) seen on multiple endpoints is normal — that's the two
    ends of one circuit — *only if it is the same service*. The same VNI/RT used
    by **different** services (different service key) is a collision that breaks
    the one-VNI-one-service invariant (and customer isolation for RT).
    """
    by_vni: dict[int, set[str]] = {}
    by_rt: dict[str, set[str]] = {}
    for c in circuits:
        key = c.evpn.description
        by_vni.setdefault(c.evpn.vni, set()).add(key)
        if c.routing_instance is not None:
            by_rt.setdefault(c.routing_instance.rt_rd, set()).add(key)

    return {
        "vni_collisions": {
            vni: sorted(keys) for vni, keys in by_vni.items() if len(keys) > 1
        },
        "rt_collisions": {
            rt: sorted(keys) for rt, keys in by_rt.items() if len(keys) > 1
        },
    }


# --------------------------------------------------------------------------- #
# VNI registry
# --------------------------------------------------------------------------- #
class VniRegistry(ABC):
    """Allocates fabric-unique VNIs and tracks service -> (vni, rt) assignments."""

    @abstractmethod
    def allocate(self, service_key: str, rt: Optional[str] = None) -> int:
        """Return the VNI for ``service_key``, allocating a fresh fabric-unique
        one if needed. Idempotent: re-allocating an existing service returns its
        current VNI. Raises :class:`RtCollision` if ``rt`` is already bound to a
        different service."""

    @abstractmethod
    def release(self, service_key: str) -> None:
        """Free a service's VNI. No-op if not allocated."""

    @abstractmethod
    def get(self, service_key: str) -> Optional[int]:
        """The VNI assigned to ``service_key``, or ``None``."""

    @abstractmethod
    def assignments(self) -> dict[str, dict]:
        """``{service_key: {"vni": int, "rt": str | None}}`` snapshot."""

    def seed_from_circuits(self, circuits: Iterable) -> None:
        """Import live read-back circuits as assignments (audit/bootstrap).

        Raises :class:`VniInUse` if a VNI is already assigned to a *different*
        service — a real fabric collision worth surfacing loudly.
        """
        for c in circuits:
            self.record(
                c.evpn.description,
                c.evpn.vni,
                c.routing_instance.rt_rd if c.routing_instance else None,
            )

    @abstractmethod
    def record(self, service_key: str, vni: int, rt: Optional[str]) -> None:
        """Assert an existing assignment (used by seeding); detect collisions."""


class JsonFileRegistry(VniRegistry):
    """A simple JSON-file-backed registry — fabric-unique VNIs for one fabric.

    In-process safe via a lock + atomic replace. For concurrent *processes* a
    real lock (or a DB-backed ``VniRegistry``) is required; the JSON impl is the
    illustrative default.
    """

    def __init__(self, path: str | Path, base_vni: int = 10000):
        self.path = Path(path)
        self.base_vni = base_vni
        self._lock = threading.Lock()
        if not self.path.exists():
            self._write({})

    def _read(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text() or "{}")

    def _write(self, data: dict[str, dict]) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
        os.replace(tmp, self.path)  # atomic

    def allocate(self, service_key: str, rt: Optional[str] = None) -> int:
        with self._lock:
            data = self._read()
            if service_key in data:
                return data[service_key]["vni"]

            if rt is not None:
                clash = next(
                    (k for k, v in data.items() if v.get("rt") == rt), None
                )
                if clash is not None:
                    raise RtCollision(
                        f"route-target {rt} already assigned to {clash}"
                    )

            used = {v["vni"] for v in data.values()}
            vni = self.base_vni
            while vni in used:
                vni += 1

            data[service_key] = {"vni": vni, "rt": rt}
            self._write(data)
            return vni

    def release(self, service_key: str) -> None:
        with self._lock:
            data = self._read()
            if data.pop(service_key, None) is not None:
                self._write(data)

    def get(self, service_key: str) -> Optional[int]:
        entry = self._read().get(service_key)
        return entry["vni"] if entry else None

    def assignments(self) -> dict[str, dict]:
        return self._read()

    def record(self, service_key: str, vni: int, rt: Optional[str]) -> None:
        with self._lock:
            data = self._read()
            owner = next(
                (k for k, v in data.items() if v["vni"] == vni and k != service_key),
                None,
            )
            if owner is not None:
                raise VniInUse(
                    f"VNI {vni} already assigned to {owner}, cannot also assign "
                    f"to {service_key}"
                )
            existing = data.get(service_key)
            if existing and existing["vni"] != vni:
                raise VniInUse(
                    f"{service_key} already has VNI {existing['vni']}, "
                    f"cannot reassign to {vni}"
                )
            data[service_key] = {"vni": vni, "rt": rt}
            self._write(data)
