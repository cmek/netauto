"""Inspect the EVPN circuits configured on a lab device (read-back).

Reconstructs each circuit from the device's running-config / get-config into the
netauto models and prints them — handy when debugging "what's actually on this
box / did my push land".

    uv run python scripts/inspect_evpn.py 172.20.30.4 arista
    uv run python scripts/inspect_evpn.py 172.20.30.6 ocnos
    uv run python scripts/inspect_evpn.py --all          # sweep the lab fabric
"""

import sys

from netauto.drivers import AristaDriver, OcnosDriver
from netauto.evpn import EvpnManager
from netauto.models import AzureEvpn

LAB = [
    ("172.20.30.4", "arista", "ar1"),
    ("172.20.30.5", "arista", "ar2"),
    ("172.20.30.6", "ocnos", "ipi1"),
    ("172.20.30.7", "ocnos", "ipi2"),
]


def connect(host: str, platform: str):
    if platform == "arista":
        driver = AristaDriver(host=host, user="admin", password="admin", enable_password="admin")
        driver.connect()
        return driver
    driver = OcnosDriver(host=host, user="admin", password="admin@123")
    driver.connect()
    return driver


def describe(circuit) -> str:
    e = circuit.evpn
    if isinstance(e, AzureEvpn):
        if e.role == "customer":
            svc = f"azure/customer s_tag={e.s_tag} c_tags={e.c_tags}"
        elif e.rewrite:
            tgt = f"->{e.internal_s_tag}" if e.internal_s_tag else " (pop)"
            svc = f"azure/cni rewrite s_tag={e.s_tag}{tgt}"
        else:
            svc = f"azure/cni s_tag={e.s_tag}"
    else:
        svc = f"evpn vlan={e.vlan.vlan_id}"
    rd = circuit.routing_instance.rd if circuit.routing_instance else "-"
    rt = circuit.routing_instance.rt_rd if circuit.routing_instance else "-"
    return (
        f"  vni={e.vni:<9} iface={str(circuit.interface):<12} "
        f"{e.description:<12} rd={rd:<15} rt={rt:<15} {svc}"
    )


def inspect(host: str, platform: str, name: str = "") -> None:
    driver = connect(host, platform)
    try:
        circuits = EvpnManager(driver).get_circuits()
        print(f"== {name or host} ({host}) — {len(circuits)} circuit(s)")
        for circuit in sorted(circuits, key=lambda c: c.evpn.vni):
            print(describe(circuit))
    finally:
        driver.disconnect()


def main() -> None:
    args = sys.argv[1:]
    if args and args[0] == "--all":
        for host, platform, name in LAB:
            try:
                inspect(host, platform, name)
            except Exception as exc:  # keep sweeping the rest of the fabric
                print(f"== {name} ({host}) ERROR: {exc}")
    else:
        host = args[0] if args else "172.20.30.4"
        platform = args[1] if len(args) > 1 else "arista"
        inspect(host, platform)


if __name__ == "__main__":
    main()
