import pytest
from netauto.models import Interface, Vlan
from netauto.drivers import MockDriver


class TestMockDriver:
    """Test suite for MockDriver functionality."""

    def test_mock_driver_initialization(self):
        """Test MockDriver initialization."""
        driver = MockDriver()
        assert len(driver.interfaces) == 0
        assert len(driver.vlans) == 0
        assert len(driver.pushed_commands) == 0

    def test_mock_driver_with_initial_interfaces(self):
        """Test MockDriver with initial interfaces."""
        interfaces = [
            Interface(name="Ethernet1", mode="trunk", trunk_vlans=[10, 20]),
            Interface(name="Ethernet2", mode="access", access_vlan=100),
        ]
        driver = MockDriver(initial_interfaces=interfaces)

        assert len(driver.interfaces) == 2
        assert "Ethernet1" in driver.interfaces
        assert "Ethernet2" in driver.interfaces
        assert driver.interfaces["Ethernet1"].trunk_vlans == [10, 20]

    def test_mock_driver_with_initial_vlans(self):
        """Test MockDriver with initial VLANs."""
        vlans = [
            Vlan(vlan_id=10, name="VLAN10"),
            Vlan(vlan_id=20, name="VLAN20"),
        ]
        driver = MockDriver(initial_vlans=vlans)

        assert len(driver.vlans) == 2
        assert 10 in driver.vlans
        assert 20 in driver.vlans
        assert driver.vlans[10].name == "VLAN10"

    def test_get_interfaces(self):
        """Test get_interfaces method."""
        interfaces = [Interface(name="Ethernet1")]
        driver = MockDriver(initial_interfaces=interfaces)

        result = driver.get_interfaces()
        assert result == driver.interfaces
        assert "Ethernet1" in result

    def test_get_vlans(self):
        """Test get_vlans method."""
        vlans = [Vlan(vlan_id=100, name="Test")]
        driver = MockDriver(initial_vlans=vlans)

        result = driver.get_vlans()
        assert result == driver.vlans
        assert 100 in result

    def test_push_config(self):
        """Test push_config method."""
        driver = MockDriver()
        commands = ["interface Ethernet1", "no shutdown", "exit"]

        driver.push_config(commands)

        assert len(driver.pushed_commands) == 3
        assert driver.pushed_commands == commands

    def test_push_config_multiple_times(self):
        """Test pushing config multiple times accumulates commands."""
        driver = MockDriver()

        driver.push_config(["command1", "command2"])
        driver.push_config(["command3", "command4"])

        assert len(driver.pushed_commands) == 4
        assert driver.pushed_commands == ["command1", "command2", "command3", "command4"]

    def test_connect_disconnect(self):
        """Test connect and disconnect methods."""
        driver = MockDriver()

        # These should not raise exceptions
        driver.connect()
        driver.disconnect()

    def test_mock_driver_state_isolation(self):
        """Test that multiple MockDriver instances have isolated state."""
        driver1 = MockDriver(initial_interfaces=[Interface(name="Eth1")])
        driver2 = MockDriver(initial_interfaces=[Interface(name="Eth2")])

        assert "Eth1" in driver1.interfaces
        assert "Eth1" not in driver2.interfaces
        assert "Eth2" in driver2.interfaces
        assert "Eth2" not in driver1.interfaces
