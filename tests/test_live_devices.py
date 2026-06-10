import pytest
import os
from netauto.drivers import AristaDriver, OcnosDriver
from netauto.logic import LagManager
from netauto.models import EvpnService, Vrf

# Skip tests unless explicitly enabled
RUN_LIVE_TESTS = os.getenv("RUN_LIVE_TESTS") == "1"
ARISTA_HOST = os.getenv("ARISTA_HOST", "172.20.30.4")
OCNOS_HOST = os.getenv("OCNOS_HOST", "172.20.30.6")
USERNAME = os.getenv("DEVICE_USER", "admin")
PASSWORD = os.getenv("DEVICE_PASSWORD", "admin")
# OcNOS uses a different default password than Arista (see lab_devices.md)
OCNOS_PASSWORD = os.getenv("OCNOS_PASSWORD", "admin@123")

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

        # Verify we can get data
        interfaces = driver.get_interfaces()
        assert isinstance(interfaces, dict)

        driver.disconnect()

    def test_ocnos_connection(self):
        """Test connection to OcNOS device."""
        driver = OcnosDriver(host=OCNOS_HOST, user=USERNAME, password=PASSWORD)
        driver.connect()
        assert driver.platform == "ipinfusion_ocnos"

        # Verify we can get data
        vlans = driver.get_vlans()
        assert isinstance(vlans, dict)

        driver.disconnect()

    def test_arista_evpn_validation(self):
        """Test VNI validation against real device."""
        driver = AristaDriver(host=ARISTA_HOST, user=USERNAME, password=PASSWORD)
        driver.connect()

        # Get existing VNIs
        vnis = driver.get_vnis()

        # If we have any VNIs, try to create a conflict
        if vnis:
            existing_vni = next(iter(vnis))
            from netauto.evpn import EvpnManager

            manager = EvpnManager(driver)

            vrf = Vrf(name="TEST", rd="1:1", rt_import=["1:1"], rt_export=["1:1"])
            service = EvpnService(vlan_id=999, vni=existing_vni, vrf_name="TEST")

            with pytest.raises(ValueError):
                manager.deploy_service(service, vrf)

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
