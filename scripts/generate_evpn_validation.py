"""Generate example EVPN circuit configuration for every supported scenario.

This renders the per-device building blocks (``EvpnManager``) offline via
``MockDriver`` — no lab devices required — for the full matrix of
global-transport circuits:

  * ``p2p_vc``  (member A <-> member B): arista/arista, ocnos/ocnos, mixed
  * ``cloud_vc`` (customer <-> CNI):     CNI on both Arista and OcNOS
  * ``azure``    (Q-in-Q, customer <-> CNI): S-TAG + 1-3 C-TAGs, incl. rewrite

Each scenario is laid out as a complete circuit (both endpoints) with create and
delete config, so the network engineering team can review what we will push
before it ever touches live gear.

Note (non-Azure scope): the CNI side is byte-identical to the customer side, and
p2p customer_a == customer_b — per-endpoint rendering depends only on
service_type x vendor. The customer/CNI and A/B labels are presentational here;
they only diverge once Azure / QinQ lands.

Usage:
    python scripts/generate_evpn_validation.py        # writes validation_output/

``generate_all()`` returns {relative_path: content} so the same matrix can be
golden-file guarded in tests (see tests/test_evpn_validation_matrix.py).
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from netauto.drivers import MockDriver
from netauto.evpn import EvpnManager
from netauto.models import Asn, AzureEvpn, Evpn, Interface, RoutingInstance, Vlan

TERACO_ASN = 37195  # route-target prefix (non-Azure, from the reference templates)
AZURE_RT = 37186    # route-target prefix used by the Azure reference templates
OUTPUT_DIRNAME = "validation_output"

# Per-vendor presentation details.
VENDORS = {
    "arista_eos": {"label": "arista", "interface": "Ethernet6", "ext": "cfg", "syntax": "Arista EOS CLI"},
    "ipinfusion_ocnos": {"label": "ocnos", "interface": "eth4", "ext": "xml", "syntax": "OcNOS NETCONF edit-config payload"},
}


# Each scenario is a complete circuit: a service identity + two endpoints.
SCENARIOS = [
    # ---- p2p_vc (member <-> member) ----
    {
        "name": "p2p_vc__arista_to_arista",
        "service_type": "p2p_vc",
        "service_key": "SO101010",
        "vlan": 100,
        "vni": 5000,
        "endpoints": [
            {"role": "customer_a", "vendor": "arista_eos", "asn": 65001},
            {"role": "customer_b", "vendor": "arista_eos", "asn": 65002},
        ],
    },
    {
        "name": "p2p_vc__ocnos_to_ocnos",
        "service_type": "p2p_vc",
        "service_key": "SO101011",
        "vlan": 101,
        "vni": 5001,
        "endpoints": [
            {"role": "customer_a", "vendor": "ipinfusion_ocnos", "asn": 65001},
            {"role": "customer_b", "vendor": "ipinfusion_ocnos", "asn": 65002},
        ],
    },
    {
        "name": "p2p_vc__arista_to_ocnos",
        "service_type": "p2p_vc",
        "service_key": "SO101012",
        "vlan": 102,
        "vni": 5002,
        "endpoints": [
            {"role": "customer_a", "vendor": "arista_eos", "asn": 65001},
            {"role": "customer_b", "vendor": "ipinfusion_ocnos", "asn": 65002},
        ],
    },
    # ---- cloud_vc (customer <-> CNI), CNI on both vendors ----
    {
        "name": "cloud_vc__cust-arista_cni-arista",
        "service_type": "cloud_vc",
        "service_key": "SO202020",
        "vlan": 200,
        "vni": 6000,
        "endpoints": [
            {"role": "customer", "vendor": "arista_eos", "asn": 65001},
            {"role": "cni", "vendor": "arista_eos", "asn": 65010},
        ],
    },
    {
        "name": "cloud_vc__cust-arista_cni-ocnos",
        "service_type": "cloud_vc",
        "service_key": "SO202021",
        "vlan": 201,
        "vni": 6001,
        "endpoints": [
            {"role": "customer", "vendor": "arista_eos", "asn": 65001},
            {"role": "cni", "vendor": "ipinfusion_ocnos", "asn": 65010},
        ],
    },
    {
        "name": "cloud_vc__cust-ocnos_cni-arista",
        "service_type": "cloud_vc",
        "service_key": "SO202022",
        "vlan": 202,
        "vni": 6002,
        "endpoints": [
            {"role": "customer", "vendor": "ipinfusion_ocnos", "asn": 65001},
            {"role": "cni", "vendor": "arista_eos", "asn": 65010},
        ],
    },
    {
        "name": "cloud_vc__cust-ocnos_cni-ocnos",
        "service_type": "cloud_vc",
        "service_key": "SO202023",
        "vlan": 203,
        "vni": 6003,
        "endpoints": [
            {"role": "customer", "vendor": "ipinfusion_ocnos", "asn": 65001},
            {"role": "cni", "vendor": "ipinfusion_ocnos", "asn": 65010},
        ],
    },
]


# Azure ExpressRoute Q-in-Q scenarios. The customer port tunnels 1-3 inner
# C-TAGs into the outer S-TAG; the CNI port keys on the S-TAG. Dual-CNI is the
# orchestrator's job (one call + VNI per CNI) — each scenario shows one circuit
# (one VNI). The rewrite variants show S-TAG conflict resolution on the CNI.
AZURE_SCENARIOS = [
    {
        "name": "azure__cust-arista_cni-arista",
        "azure": True,
        "service_key": "SO303030",
        "s_tag": 700,
        "c_tags": [10, 20, 30],
        "vni": 7000,
        "endpoints": [
            {"role": "customer", "vendor": "arista_eos", "asn": 65001},
            {"role": "cni", "vendor": "arista_eos", "asn": 65010},
        ],
    },
    {
        "name": "azure__cust-ocnos_cni-ocnos",
        "azure": True,
        "service_key": "SO303031",
        "s_tag": 701,
        "c_tags": [11, 21],
        "vni": 7001,
        "endpoints": [
            {"role": "customer", "vendor": "ipinfusion_ocnos", "asn": 65001},
            {"role": "cni", "vendor": "ipinfusion_ocnos", "asn": 65010},
        ],
    },
    {
        "name": "azure__cust-arista_cni-ocnos",
        "azure": True,
        "service_key": "SO303032",
        "s_tag": 702,
        "c_tags": [12, 22, 32],
        "vni": 7002,
        "endpoints": [
            {"role": "customer", "vendor": "arista_eos", "asn": 65001},
            {"role": "cni", "vendor": "ipinfusion_ocnos", "asn": 65010},
        ],
    },
    {
        # S-TAG conflict on the Arista CNI: Azure S-TAG 703 translated to
        # internal S-TAG 2703.
        "name": "azure__rewrite_cni-arista",
        "azure": True,
        "service_key": "SO303033",
        "s_tag": 703,
        "c_tags": [13, 23],
        "vni": 7003,
        "endpoints": [
            {"role": "customer", "vendor": "arista_eos", "asn": 65001},
            {"role": "cni", "vendor": "arista_eos", "asn": 65010,
             "rewrite": True, "internal_s_tag": 2703},
        ],
    },
    {
        # S-TAG conflict on the OcNOS CNI: pop the Azure S-TAG, disable arp/nd.
        "name": "azure__rewrite_cni-ocnos",
        "azure": True,
        "service_key": "SO303034",
        "s_tag": 704,
        "c_tags": [14, 24],
        "vni": 7004,
        "endpoints": [
            {"role": "customer", "vendor": "ipinfusion_ocnos", "asn": 65001},
            {"role": "cni", "vendor": "ipinfusion_ocnos", "asn": 65010, "rewrite": True},
        ],
    },
]


def _endpoint_files(scenario: dict):
    """(endpoint, create_name, delete_name) per endpoint — single source of the
    filenames so generate_all() and the SUMMARY links never diverge."""
    rows = []
    for idx, ep in enumerate(scenario["endpoints"], start=1):
        v = VENDORS[ep["vendor"]]
        base = f"{idx}_{ep['role']}__{v['label']}"
        rows.append((ep, f"{base}.{v['ext']}", f"{base}.delete.{v['ext']}"))
    return rows


def _render_endpoint(scenario: dict, endpoint: dict) -> tuple[str, str]:
    """Return (create_config, delete_config) for one endpoint, via EvpnManager."""
    vendor = endpoint["vendor"]
    interface = VENDORS[vendor]["interface"]
    service_key = scenario["service_key"]
    num = service_key[2:]

    driver = MockDriver(
        platform=vendor,
        initial_interfaces=[Interface(name=interface)],
        initial_switchports=[Interface(name=interface, mode="trunk")],
    )
    mgr = EvpnManager(driver)

    evpn = Evpn(
        vlan=Vlan(vlan_id=scenario["vlan"], name=service_key),
        asn=endpoint["asn"],
        vni=scenario["vni"],
        description=service_key,
        service_type=scenario["service_type"],
    )
    ri = RoutingInstance(
        instance_name=service_key,
        instance_type="mac-vrf",
        rd=f"{endpoint['asn']}:{num}",  # RD is device-local
        rt_rd=f"{TERACO_ASN}:{num}",    # RT is shared across the circuit
    )

    create = mgr.create_circuit(
        interface, evpn, routing_instance=ri, asn=Asn(asn=endpoint["asn"]), dry_run=True
    )
    delete = mgr.delete_circuit(
        interface, evpn, routing_instance=ri, asn=Asn(asn=endpoint["asn"]),
        delete_vrf=True, dry_run=True,
    )
    return create, delete


def _render_azure_endpoint(scenario: dict, endpoint: dict) -> tuple[str, str]:
    """Return (create, delete) for one Azure Q-in-Q endpoint, via EvpnManager."""
    vendor = endpoint["vendor"]
    interface = VENDORS[vendor]["interface"]
    key = scenario["service_key"]
    num = key[2:]

    driver = MockDriver(
        platform=vendor,
        initial_interfaces=[Interface(name=interface)],
        initial_switchports=[Interface(name=interface, mode="trunk")],
    )
    mgr = EvpnManager(driver)

    fields = dict(
        description=key, asn=endpoint["asn"], vni=scenario["vni"],
        s_tag=scenario["s_tag"], role=endpoint["role"],
    )
    if endpoint["role"] == "customer":
        fields["c_tags"] = scenario["c_tags"]
    elif endpoint.get("rewrite"):
        fields["rewrite"] = True
        if endpoint.get("internal_s_tag") is not None:
            fields["internal_s_tag"] = endpoint["internal_s_tag"]
    azure = AzureEvpn(**fields)

    ri = RoutingInstance(
        instance_name=key, instance_type="mac-vrf",
        rd=f"{endpoint['asn']}:{num}", rt_rd=f"{AZURE_RT}:{num}",
    )
    create = mgr.create_azure_circuit(
        interface, azure, routing_instance=ri, asn=Asn(asn=endpoint["asn"]), dry_run=True
    )
    delete = mgr.delete_azure_circuit(
        interface, azure, routing_instance=ri, asn=Asn(asn=endpoint["asn"]),
        delete_vrf=True, dry_run=True,
    )
    return create, delete


def _scenario_readme(scenario: dict, files: List[str]) -> str:
    if scenario.get("azure"):
        return _azure_scenario_readme(scenario, files)
    st = scenario["service_type"]
    vni, vlan = scenario["vni"], scenario["vlan"]
    lines = [
        f"# {scenario['name']}",
        "",
        f"- Service type: **{st}**",
        f"- Service key: `{scenario['service_key']}`",
        f"- VLAN: `{vlan}`",
        f"- VNI: `{vni}`  (allocated externally, used verbatim for the VXLAN id"
        " and the mac-vrf / vlan-aware-bundle)",
        f"- Route-target prefix: `{TERACO_ASN}` (shared across both endpoints)",
        "",
        "## Endpoints",
        "",
    ]
    for ep in scenario["endpoints"]:
        v = VENDORS[ep["vendor"]]
        lines.append(
            f"- **{ep['role']}** — {v['label']} ({v['syntax']}), "
            f"interface `{v['interface']}`, local ASN `{ep['asn']}`, "
            f"RD `{ep['asn']}:{scenario['service_key'][2:]}`"
        )
    lines += ["", "## Files", ""]
    lines += [f"- `{f}`" for f in files]
    lines.append("")
    return "\n".join(lines)


def _azure_scenario_readme(scenario: dict, files: List[str]) -> str:
    lines = [
        f"# {scenario['name']}",
        "",
        "- Service type: **azure** (ExpressRoute Q-in-Q / 802.1ad)",
        f"- Service key: `{scenario['service_key']}`",
        f"- S-TAG (outer): `{scenario['s_tag']}`",
        f"- C-TAGs (inner, customer side): `{scenario['c_tags']}`",
        f"- VNI: `{scenario['vni']}`  (one circuit; dual-CNI uses one VNI per CNI)",
        f"- Route-target prefix: `{AZURE_RT}`",
        "",
        "The customer port tunnels each C-TAG into the S-TAG; the CNI port keys "
        "on the S-TAG (C-TAGs are encapsulated). Azure mandates dual CNI — the "
        "orchestrator repeats the CNI config on the secondary CNI with its own VNI.",
        "",
        "## Endpoints",
        "",
    ]
    for ep in scenario["endpoints"]:
        v = VENDORS[ep["vendor"]]
        extra = ""
        if ep["role"] == "cni" and ep.get("rewrite"):
            internal = ep.get("internal_s_tag")
            extra = (
                f" · **S-TAG rewrite** (Azure {scenario['s_tag']} → internal {internal})"
                if internal else " · **S-TAG rewrite** (pop + arp/nd-cache disable)"
            )
        lines.append(
            f"- **{ep['role']}** — {v['label']} ({v['syntax']}), "
            f"interface `{v['interface']}`, local ASN `{ep['asn']}`{extra}"
        )
    lines += ["", "## Files", ""]
    lines += [f"- `{f}`" for f in files]
    lines.append("")
    return "\n".join(lines)


def _summary(scenarios: List[dict], azure_scenarios: List[dict]) -> str:
    lines = [
        "# EVPN circuit validation matrix",
        "",
        "Example configuration for every supported EVPN circuit scenario, for",
        "review by network engineering before these building blocks are trusted",
        "against production gear. Generated offline by",
        "`scripts/generate_evpn_validation.py` (via MockDriver — no devices).",
        "",
        "Scope: **global transport** (EVPN/VXLAN across different devices) for",
        "`cloud_vc` (customer ↔ CNI), `p2p_vc` (member ↔ member), and **Azure**",
        "ExpressRoute Q-in-Q (S-TAG + 1-3 C-TAGs, incl. S-TAG rewrite). Same-device",
        "local switching is out of scope.",
        "",
        "## Lab environment",
        "",
        "The lab devices already carry the EVPN **underlay** (BGP, a VXLAN VTEP",
        "source, and the L2VPN-EVPN address-family). These building blocks add",
        "only the per-service circuit on top — they do not configure the underlay.",
        "",
        "| Device | Mgmt IP | Platform | Role | Notes |",
        "|--------|---------|----------|------|-------|",
        "| ar1 | 172.20.30.4 | Arista cEOS | leaf | BGP ASN 65001 · **live-validated** |",
        "| ar2 | 172.20.30.5 | Arista cEOS | leaf | BGP ASN 65002 |",
        "| ipi1 | 172.20.30.6 | IP Infusion OcNOS-SP | leaf | VTEP 10.0.0.6 · **live-validated** |",
        "| ipi2 | 172.20.30.7 | IP Infusion OcNOS-SP | leaf | |",
        "| spine1 / spine2 | 172.20.30.2 / .3 | Arista cEOS | spine | EVPN route reflectors |",
        "",
        "A full create → verify → delete cycle was run live on ar1 and ipi1 "
        "(see `tests/test_live_devices.py::TestLiveEvpn`).",
        "",
        "## How a circuit is built",
        "",
        "`EvpnManager` is a **per-device building block**: one call configures one",
        "endpoint interface on one device. The orchestrator (Prefect) calls it once",
        "per end of the circuit. `create_circuit` pushes two transactions:",
        "",
        "1. **Service VRF** — the `mac-vrf` / `vlan-aware-bundle` with RD + route-target.",
        "2. **Circuit** — the access sub-interface / switchport, the VLAN↔VNI VXLAN",
        "   mapping, and the EVPN access binding.",
        "",
        "`delete_circuit` reverses both. Arista output is EOS CLI; OcNOS output is",
        "a NETCONF `edit-config` payload. The **VNI** is allocated externally and",
        "used verbatim for the VXLAN id / vpn-id and the bundle name — never derived",
        "from the VLAN. cloud_vc and p2p_vc render identically given the same",
        f"vni/vlan; the route-target prefix is `{TERACO_ASN}` and is shared across",
        "both endpoints of a circuit.",
        "",
        "## Scenarios",
        "",
        "Each scenario is a complete circuit (both endpoints). Click a scenario for",
        "its README, or jump straight to a config below.",
        "",
        "| Scenario | Service | Endpoints | VLAN | VNI |",
        "|----------|---------|-----------|------|-----|",
    ]
    for s in scenarios:
        eps = " ↔ ".join(
            f"{ep['role']}/{VENDORS[ep['vendor']]['label']}" for ep in s["endpoints"]
        )
        link = f"[`{s['name']}`]({s['name']}/README.md)"
        lines.append(
            f"| {link} | {s['service_type']} | {eps} | {s['vlan']} | {s['vni']} |"
        )

    # ---- Azure Q-in-Q scenarios ----
    lines += [
        "",
        "## Azure ExpressRoute (Q-in-Q)",
        "",
        "The customer port wraps 1-3 inner C-TAGs into one outer S-TAG (Arista",
        "`dot1q-tunnel`; OcNOS `rewrite push`); the CNI port keys on the S-TAG. A",
        "rewrite scenario resolves an S-TAG conflict on the CNI (Arista translates",
        "to an internal S-TAG; OcNOS pops the S-TAG and disables arp/nd caching).",
        "Azure mandates dual CNI — the orchestrator repeats the CNI config per CNI",
        "with its own VNI; each scenario below shows one circuit (one VNI).",
        "",
        "Live validation: the Arista CNI-rewrite and both OcNOS paths (customer +",
        "CNI-rewrite) were run create→verify→delete on ar1/ipi1. The Arista "
        "**customer** Q-in-Q path uses `switchport ... dot1q-tunnel`, which the "
        "cEOSLab virtual platform does not support — it is valid on real EOS "
        "hardware but cannot be exercised on this lab.",
        "",
        "| Scenario | Endpoints | S-TAG | C-TAGs | VNI | Rewrite |",
        "|----------|-----------|-------|--------|-----|---------|",
    ]
    for s in azure_scenarios:
        eps = " ↔ ".join(
            f"{ep['role']}/{VENDORS[ep['vendor']]['label']}" for ep in s["endpoints"]
        )
        rw = next(
            (ep for ep in s["endpoints"] if ep.get("rewrite")), None
        )
        rewrite = "—"
        if rw:
            rewrite = (
                f"→ {rw['internal_s_tag']}" if rw.get("internal_s_tag") else "pop"
            )
        link = f"[`{s['name']}`]({s['name']}/README.md)"
        lines.append(
            f"| {link} | {eps} | {s['s_tag']} | {s['c_tags']} | {s['vni']} | {rewrite} |"
        )

    lines += ["", "## Generated configs", ""]
    for s in scenarios + azure_scenarios:
        folder = s["name"]
        lines.append(f"### [`{folder}`]({folder}/README.md)")
        for ep, create_name, delete_name in _endpoint_files(s):
            label = f"{ep['role']} ({VENDORS[ep['vendor']]['label']})"
            lines.append(
                f"- {label}: "
                f"[create]({folder}/{create_name}) · "
                f"[delete]({folder}/{delete_name})"
            )
        lines.append("")
    return "\n".join(lines)


def generate_all() -> Dict[str, str]:
    """Render the whole matrix. Returns {relative_path: file_content}."""
    out: Dict[str, str] = {}
    for scenario in SCENARIOS + AZURE_SCENARIOS:
        render = (
            _render_azure_endpoint if scenario.get("azure") else _render_endpoint
        )
        folder = scenario["name"]
        files: List[str] = []
        for ep, create_name, delete_name in _endpoint_files(scenario):
            create, delete = render(scenario, ep)
            out[f"{folder}/{create_name}"] = create + "\n"
            out[f"{folder}/{delete_name}"] = delete + "\n"
            files += [create_name, delete_name]
        out[f"{folder}/README.md"] = _scenario_readme(scenario, files)
    out["SUMMARY.md"] = _summary(SCENARIOS, AZURE_SCENARIOS)
    return out


def output_dir() -> Path:
    return Path(__file__).resolve().parent.parent / OUTPUT_DIRNAME


def main() -> None:
    root = output_dir()
    artifacts = generate_all()
    for rel_path, content in artifacts.items():
        dest = root / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content)
    print(f"Wrote {len(artifacts)} files to {root}")
    print(f"Review {root / 'SUMMARY.md'} and send {OUTPUT_DIRNAME}/ to network engineering.")


if __name__ == "__main__":
    main()
