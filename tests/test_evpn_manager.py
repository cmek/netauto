import pytest
from netauto.models import EvpnService, Vrf
from netauto.drivers import MockDriver
from netauto.evpn import EvpnManager


class TestEvpnManager:
    """Test suite for EVPN service deployment logic."""

    def test_basic_evpn_service_deployment(self):
        """Test deploying a basic EVPN service."""
        driver = MockDriver()
        manager = EvpnManager(driver)

        vrf = Vrf(
            name="PROD",
            rd="10.1.1.1:10010",
            rt_import=["65001:10010"],
            rt_export=["65001:10010"],
        )
        service = EvpnService(vlan_id=10, vni=10010, vrf_name="PROD")

        commands = manager.deploy_service(service, vrf)

        # Join commands for easier assertion
        commands_str = "\n".join(commands)

        # Verify VLAN config
        assert "vlan 10" in commands_str
        assert "name EVPN_VLAN_10" in commands_str

        # Verify VRF config
        assert "vrf definition PROD" in commands_str
        assert "rd 10.1.1.1:10010" in commands_str
        assert "route-target import 65001:10010" in commands_str
        assert "route-target export 65001:10010" in commands_str

        # Verify VXLAN config
        assert "interface Vxlan1" in commands_str
        assert "vxlan vlan 10 vni 10010" in commands_str

        # Verify BGP config
        assert "router bgp 65001" in commands_str

    def test_evpn_service_with_multiple_rt(self):
        """Test EVPN service with multiple route targets."""
        driver = MockDriver()
        manager = EvpnManager(driver)

        vrf = Vrf(
            name="MULTI_RT",
            rd="10.1.1.1:20000",
            rt_import=["65001:20000", "65002:20000"],
            rt_export=["65001:20000", "65003:20000"],
        )
        service = EvpnService(vlan_id=20, vni=20000, vrf_name="MULTI_RT")

        commands = manager.deploy_service(service, vrf)

        # Join commands for easier assertion
        commands_str = "\n".join(commands)

        # Verify all RTs are present
        assert "route-target import 65001:20000" in commands_str
        assert "route-target import 65002:20000" in commands_str
        assert "route-target export 65001:20000" in commands_str
        assert "route-target export 65003:20000" in commands_str

    def test_multiple_evpn_services(self):
        """Test deploying multiple EVPN services."""
        driver = MockDriver()
        manager = EvpnManager(driver)

        vrf1 = Vrf(
            name="VRF1",
            rd="10.1.1.1:10",
            rt_import=["65001:10"],
            rt_export=["65001:10"],
        )
        service1 = EvpnService(vlan_id=10, vni=10010, vrf_name="VRF1")

        vrf2 = Vrf(
            name="VRF2",
            rd="10.1.1.1:20",
            rt_import=["65001:20"],
            rt_export=["65001:20"],
        )
        service2 = EvpnService(vlan_id=20, vni=20020, vrf_name="VRF2")

        commands1 = manager.deploy_service(service1, vrf1)
        commands2 = manager.deploy_service(service2, vrf2)

        # Verify first service
        commands1_str = "\n".join(commands1)
        assert "vlan 10" in commands1_str
        assert "vxlan vlan 10 vni 10010" in commands1_str

        # Verify second service
        commands2_str = "\n".join(commands2)
        assert "vlan 20" in commands2_str
        assert "vxlan vlan 20 vni 20020" in commands2_str

    def test_same_vlan_different_vni(self):
        """Test service with same VLAN but different VNI (edge case)."""
        driver = MockDriver()
        manager = EvpnManager(driver)

        vrf = Vrf(
            name="TEST",
            rd="10.1.1.1:30",
            rt_import=["65001:30"],
            rt_export=["65001:30"],
        )
        service1 = EvpnService(vlan_id=100, vni=30010, vrf_name="TEST")
        service2 = EvpnService(vlan_id=100, vni=30020, vrf_name="TEST")

        commands1 = manager.deploy_service(service1, vrf)
        commands2 = manager.deploy_service(service2, vrf)

        # Both should generate valid configs even with same VLAN
        commands1_str = "\n".join(commands1)
        commands2_str = "\n".join(commands2)
        assert "vlan 100" in commands1_str
        assert "vxlan vlan 100 vni 30010" in commands1_str
        assert "vxlan vlan 100 vni 30020" in commands2_str

    def test_vrf_with_asymmetric_rt(self):
        """Test VRF with different import and export RTs."""
        driver = MockDriver()
        manager = EvpnManager(driver)

        vrf = Vrf(
            name="ASYMMETRIC",
            rd="10.1.1.1:40",
            rt_import=["65001:40", "65002:40"],
            rt_export=["65001:40"],
        )
        service = EvpnService(vlan_id=40, vni=40040, vrf_name="ASYMMETRIC")

        commands = manager.deploy_service(service, vrf)

        # Join commands for easier assertion
        commands_str = "\n".join(commands)

        # Verify asymmetric RTs
        import_count = sum(1 for c in commands if "route-target import" in c)
        export_count = sum(1 for c in commands if "route-target export" in c)

        assert import_count == 2
        assert export_count == 1

    def test_evpn_service_with_mcast_group(self):
        """Test EVPN service with multicast group (optional field)."""
        driver = MockDriver()
        manager = EvpnManager(driver)

        vrf = Vrf(
            name="MCAST",
            rd="10.1.1.1:50",
            rt_import=["65001:50"],
            rt_export=["65001:50"],
        )
        service = EvpnService(
            vlan_id=50, vni=50050, vrf_name="MCAST", mcast_group="239.1.1.1"
        )

        commands = manager.deploy_service(service, vrf)

        # Should still generate valid config
        commands_str = "\n".join(commands)
        assert "vlan 50" in commands_str
        assert "vxlan vlan 50 vni 50050" in commands_str

    def test_apply_pushes_to_driver(self):
        """Test that apply() pushes commands to driver."""
        driver = MockDriver()
        manager = EvpnManager(driver)

        vrf = Vrf(
            name="APPLY_TEST",
            rd="10.1.1.1:60",
            rt_import=["65001:60"],
            rt_export=["65001:60"],
        )
        service = EvpnService(vlan_id=60, vni=60060, vrf_name="APPLY_TEST")

        commands = manager.deploy_service(service, vrf)
        manager.apply(commands)

        # Verify commands were pushed
        assert len(driver.pushed_commands) > 0
        assert driver.pushed_commands == commands

    def test_evpn_service_command_order(self):
        """Test that commands are generated in the correct order."""
        driver = MockDriver()
        manager = EvpnManager(driver)

        vrf = Vrf(
            name="ORDER",
            rd="10.1.1.1:70",
            rt_import=["65001:70"],
            rt_export=["65001:70"],
        )
        service = EvpnService(vlan_id=70, vni=70070, vrf_name="ORDER")

        commands = manager.deploy_service(service, vrf)

        # Find indices of key commands
        vlan_idx = next(i for i, c in enumerate(commands) if "vlan 70" in c)
        vrf_idx = next(i for i, c in enumerate(commands) if "vrf definition" in c)
        vxlan_idx = next(i for i, c in enumerate(commands) if "interface Vxlan1" in c)
        bgp_idx = next(i for i, c in enumerate(commands) if "router bgp" in c)

        # Verify order: VLAN -> VRF -> VXLAN -> BGP
        assert vlan_idx < vrf_idx < vxlan_idx < bgp_idx

    def test_vni_conflict_detection(self):
        """Test that VNI conflicts are detected."""
        # Setup driver with existing VNI
        initial_vnis = {10010: {"vlan_id": 10}}
        driver = MockDriver(initial_vnis=initial_vnis)
        manager = EvpnManager(driver)

        vrf = Vrf(
            name="CONFLICT",
            rd="10.1.1.1:80",
            rt_import=["65001:80"],
            rt_export=["65001:80"],
        )
        service = EvpnService(
            vlan_id=80, vni=10010, vrf_name="CONFLICT"
        )  # VNI 10010 already in use

        with pytest.raises(ValueError, match="VNI 10010 is already in use"):
            manager.deploy_service(service, vrf)

    def test_vni_no_conflict_with_different_vni(self):
        """Test that different VNIs don't conflict."""
        # Setup driver with existing VNI
        initial_vnis = {10010: {"vlan_id": 10}}
        driver = MockDriver(initial_vnis=initial_vnis)
        manager = EvpnManager(driver)

        vrf = Vrf(
            name="NO_CONFLICT",
            rd="10.1.1.1:90",
            rt_import=["65001:90"],
            rt_export=["65001:90"],
        )
        service = EvpnService(
            vlan_id=90, vni=20020, vrf_name="NO_CONFLICT"
        )  # VNI 20020 is not in use

    def test_evpn_service_with_stag(self):
        """Test EVPN service with S-TAG."""
        driver = MockDriver()
        manager = EvpnManager(driver)

        vrf = Vrf(
            name="STAG_TEST",
            rd="10.1.1.1:99",
            rt_import=["65001:99"],
            rt_export=["65001:99"],
        )
        service = EvpnService(vlan_id=99, vni=99099, vrf_name="STAG_TEST", s_tag=200)

        commands = manager.deploy_service(service, vrf)
        commands_str = "\n".join(commands)

        # Verify S-TAG is used in the name (as per our template implementation)
        assert "EVPN_VLAN_99_STAG_200" in commands_str
