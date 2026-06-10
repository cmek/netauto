"""Create an EVPN circuit endpoint with the EvpnManager building block.

Runnable offline against MockDriver (no lab device needed):

    python examples/evpn_circuit.py

EvpnManager configures ONE endpoint on ONE device per call. The orchestrator
(Prefect) calls it once per end of the circuit. Swap MockDriver for AristaDriver
/ OcnosDriver (see lab_devices.md) to push to real gear.
"""

from netauto.drivers import MockDriver
from netauto.evpn import EvpnManager
from netauto.models import Evpn, Interface, RoutingInstance, Vlan


def provision(driver, interface, service_key, vlan_id, vni, asn, service_type):
    evpn = Evpn(
        vlan=Vlan(vlan_id=vlan_id, name=service_key),
        asn=asn,
        vni=vni,
        description=service_key,
        service_type=service_type,
    )
    ri = RoutingInstance(
        instance_name=service_key,  # must match evpn.description
        instance_type="mac-vrf",
        rd=f"{asn}:{service_key[2:]}",
        rt_rd=f"37195:{service_key[2:]}",
    )
    mgr = EvpnManager(driver)
    return mgr.create_circuit(interface, evpn, routing_instance=ri, dry_run=True)


def main():
    # cloud_vc on an Arista endpoint. The VNI (5000) is allocated externally and
    # used verbatim — it is not derived from the VLAN.
    arista = MockDriver(
        platform="arista_eos",
        initial_interfaces=[Interface(name="Ethernet6")],
        initial_switchports=[Interface(name="Ethernet6", mode="trunk")],
    )
    print("## cloud_vc on Arista (vni 5000, passed in whole)")
    print(provision(arista, "Ethernet6", "SO555", 100, 5000, 65001, "cloud_vc"))

    # p2p_vc on an OcNOS endpoint (NETCONF payload).
    ocnos = MockDriver(
        platform="ipinfusion_ocnos",
        initial_interfaces=[Interface(name="eth4")],
        initial_switchports=[Interface(name="eth4", mode="trunk")],
    )
    print("\n## p2p_vc on OcNOS (vni 5001, passed in whole)")
    print(provision(ocnos, "eth4", "SO777", 101, 5001, 65002, "p2p_vc"))


if __name__ == "__main__":
    main()
