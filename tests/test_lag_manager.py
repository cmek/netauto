import pytest
from netauto.models import Interface
from netauto.drivers import MockDriver
from netauto.logic import LagManager


class TestLagManager:
    """Test suite for LAG migration logic with all edge cases."""

    def test_basic_lag_creation_with_trunk_ports(self):
        """Test creating a LAG from two trunk ports with VLANs."""
        initial_interfaces = [
            Interface(name="Ethernet1", mode="trunk", trunk_vlans=[10, 20]),
            Interface(name="Ethernet2", mode="trunk", trunk_vlans=[20, 30]),
        ]
        driver = MockDriver(initial_interfaces=initial_interfaces)
        manager = LagManager(driver)

        commands = manager.create_lag("Port-Channel1", ["Ethernet1", "Ethernet2"])

        # Verify VLANs were merged (10, 20, 30)
        commands_str = "\n".join(commands)
        assert "switchport trunk allowed vlan 10,20,30" in commands_str
        assert "interface Port-Channel1" in commands_str
        assert "channel-group 1 mode active" in commands_str

    def test_basic_lag_creation_with_access_ports(self):
        """Test creating a LAG from two access ports."""
        initial_interfaces = [
            Interface(name="Ethernet1", mode="access", access_vlan=100),
            Interface(name="Ethernet2", mode="access", access_vlan=100),
        ]
        driver = MockDriver(initial_interfaces=initial_interfaces)
        manager = LagManager(driver)

        commands = manager.create_lag("Port-Channel1", ["Ethernet1", "Ethernet2"])

        # Should migrate access VLAN
        commands_str = "\n".join(commands)
        assert "100" in commands_str
        assert "interface Port-Channel1" in commands_str

    def test_port_already_in_lag_raises_error(self):
        """Test that using a port already in a LAG raises ValueError."""
        initial_interfaces = [
            Interface(
                name="Ethernet1",
                mode="trunk",
                trunk_vlans=[10],
                lag_member_of="Port-Channel99",
            ),
            Interface(name="Ethernet2", mode="trunk", trunk_vlans=[20]),
        ]
        driver = MockDriver(initial_interfaces=initial_interfaces)
        manager = LagManager(driver)

        with pytest.raises(ValueError, match="already a member of"):
            manager.create_lag("Port-Channel1", ["Ethernet1", "Ethernet2"])

    def test_non_existent_port_raises_error(self):
        """Test that using a non-existent port raises ValueError."""
        initial_interfaces = [
            Interface(name="Ethernet1", mode="trunk", trunk_vlans=[10]),
        ]
        driver = MockDriver(initial_interfaces=initial_interfaces)
        manager = LagManager(driver)

        with pytest.raises(ValueError, match="does not exist"):
            manager.create_lag("Port-Channel1", ["Ethernet1", "Ethernet999"])

    def test_vlan_migration_trunk_ports(self):
        """Test VLAN migration from trunk ports."""
        initial_interfaces = [
            Interface(name="Ethernet1", mode="trunk", trunk_vlans=[10, 20, 30]),
            Interface(name="Ethernet2", mode="trunk", trunk_vlans=[30, 40, 50]),
        ]
        driver = MockDriver(initial_interfaces=initial_interfaces)
        manager = LagManager(driver)

        commands = manager.create_lag("Port-Channel1", ["Ethernet1", "Ethernet2"])

        # Should merge all VLANs: 10, 20, 30, 40, 50
        commands_str = "\n".join(commands)
        assert "trunk allowed vlan" in commands_str
        # Check all VLANs are present
        for vlan in ["10", "20", "30", "40", "50"]:
            assert vlan in commands_str

    def test_mixed_trunk_access_ports(self):
        """Test creating LAG with mixed trunk and access ports."""
        initial_interfaces = [
            Interface(name="Ethernet1", mode="trunk", trunk_vlans=[10, 20]),
            Interface(name="Ethernet2", mode="access", access_vlan=30),
        ]
        driver = MockDriver(initial_interfaces=initial_interfaces)
        manager = LagManager(driver)

        commands = manager.create_lag("Port-Channel1", ["Ethernet1", "Ethernet2"])

        # Should merge all VLANs: 10, 20, 30
        commands_str = "\n".join(commands)
        assert "trunk allowed vlan" in commands_str
        for vlan in ["10", "20", "30"]:
            assert vlan in commands_str

    def test_no_vlans_on_ports(self):
        """Test creating LAG from ports with no VLANs."""
        initial_interfaces = [
            Interface(name="Ethernet1", mode="routed"),
            Interface(name="Ethernet2", mode="routed"),
        ]
        driver = MockDriver(initial_interfaces=initial_interfaces)
        manager = LagManager(driver)

        commands = manager.create_lag("Port-Channel1", ["Ethernet1", "Ethernet2"])

        # Should create LAG without switchport config
        commands_str = "\n".join(commands)
        assert "no switchport" in commands_str
        assert "interface Port-Channel1" in commands_str

    def test_single_port_lag(self):
        """Test creating a LAG with a single port (edge case but valid)."""
        initial_interfaces = [
            Interface(name="Ethernet1", mode="trunk", trunk_vlans=[10]),
        ]
        driver = MockDriver(initial_interfaces=initial_interfaces)
        manager = LagManager(driver)

        commands = manager.create_lag("Port-Channel1", ["Ethernet1"])

        # Should work
        commands_str = "\n".join(commands)
        assert "interface Port-Channel1" in commands_str
        assert "channel-group 1 mode active" in commands_str

    def test_different_lacp_modes(self):
        """Test creating LAG with different LACP modes."""
        initial_interfaces = [
            Interface(name="Ethernet1", mode="trunk", trunk_vlans=[10]),
            Interface(name="Ethernet2", mode="trunk", trunk_vlans=[10]),
        ]
        driver = MockDriver(initial_interfaces=initial_interfaces)
        manager = LagManager(driver)

        # Test passive mode
        commands = manager.create_lag(
            "Port-Channel1", ["Ethernet1", "Ethernet2"], lacp_mode="passive"
        )
        commands_str = "\n".join(commands)
        assert "channel-group 1 mode passive" in commands_str

    def test_apply_pushes_to_driver(self):
        """Test that apply() pushes commands to driver."""
        initial_interfaces = [
            Interface(name="Ethernet1", mode="trunk", trunk_vlans=[10]),
        ]
        driver = MockDriver(initial_interfaces=initial_interfaces)
        manager = LagManager(driver)

        commands = manager.create_lag("Port-Channel1", ["Ethernet1"])
        manager.apply(commands)

        # Verify commands were pushed
        assert len(driver.pushed_commands) > 0
        assert driver.pushed_commands == commands

    def test_delete_lag(self):
        """Test deleting a LAG configuration."""
        driver = MockDriver()
        manager = LagManager(driver)

        commands = manager.delete_lag("Port-Channel1", ["Ethernet1", "Ethernet2"])
        commands_str = "\n".join(commands)

        assert "no channel-group" in commands_str
        assert "no interface Port-Channel1" in commands_str
        assert "interface Ethernet1" in commands_str
        assert "interface Ethernet2" in commands_str

    def test_delete_lag_apply(self):
        """Test that delete_lag commands are pushed to driver."""
        driver = MockDriver()
        manager = LagManager(driver)

        commands = manager.delete_lag("Port-Channel10", ["Ethernet5"])
        manager.apply(commands)

        assert len(driver.pushed_commands) > 0
        assert driver.pushed_commands == commands
