import pytest
from pydantic import ValidationError
from netauto.models import Vlan, Interface, Lag, Vrf, Bgp, EvpnService


class TestModels:
    """Test suite for Pydantic model validation."""

    def test_vlan_valid_id(self):
        """Test VLAN with valid ID."""
        vlan = Vlan(vlan_id=100, name="Test VLAN")
        assert vlan.vlan_id == 100
        assert vlan.name == "Test VLAN"

    def test_vlan_id_too_low(self):
        """Test VLAN ID below minimum (1)."""
        with pytest.raises(ValidationError):
            Vlan(vlan_id=0, name="Invalid")

    def test_vlan_id_too_high(self):
        """Test VLAN ID above maximum (4094)."""
        with pytest.raises(ValidationError):
            Vlan(vlan_id=4095, name="Invalid")

    def test_vlan_boundary_values(self):
        """Test VLAN boundary values (1 and 4094)."""
        vlan_min = Vlan(vlan_id=1, name="Min")
        vlan_max = Vlan(vlan_id=4094, name="Max")
        assert vlan_min.vlan_id == 1
        assert vlan_max.vlan_id == 4094

    def test_interface_defaults(self):
        """Test Interface model default values."""
        interface = Interface(name="Ethernet1")
        assert interface.enabled is True
        assert interface.mtu == 1500
        assert interface.mode == "access"
        assert interface.access_vlan is None
        assert interface.trunk_vlans == []

    def test_interface_trunk_mode(self):
        """Test Interface in trunk mode."""
        interface = Interface(name="Ethernet1", mode="trunk", trunk_vlans=[10, 20, 30])
        assert interface.mode == "trunk"
        assert interface.trunk_vlans == [10, 20, 30]

    def test_interface_access_mode(self):
        """Test Interface in access mode."""
        interface = Interface(name="Ethernet1", mode="access", access_vlan=100)
        assert interface.mode == "access"
        assert interface.access_vlan == 100

    def test_lag_inherits_interface(self):
        """Test that Lag inherits from Interface."""
        lag = Lag(name="Port-Channel1", members=["Ethernet1", "Ethernet2"])
        assert isinstance(lag, Interface)
        assert lag.members == ["Ethernet1", "Ethernet2"]
        assert lag.lacp_mode == "active"
        assert lag.min_links == 1

    def test_lag_lacp_modes(self):
        """Test LAG LACP mode validation."""
        lag_active = Lag(name="Po1", lacp_mode="active", members=["Eth1"])
        lag_passive = Lag(name="Po2", lacp_mode="passive", members=["Eth2"])
        lag_static = Lag(name="Po3", lacp_mode="static", members=["Eth3"])

        assert lag_active.lacp_mode == "active"
        assert lag_passive.lacp_mode == "passive"
        assert lag_static.lacp_mode == "static"

    def test_vrf_model(self):
        """Test VRF model."""
        vrf = Vrf(
            name="PROD",
            rd="10.1.1.1:100",
            rt_import=["65001:100"],
            rt_export=["65001:100"]
        )
        assert vrf.name == "PROD"
        assert vrf.rd == "10.1.1.1:100"
        assert len(vrf.rt_import) == 1
        assert len(vrf.rt_export) == 1

    def test_vrf_multiple_rt(self):
        """Test VRF with multiple route targets."""
        vrf = Vrf(
            name="MULTI",
            rd="10.1.1.1:200",
            rt_import=["65001:200", "65002:200"],
            rt_export=["65001:200", "65003:200", "65004:200"]
        )
        assert len(vrf.rt_import) == 2
        assert len(vrf.rt_export) == 3

    def test_bgp_model(self):
        """Test BGP model."""
        bgp = Bgp(as_number=65001, router_id="10.1.1.1", neighbors=["10.1.1.2", "10.1.1.3"])
        assert bgp.as_number == 65001
        assert bgp.router_id == "10.1.1.1"
        assert len(bgp.neighbors) == 2

    def test_bgp_defaults(self):
        """Test BGP model with defaults."""
        bgp = Bgp(as_number=65001, router_id="10.1.1.1")
        assert bgp.neighbors == []

    def test_evpn_service_model(self):
        """Test EVPN service model."""
        service = EvpnService(vlan_id=100, vni=10100, vrf_name="TEST")
        assert service.vlan_id == 100
        assert service.vni == 10100
        assert service.vrf_name == "TEST"
        assert service.mcast_group is None

    def test_evpn_service_with_mcast(self):
        """Test EVPN service with multicast group."""
        service = EvpnService(
            vlan_id=200,
            vni=20200,
            vrf_name="MCAST_TEST",
            mcast_group="239.1.1.1"
        )
        assert service.mcast_group == "239.1.1.1"

    def test_interface_mode_validation(self):
        """Test that invalid interface modes are rejected."""
        with pytest.raises(ValidationError):
            Interface(name="Eth1", mode="invalid_mode")

    def test_required_fields(self):
        """Test that required fields are enforced."""
        # Vlan requires vlan_id and name
        with pytest.raises(ValidationError):
            Vlan(name="Test")  # Missing vlan_id

        # Interface requires name
        with pytest.raises(ValidationError):
            Interface()

        # VRF requires all fields
        with pytest.raises(ValidationError):
            Vrf(name="TEST")  # Missing rd, rt_import, rt_export
