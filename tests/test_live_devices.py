import pytest
import os
from netauto.drivers import AristaDriver, OcnosDriver
from netauto.evpn import EvpnManager
from netauto.logic import LagManager
from netauto.models import Asn, Evpn, Interface, RoutingInstance, Vlan

# Skip tests unless explicitly enabled
RUN_LIVE_TESTS = os.getenv("RUN_LIVE_TESTS") == "1"
ARISTA_HOST = os.getenv("ARISTA_HOST", "172.20.30.4")
OCNOS_HOST = os.getenv("OCNOS_HOST", "172.20.30.6")
USERNAME = os.getenv("DEVICE_USER", "admin")
PASSWORD = os.getenv("DEVICE_PASSWORD", "admin")
# OcNOS uses a different default password than Arista (see lab_devices.md)
OCNOS_PASSWORD = os.getenv("OCNOS_PASSWORD", "admin@123")

# ar1's BGP ASN (must match the device for the router-bgp config to land).
ARISTA_ASN = int(os.getenv("ARISTA_ASN", "65001"))
TERACO_ASN = 37195

# Free ports to bundle/unbundle during the live LAG cycle. Override via env if
# these aren't safe on your devices. The test creates then deletes the LAG, so
# it is self-cleaning.
ARISTA_LAG_NAME = os.getenv("ARISTA_LAG_NAME", "Port-Channel99")
OCNOS_LAG_NAME = os.getenv("OCNOS_LAG_NAME", "po99")
ARISTA_LAG_MEMBERS = os.getenv("ARISTA_LAG_MEMBERS", "Ethernet5,Ethernet6").split(",")
OCNOS_LAG_MEMBERS = os.getenv("OCNOS_LAG_MEMBERS", "eth3,eth4").split(",")


def _interface_names(interfaces) -> set[str]:
    """get_interfaces() returns a list (real drivers) or dict (mock)."""
    if isinstance(interfaces, dict):
        return set(interfaces.keys())
    return {intf.name for intf in interfaces}


@pytest.mark.skipif(not RUN_LIVE_TESTS, reason="Live tests not enabled")
class TestLiveDevices:
    def test_arista_connection(self):
        """Test connection to Arista device."""
        driver = AristaDriver(host=ARISTA_HOST, user=USERNAME, password=PASSWORD)
        driver.connect()
        assert driver.platform == "arista_eos"

        # Verify we can get data. The real Arista driver returns a list of
        # interfaces (callers normalise via _as_interface_map); Mock returns a dict.
        interfaces = driver.get_interfaces()
        assert _interface_names(interfaces)

        driver.disconnect()

    def test_ocnos_connection(self):
        """Test connection to OcNOS device."""
        driver = OcnosDriver(host=OCNOS_HOST, user=USERNAME, password=OCNOS_PASSWORD)
        driver.connect()
        assert driver.platform == "ipinfusion_ocnos"

        # Verify we can get data (OcNOS get_vlans returns a list; Mock a dict)
        vlans = driver.get_vlans()
        assert isinstance(vlans, (list, dict))

        driver.disconnect()

    def test_ocnos_get_vnis_returns_list(self):
        """get_vnis() parses the vxlan tenants (regression: lxml predicate bug)."""
        driver = OcnosDriver(host=OCNOS_HOST, user=USERNAME, password=OCNOS_PASSWORD)
        driver.connect()
        vnis = driver.get_vnis()
        assert isinstance(vnis, list)
        assert all(isinstance(v, int) for v in vnis)
        driver.disconnect()


def _free_value(config_text: str, candidates, token):
    for v in candidates:
        if token(v) not in config_text:
            return v
    raise RuntimeError("no free value found for live test")


@pytest.mark.skipif(not RUN_LIVE_TESTS, reason="Live tests not enabled")
class TestLiveEvpn:
    """Full EVPN circuit create -> verify -> delete cycle (self-cleaning).

    Builds one circuit endpoint on a free port via EvpnManager, confirms it
    landed in the running config, then deletes it (VRF included).
    """

    def test_arista_evpn_circuit_create_delete(self):
        driver = AristaDriver(host=ARISTA_HOST, user=USERNAME, password=PASSWORD,
                              enable_password=os.getenv("ARISTA_ENABLE", "admin"))
        driver.connect()
        cfg = driver.get_config()
        vlan = _free_value(cfg, range(3700, 3999), lambda v: f"vlan {v} ")
        vni = _free_value(cfg, range(39900, 39999), lambda v: f"vni {v}")
        key = f"SO9{vni}"
        interface = os.getenv("ARISTA_EVPN_PORT", "Ethernet6")

        evpn = Evpn(vlan=Vlan(vlan_id=vlan, name=key), asn=ARISTA_ASN, vni=vni,
                    description=key, service_type="cloud_vc")
        ri = RoutingInstance(instance_name=key, instance_type="mac-vrf",
                             rd=f"{ARISTA_ASN}:{vni}", rt_rd=f"{TERACO_ASN}:{vni}")
        mgr = EvpnManager(driver)
        try:
            mgr.create_circuit(interface, evpn, routing_instance=ri)
            after = driver.get_config()
            assert f"vxlan vlan {vlan} vni {vni}" in after
            assert f"vlan-aware-bundle {key}" in after
        finally:
            mgr.delete_circuit(interface, evpn, routing_instance=ri, delete_vrf=True)
            driver.push_config([f"default interface {interface}"])
        final = driver.get_config()
        assert f"vni {vni}" not in final
        assert f"vlan-aware-bundle {key}" not in final
        driver.disconnect()

    def test_ocnos_evpn_circuit_create_delete(self):
        driver = OcnosDriver(host=OCNOS_HOST, user=USERNAME, password=OCNOS_PASSWORD)
        driver.connect()
        existing = set(driver.get_vnis())
        vni = next(v for v in range(39800, 39899) if v not in existing)
        vlan = vni - 36000  # 3800-range, parallel to vni
        key = f"SO9{vni}"
        interface = os.getenv("OCNOS_EVPN_PORT", "eth4")

        evpn = Evpn(vlan=Vlan(vlan_id=vlan, name=key), asn=65003, vni=vni,
                    description=key, service_type="cloud_vc")
        ri = RoutingInstance(instance_name=key, instance_type="mac-vrf",
                             rd=f"65003:{vni}", rt_rd=f"{TERACO_ASN}:{vni}")
        mgr = EvpnManager(driver)
        try:
            mgr.create_circuit(interface, evpn, routing_instance=ri)
            after = driver.get_config()
            assert key in after
            assert f"{interface}.{vlan}" in after
            assert str(vni) in after
        finally:
            mgr.delete_circuit(interface, evpn, routing_instance=ri, delete_vrf=True)
        final = driver.get_config()
        assert key not in final
        driver.disconnect()


@pytest.mark.skipif(not RUN_LIVE_TESTS, reason="Live tests not enabled")
class TestLiveLag:
    """Full single-switch LAG build -> verify -> delete cycle (self-cleaning).

    Runs against ar1 (Arista) and ipi1 (OcNOS). Uses migrate_vlans=False so the
    test never disturbs real VLAN config on the chosen ports.
    """

    def test_arista_lag_create_delete(self):
        driver = AristaDriver(host=ARISTA_HOST, user=USERNAME, password=PASSWORD)
        driver.connect()
        mgr = LagManager(driver)
        try:
            mgr.create_lag(ARISTA_LAG_NAME, ARISTA_LAG_MEMBERS, migrate_vlans=False)
            assert ARISTA_LAG_NAME in _interface_names(driver.get_interfaces())
        finally:
            mgr.delete_lag(ARISTA_LAG_NAME, ARISTA_LAG_MEMBERS)
        assert ARISTA_LAG_NAME not in _interface_names(driver.get_interfaces())
        driver.disconnect()

    def test_ocnos_lag_create_delete(self):
        driver = OcnosDriver(host=OCNOS_HOST, user=USERNAME, password=OCNOS_PASSWORD)
        mgr = LagManager(driver)
        try:
            mgr.create_lag(OCNOS_LAG_NAME, OCNOS_LAG_MEMBERS, migrate_vlans=False)
            assert OCNOS_LAG_NAME in _interface_names(driver.get_interfaces())
        finally:
            mgr.delete_lag(OCNOS_LAG_NAME, OCNOS_LAG_MEMBERS)
        assert OCNOS_LAG_NAME not in _interface_names(driver.get_interfaces())
        driver.disconnect()
