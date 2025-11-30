import pytest
from netauto.models import Interface
from netauto.drivers import MockDriver
from netauto.logic import InterfaceManager


class TestInterfaceManager:
    """Test suite for managing Interface config."""

    def test_basic_interface_updates(self):
        """Test creating a LAG from two trunk ports with VLANs."""
        initial_interfaces = [
            Interface(
                name="Ethernet1",
                mode="trunk",
                mtu=1500,
                description="something",
                trunk_vlans=[10, 20],
            ),
            Interface(name="Ethernet2", mode="trunk", trunk_vlans=[20, 30]),
        ]
        driver = MockDriver(initial_interfaces=initial_interfaces)
        manager = InterfaceManager(driver, "Ethernet1")

        manager.mtu = 1400
        manager.description = "test123"
        commands = manager.apply()

        # Verify VLANs were merged (10, 20, 30)
        commands_str = "\n".join(commands)
        assert "mtu 1400" in commands_str
        assert "description test123" in commands_str
