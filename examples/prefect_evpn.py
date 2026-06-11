"""Illustrative Prefect integration for EVPN circuit provisioning.

A *sketch* showing how the netauto EVPN building blocks (`EvpnManager`) are wired
into Prefect to provision a full circuit **across devices**. The library
configures one endpoint on one device per call; this flow is the orchestrator
that ties the ends together — exactly the split described in
`docs/evpn_service.md` (the library is per-device; Prefect owns the rest):

  * **VNI allocation** — read the VNIs currently in use on the target devices
    (`driver.get_vnis()`) and pick a free one. (A real deployment would track
    allocations in a database with locking; this scan is illustrative.)
  * **Per-endpoint provisioning** — one task per end, run concurrently.
  * **Azure dual CNI** — Azure mandates a primary + secondary CNI; the flow
    provisions each CNI as its own circuit with its own VNI.

It is not exercised by the test suite, and Prefect need not be installed to read
it — it documents the intended shape of the integration. Always run with
`dry_run=True` first to review the diff, then flip to commit.

Run (once Prefect is installed and configured):
    uv run python examples/prefect_evpn.py
"""

from __future__ import annotations

from prefect import flow, task, get_run_logger
from prefect.blocks.system import Secret

import os
from collections import defaultdict

from netauto.allocation import JsonFileRegistry, make_routing_instance
from netauto.drivers import AristaDriver, OcnosDriver
from netauto.drivers.base import DeviceDriver
from netauto.evpn import EvpnManager, plan_reconcile
from netauto.models import AzureEvpn, Evpn, EvpnCircuit, RoutingInstance, Vlan

# Route-target prefixes from the reference templates (see docs/evpn_service.md).
STANDARD_RT = 37195
AZURE_RT = 37186

# An endpoint is a plain (JSON-serializable) dict so it travels cleanly as a
# Prefect flow/task parameter:
#   {"platform": "arista_eos" | "ipinfusion_ocnos",
#    "host": "172.20.30.4", "interface": "Ethernet6", "asn": 65001,
#    # CNI-only, optional, for Azure S-TAG rewrite:
#    "rewrite": True, "internal_s_tag": 2500}
Endpoint = dict


# --------------------------------------------------------------------------- #
# Connection (helper, not a task: drivers hold live sockets and shouldn't be
# passed between tasks — each task opens and closes its own connection).
# --------------------------------------------------------------------------- #
def _connect(platform: str, host: str) -> DeviceDriver:
    """Open a connected driver. Credentials come from Prefect Secret blocks
    (`Secret(value=...).save("device-password")`), keeping them out of code."""
    if platform == "arista_eos":
        driver = AristaDriver(
            host=host, user="admin", password=Secret.load("device-password").get()
        )
        driver.connect()  # eAPI / HTTP
        return driver
    if platform == "ipinfusion_ocnos":
        # OcNOS connects over NETCONF in its constructor.
        return OcnosDriver(
            host=host, user="admin", password=Secret.load("ocnos-password").get()
        )
    raise ValueError(f"Unsupported platform: {platform}")


# The fabric-wide VNI registry is the source of truth for allocation: a VNI
# must be globally unique across all 20+ switches, so it cannot be picked by
# scanning only a circuit's two endpoints. The JSON-file registry is the
# illustrative default; production swaps a DB-backed VniRegistry. (The per-device
# get_vnis() check inside EvpnManager stays as a safety net against drift.)
REGISTRY = JsonFileRegistry(os.getenv("VNI_REGISTRY", "vni_registry.json"))


def _routing_instance(service_key: str, asn: int, rt_prefix: int) -> RoutingInstance:
    """The mac-vrf / vlan-aware-bundle: RD is device-local, RT is shared."""
    return make_routing_instance(service_key, device_asn=asn, rt_asn=rt_prefix)


@task
def allocate_vni(service_key: str, rt: str) -> int:
    """Reserve a fabric-unique VNI for the service (idempotent)."""
    return REGISTRY.allocate(service_key, rt=rt)


# --------------------------------------------------------------------------- #
# Per-endpoint building-block tasks (one device each)
# --------------------------------------------------------------------------- #
@task
def provision_endpoint(
    endpoint: Endpoint,
    service_key: str,
    vlan: int,
    vni: int,
    service_type: str = "p2p_vc",
    dry_run: bool = False,
) -> str:
    """Provision one (non-Azure) circuit endpoint; returns the config diff."""
    logger = get_run_logger()
    driver = _connect(endpoint["platform"], endpoint["host"])
    try:
        evpn = Evpn(
            vlan=Vlan(vlan_id=vlan, name=service_key),
            asn=endpoint["asn"],
            vni=vni,
            description=service_key,
            service_type=service_type,
        )
        diff = EvpnManager(driver).create_circuit(
            endpoint["interface"],
            evpn,
            routing_instance=_routing_instance(service_key, endpoint["asn"], STANDARD_RT),
            dry_run=dry_run,
        )
        logger.info("provisioned %s on %s (dry_run=%s)\n%s",
                    service_key, endpoint["host"], dry_run, diff)
        return diff
    finally:
        driver.disconnect()


@task
def deprovision_endpoint(
    endpoint: Endpoint,
    service_key: str,
    vlan: int,
    vni: int,
    service_type: str = "p2p_vc",
    delete_vrf: bool = True,
    dry_run: bool = False,
) -> str:
    """Tear one circuit endpoint down; returns the config diff."""
    driver = _connect(endpoint["platform"], endpoint["host"])
    try:
        evpn = Evpn(
            vlan=Vlan(vlan_id=vlan, name=service_key),
            asn=endpoint["asn"],
            vni=vni,
            description=service_key,
            service_type=service_type,
        )
        return EvpnManager(driver).delete_circuit(
            endpoint["interface"],
            evpn,
            routing_instance=_routing_instance(service_key, endpoint["asn"], STANDARD_RT),
            delete_vrf=delete_vrf,
            dry_run=dry_run,
        )
    finally:
        driver.disconnect()


@task
def provision_azure_endpoint(
    endpoint: Endpoint,
    service_key: str,
    s_tag: int,
    vni: int,
    role: str,
    c_tags: list[int] | None = None,
    dry_run: bool = False,
) -> str:
    """Provision one Azure Q-in-Q endpoint (customer or CNI)."""
    fields = dict(
        description=service_key, asn=endpoint["asn"], vni=vni, s_tag=s_tag, role=role
    )
    if role == "customer":
        fields["c_tags"] = c_tags or []
    elif endpoint.get("rewrite"):  # CNI S-TAG conflict resolution
        fields["rewrite"] = True
        if endpoint.get("internal_s_tag") is not None:
            fields["internal_s_tag"] = endpoint["internal_s_tag"]

    driver = _connect(endpoint["platform"], endpoint["host"])
    try:
        return EvpnManager(driver).create_azure_circuit(
            endpoint["interface"],
            AzureEvpn(**fields),
            routing_instance=_routing_instance(service_key, endpoint["asn"], AZURE_RT),
            dry_run=dry_run,
        )
    finally:
        driver.disconnect()


# --------------------------------------------------------------------------- #
# Flows
# --------------------------------------------------------------------------- #
@flow(name="provision-evpn-circuit")
def provision_evpn_circuit(
    service_key: str,
    vlan: int,
    endpoints: list[Endpoint],
    service_type: str = "p2p_vc",
    vni: int | None = None,
    dry_run: bool = False,
) -> dict[str, str]:
    """Provision a global-transport circuit across its endpoints (p2p_vc/cloud_vc).

    When ``vni`` is not supplied, reserve a fabric-unique one from the registry.
    Endpoints are provisioned concurrently.
    """
    logger = get_run_logger()
    if vni is None:
        vni = allocate_vni(service_key, rt=f"{STANDARD_RT}:{service_key[2:]}")
        logger.info("registry allocated VNI %s for %s", vni, service_key)

    futures = [
        provision_endpoint.submit(ep, service_key, vlan, vni, service_type, dry_run)
        for ep in endpoints
    ]
    return {ep["host"]: f.result() for ep, f in zip(endpoints, futures)}


@flow(name="decommission-evpn-circuit")
def decommission_evpn_circuit(
    service_key: str,
    vlan: int,
    vni: int,
    endpoints: list[Endpoint],
    service_type: str = "p2p_vc",
    dry_run: bool = False,
) -> dict[str, str]:
    """Tear a circuit down on every endpoint."""
    futures = [
        deprovision_endpoint.submit(
            ep, service_key, vlan, vni, service_type, dry_run=dry_run
        )
        for ep in endpoints
    ]
    return {ep["host"]: f.result() for ep, f in zip(endpoints, futures)}


@task(retries=2, retry_delay_seconds=10)
def read_circuits(platform: str, host: str) -> list[dict]:
    """Read a device's EVPN circuits back into plain dicts (JSON-serializable)."""
    driver = _connect(platform, host)
    try:
        rows = []
        for c in EvpnManager(driver).get_circuits():
            rows.append({
                "host": host,
                "vni": c.evpn.vni,
                "interface": c.interface,
                "description": c.evpn.description,
                "rt": c.routing_instance.rt_rd if c.routing_instance else None,
            })
        return rows
    finally:
        driver.disconnect()


@flow(name="audit-fabric-evpn")
def audit_fabric(devices: list[Endpoint]) -> dict:
    """Read every device's circuits and flag fabric-wide hazards.

    This is the concrete follow-through on the global-VNI-uniqueness rule: a VNI
    must identify exactly one service across the whole fabric. Seeing the same
    VNI on two devices is normal — that's the two ends of one circuit — *as long
    as they share the same route-target*. The same VNI with **different** RTs is
    a collision (two unrelated services reusing a VNI), which read-back catches.

    devices: ``[{"platform": ..., "host": ...}, ...]``
    """
    logger = get_run_logger()
    circuits: list[dict] = []
    for dev in devices:
        circuits.extend(read_circuits(dev["platform"], dev["host"]))

    # Same collision logic as netauto.allocation.find_conflicts (a VNI/RT used by
    # >1 distinct service key), computed here on the serializable dict rows.
    by_vni: dict[int, set] = defaultdict(set)
    by_rt: dict[str, set] = defaultdict(set)
    by_vni_ends: dict[int, list] = defaultdict(list)
    for c in circuits:
        by_vni[c["vni"]].add(c["description"])
        by_vni_ends[c["vni"]].append(c)
        if c["rt"]:
            by_rt[c["rt"]].add(c["description"])

    vni_collisions = {v: sorted(s) for v, s in by_vni.items() if len(s) > 1}
    rt_collisions = {r: sorted(s) for r, s in by_rt.items() if len(s) > 1}
    # one end only: half-deleted, or the far end is a cloud CNI / outside the sweep.
    single_ended = {v: ends for v, ends in by_vni_ends.items() if len(ends) == 1}

    if vni_collisions or rt_collisions:
        logger.error("fabric collisions — vni: %s  rt: %s", vni_collisions, rt_collisions)
    logger.info("audited %d circuits across %d devices; %d single-ended",
                len(circuits), len(devices), len(single_ended))
    return {
        "circuits": circuits,
        "vni_collisions": vni_collisions,
        "rt_collisions": rt_collisions,
        "single_ended": single_ended,
    }


@task
def reconcile_device(platform: str, host: str, intended_specs: list[dict]) -> dict:
    """Diff a device's live circuits against the intended inventory (report-only).

    intended_specs: ``[{interface, service_key, vlan, vni, asn, rt_prefix}, ...]``
    """
    driver = _connect(platform, host)
    try:
        actual = EvpnManager(driver).get_circuits()
        intended = [
            EvpnCircuit(
                evpn=Evpn(
                    vlan=Vlan(vlan_id=s["vlan"], name=s["service_key"]),
                    asn=s["asn"], vni=s["vni"], description=s["service_key"],
                ),
                routing_instance=make_routing_instance(
                    s["service_key"], s["asn"], s["rt_prefix"]
                ),
                interface=s["interface"],
            )
            for s in intended_specs
        ]
        return plan_reconcile(intended, actual).model_dump()
    finally:
        driver.disconnect()


@flow(name="reconcile-fabric-evpn")
def reconcile_fabric(devices_with_intent: list[dict]) -> dict:
    """Report drift of each device vs its intended inventory (declarative audit).

    devices_with_intent: ``[{platform, host, intended: [spec, ...]}, ...]``.
    Report-only — feed the plan's to_create/to_update into ensure_circuit to apply.
    """
    logger = get_run_logger()
    plans: dict[str, dict] = {}
    for dev in devices_with_intent:
        plan = reconcile_device(dev["platform"], dev["host"], dev["intended"])
        plans[dev["host"]] = plan
        logger.info(
            "reconcile %s — create=%s update=%s delete=%s in_sync=%s",
            dev["host"], plan["to_create"], list(plan["to_update"]),
            plan["to_delete"], plan["in_sync"],
        )
    return plans


@flow(name="provision-azure-circuit")
def provision_azure_circuit(
    service_key: str,
    s_tag: int,
    c_tags: list[int],
    customer: Endpoint,
    cni_primary: Endpoint,
    cni_secondary: Endpoint,
    dry_run: bool = False,
) -> dict[str, str]:
    """Provision an Azure ExpressRoute Q-in-Q circuit with mandatory dual CNI.

    Each CNI is its own circuit with its own VNI (S-TAG shared across both). The
    CNI vendor pair must match; the customer vendor is independent.
    """
    logger = get_run_logger()
    num = service_key[2:]
    # Two circuits => two registry entries => two fabric-unique VNIs.
    vni_primary = allocate_vni(f"{service_key}-primary", rt=f"{AZURE_RT}:{num}-P")
    vni_secondary = allocate_vni(f"{service_key}-secondary", rt=f"{AZURE_RT}:{num}-S")
    logger.info("Azure VNIs: primary=%s secondary=%s", vni_primary, vni_secondary)

    results: dict[str, str] = {}
    # Primary circuit: customer (1-3 C-TAGs) <-> primary CNI.
    results["customer"] = provision_azure_endpoint(
        customer, service_key, s_tag, vni_primary, role="customer",
        c_tags=c_tags, dry_run=dry_run,
    )
    results["cni_primary"] = provision_azure_endpoint(
        cni_primary, service_key, s_tag, vni_primary, role="cni", dry_run=dry_run,
    )
    # Secondary circuit on the second CNI (its own VNI; same S-TAG).
    results["cni_secondary"] = provision_azure_endpoint(
        cni_secondary, service_key, s_tag, vni_secondary, role="cni", dry_run=dry_run,
    )
    # NOTE: when C-TAGs are split across the two circuits, the customer port is
    # also provisioned for the secondary circuit (vni_secondary) with its subset
    # of C-TAGs — omitted here to keep the sketch focused.
    return results


if __name__ == "__main__":
    # p2p_vc across an Arista leaf and an OcNOS leaf; VNI auto-allocated by
    # scanning both devices. dry_run=True previews the diff without committing.
    provision_evpn_circuit(
        service_key="SO123456",
        vlan=1234,
        endpoints=[
            {"platform": "arista_eos", "host": "172.20.30.4", "interface": "Ethernet6", "asn": 65001},
            {"platform": "ipinfusion_ocnos", "host": "172.20.30.6", "interface": "eth4", "asn": 65003},
        ],
        service_type="p2p_vc",
        dry_run=True,
    )

    # Azure Q-in-Q: OcNOS customer + dual Arista CNI (primary needs an S-TAG
    # rewrite — Azure's S-TAG 500 conflicts on that device, translated to 2500).
    provision_azure_circuit(
        service_key="SO654321",
        s_tag=500,
        c_tags=[10, 20, 30],
        customer={"platform": "ipinfusion_ocnos", "host": "172.20.30.7", "interface": "eth4", "asn": 65004},
        cni_primary={"platform": "arista_eos", "host": "172.20.30.4", "interface": "Ethernet6", "asn": 65001, "rewrite": True, "internal_s_tag": 2500},
        cni_secondary={"platform": "arista_eos", "host": "172.20.30.5", "interface": "Ethernet6", "asn": 65002},
        dry_run=True,
    )
