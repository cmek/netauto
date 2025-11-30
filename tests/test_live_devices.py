import pytest
import os
from netauto.drivers import AristaDriver, OcnosDriver
from netauto.models import EvpnService, Vrf

# Skip tests unless explicitly enabled
RUN_LIVE_TESTS = os.getenv("RUN_LIVE_TESTS") == "1"
ARISTA_HOST = os.getenv("ARISTA_HOST", "172.20.30.4")
OCNOS_HOST = os.getenv("OCNOS_HOST", "172.20.30.6")
USERNAME = os.getenv("DEVICE_USER", "admin")
PASSWORD = os.getenv("DEVICE_PASSWORD", "admin")

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
