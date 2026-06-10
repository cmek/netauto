"""Live, self-cleaning EVPN circuit test for EvpnManager against a lab device.

Creates an EVPN circuit on a free port, verifies it landed in the running
config, then deletes it (and restores the port). Prints each phase.

    ARISTA: uv run python scripts/live_evpn_test.py arista
    OCNOS:  uv run python scripts/live_evpn_test.py ocnos

Safe to re-run; it cleans up after itself in a finally block.
"""

import sys

from netauto.drivers import AristaDriver, OcnosDriver
from netauto.evpn import EvpnManager
from netauto.models import Asn, AzureEvpn, Evpn, Interface, RoutingInstance, Vlan

TERACO_ASN = 37195
AZURE_RT = 37186


def pick_unused(config_text: str, candidates, token_fmt):
    for value in candidates:
        if token_fmt(value) not in config_text:
            return value
    raise RuntimeError(f"no unused value among {candidates}")


def run_arista():
    host = "172.20.30.4"  # ar1
    interface = "Ethernet6"
    driver = AristaDriver(host=host, user="admin", password="admin", enable_password="admin")
    driver.connect()

    cfg = driver.get_config()
    asn = 65001  # ar1's BGP ASN (confirmed on device)
    vlan = pick_unused(cfg, range(3700, 3999), lambda v: f"vlan {v} ")
    vni = pick_unused(cfg, range(39900, 39999), lambda v: f"vni {v}")
    service_key = f"SO9{vni}"

    print(f"== ar1 ({host}) — circuit on {interface}: vlan={vlan} vni={vni} key={service_key}")

    evpn = Evpn(
        vlan=Vlan(vlan_id=vlan, name=service_key),
        asn=asn,
        vni=vni,
        description=service_key,
        service_type="cloud_vc",
    )
    ri = RoutingInstance(
        instance_name=service_key,
        instance_type="mac-vrf",
        rd=f"{asn}:{vni}",
        rt_rd=f"{TERACO_ASN}:{vni}",
    )
    mgr = EvpnManager(driver)

    try:
        print("\n-- CREATE --")
        print(mgr.create_circuit(interface, evpn, routing_instance=ri))

        after = driver.get_config()
        checks = {
            f"vxlan vlan {vlan} vni {vni}": f"vxlan vlan {vlan} vni {vni}" in after,
            f"vlan-aware-bundle {service_key}": f"vlan-aware-bundle {service_key}" in after,
            f"vlan {vlan} on {interface}": f"switchport trunk allowed vlan add {vlan}" in after
            or f"allowed vlan {vlan}" in after,
            f"rd {asn}:{vni}": f"rd {asn}:{vni}" in after,
        }
        print("\n-- VERIFY (running-config) --")
        for label, ok in checks.items():
            print(f"  [{'OK' if ok else 'MISSING'}] {label}")
    finally:
        print("\n-- DELETE (cleanup) --")
        print(mgr.delete_circuit(interface, evpn, routing_instance=ri, delete_vrf=True))
        # restore the free test port to a clean default
        driver.push_config([f"default interface {interface}"])

        final = driver.get_config()
        gone = (
            f"vni {vni}" not in final
            and f"vlan-aware-bundle {service_key}" not in final
        )
        print(f"\n-- POST-CLEANUP: circuit fully removed: {gone}")

    driver.disconnect()


def run_ocnos():
    host = "172.20.30.6"  # ipi1
    interface = "eth4"
    driver = OcnosDriver(host=host, user="admin", password="admin@123")
    driver.connect()

    asn = 65003
    vlan, vni = 3801, 39801
    service_key = f"SO9{vni}"
    print(f"== ipi1 ({host}) — circuit on {interface}: vlan={vlan} vni={vni} key={service_key}")

    evpn = Evpn(
        vlan=Vlan(vlan_id=vlan, name=service_key),
        asn=asn,
        vni=vni,
        description=service_key,
        service_type="cloud_vc",
    )
    ri = RoutingInstance(
        instance_name=service_key,
        instance_type="mac-vrf",
        rd=f"{asn}:{vni}",
        rt_rd=f"{TERACO_ASN}:{vni}",
    )
    mgr = EvpnManager(driver)

    try:
        print("\n-- CREATE --")
        print(mgr.create_circuit(interface, evpn, routing_instance=ri))
        after = driver.get_config()
        print("\n-- VERIFY (running-config) --")
        for token in (service_key, str(vni), f"{interface}.{vlan}"):
            print(f"  [{'OK' if token in after else 'MISSING'}] {token}")
    finally:
        print("\n-- DELETE (cleanup) --")
        print(mgr.delete_circuit(interface, evpn, routing_instance=ri, delete_vrf=True))
        final = driver.get_config()
        print(f"\n-- POST-CLEANUP: instance removed: {service_key not in final}")

    driver.disconnect()


def _azure_ri(key, asn):
    return RoutingInstance(
        instance_name=key, instance_type="mac-vrf",
        rd=f"{asn}:{key[2:]}", rt_rd=f"{AZURE_RT}:{key[2:]}",
    )


def _cycle_azure(driver, mgr, interface, azure, checks, restore=None):
    print(f"\n== Azure {azure.role}"
          f"{' (rewrite)' if azure.rewrite else ''} on {interface}: "
          f"s_tag={azure.s_tag} c_tags={azure.c_tags} vni={azure.vni}")
    created = False
    try:
        print("-- CREATE --")
        mgr.create_azure_circuit(interface, azure, routing_instance=_azure_ri(azure.description, azure.asn))
        created = True
        after = driver.get_config()
        for label, token in checks.items():
            print(f"  [{'OK' if token in after else 'MISSING'}] {label}")
    except Exception as e:
        msg = str(e).splitlines()[0]
        print(f"  [UNSUPPORTED/ERROR] {msg}")
    finally:
        print("-- DELETE (cleanup) --")
        try:
            mgr.delete_azure_circuit(interface, azure, routing_instance=_azure_ri(azure.description, azure.asn), delete_vrf=True)
        except Exception as e:
            print(f"  delete note: {str(e).splitlines()[0]}")
        if restore:
            driver.push_config(restore)
        final = driver.get_config()
        print(f"  removed: {azure.description not in final and str(azure.vni) not in final}")


def run_arista_azure():
    host, interface, asn = "172.20.30.4", "Ethernet6", 65001
    driver = AristaDriver(host=host, user="admin", password="admin", enable_password="admin")
    driver.connect()
    cfg = driver.get_config()
    s_tag = pick_unused(cfg, range(3700, 3799), lambda v: f"vlan {v} ")
    vni = pick_unused(cfg, range(39700, 39799), lambda v: f"vni {v}")
    internal = pick_unused(cfg, range(3800, 3899), lambda v: f"vlan {v} ")
    print(f"== ar1 ({host}) Azure tests on {interface}")

    # customer: 3 C-TAGs tunneled into the S-TAG
    cust = AzureEvpn(description=f"SO{vni}", asn=asn, vni=vni, s_tag=s_tag,
                     role="customer", c_tags=[11, 21, 31])
    _cycle_azure(driver, EvpnManager(driver), interface, cust, {
        f"dot1q-tunnel 11->{s_tag}": f"switchport vlan translation 11 dot1q-tunnel {s_tag}",
        f"vxlan vlan {s_tag}": f"vxlan vlan {s_tag} vni {vni}",
    }, restore=[f"default interface {interface}"])

    # cni rewrite: Azure S-TAG translated to an internal S-TAG
    cni = AzureEvpn(description=f"SO{vni}", asn=asn, vni=vni, s_tag=s_tag,
                    role="cni", rewrite=True, internal_s_tag=internal)
    _cycle_azure(driver, EvpnManager(driver), interface, cni, {
        f"translation {s_tag}->{internal}": f"switchport vlan translation {s_tag} {internal}",
        f"vxlan vlan {internal}": f"vxlan vlan {internal} vni {vni}",
    }, restore=[f"default interface {interface}"])
    driver.disconnect()


def run_ocnos_azure():
    host, interface, asn = "172.20.30.6", "eth4", 65003
    driver = OcnosDriver(host=host, user="admin", password="admin@123")
    driver.connect()
    existing = set(driver.get_vnis())
    vni = next(v for v in range(39700, 39799) if v not in existing)
    s_tag = 3750
    print(f"== ipi1 ({host}) Azure tests on {interface}")

    cust = AzureEvpn(description=f"SO{vni}", asn=asn, vni=vni, s_tag=s_tag,
                     role="customer", c_tags=[12, 22])
    _cycle_azure(driver, EvpnManager(driver), interface, cust, {
        f"sub-if {interface}.12": f"{interface}.12",
        "push s_tag": str(s_tag),
    })

    cni = AzureEvpn(description=f"SO{vni}", asn=asn, vni=vni, s_tag=s_tag,
                    role="cni", rewrite=True)
    _cycle_azure(driver, EvpnManager(driver), interface, cni, {
        f"sub-if {interface}.{s_tag}": f"{interface}.{s_tag}",
        "arp-cache disable": "arp-cache",
    })
    driver.disconnect()


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "arista"
    {
        "arista": run_arista,
        "ocnos": run_ocnos,
        "arista-azure": run_arista_azure,
        "ocnos-azure": run_ocnos_azure,
    }[target]()
