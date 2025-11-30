import logging
from typing import List, Set
from .models import Interface, Lag
from .drivers import DeviceDriver
from .renderer import TemplateRenderer
from .exceptions import NetAutoException

logger = logging.getLogger(__name__)


class InterfaceManager:
    def __init__(self, driver: DeviceDriver, name: str):
        self.driver = driver
        self.name = name
        self.renderer = TemplateRenderer()
        interfaces = driver.get_interfaces()
        self.interface = interfaces.get(name, None)
        if self.interface is None:
            raise NetAutoException(f"Interface {name} not found")

    @property
    def description(self):
        return self.interface.description

    @description.setter
    def description(self, description):
        self.interface.description = description

    @property
    def mtu(self):
        return self.interface.mtu

    @mtu.setter
    def mtu(self, mtu):
        self.interface.mtu = mtu

    def apply(self):
        """applies current configuration"""
        commands = self.renderer.render_interface(self.driver.platform, self.interface)
        logger.info(f"interface commands: {commands}")
        response = self.driver.push_config(commands)
        return commands


class LagManager:
    def __init__(self, driver: DeviceDriver):
        self.driver = driver
        self.renderer = TemplateRenderer()

    def create_lag(
        self, lag_name: str, member_ports: List[str], lacp_mode: str = "active"
    ) -> List[str]:
        """
        Creates a LAG, migrating VLANs from member ports if they exist.
        Returns a list of commands to execute.
        """
        # 1. Get current state
        current_interfaces = self.driver.get_interfaces()

        # 2. Validation
        for port in member_ports:
            if port not in current_interfaces:
                raise ValueError(f"Port {port} does not exist on device.")
            if current_interfaces[port].lag_member_of:
                raise ValueError(
                    f"Port {port} is already a member of {current_interfaces[port].lag_member_of}"
                )

        # 3. Collect VLANs to migrate
        vlans_to_migrate: Set[int] = set()
        for port in member_ports:
            interface = current_interfaces[port]
            if interface.mode == "trunk":
                vlans_to_migrate.update(interface.trunk_vlans)
            elif interface.mode == "access" and interface.access_vlan:
                vlans_to_migrate.add(interface.access_vlan)

        logger.debug(f"Found VLANs to migrate: {vlans_to_migrate}")

        # 4. Extract LAG number from name (e.g., "po10" -> 10)
        lag_number = int(lag_name.replace(self.driver.lag_prefix, ""))

        # 5. Prepare context for template
        context = {
            "lag_name": lag_name,
            "lag_number": lag_number,
            "members": member_ports,
            "vlans": sorted(vlans_to_migrate),
            "lacp_mode": lacp_mode,
            "has_vlans": bool(vlans_to_migrate),
        }

        # 6. Render configuration using template
        commands = self.renderer.render_lag(self.driver.platform, **context)

        return commands

    def delete_lag(self, lag_name: str, member_ports: List[str]) -> List[str]:
        """
        Deletes a LAG configuration.
        Returns a list of commands to execute.
        """
        # Extract LAG number from name
        lag_number = int(lag_name.replace("Port-Channel", ""))

        # Prepare context for template
        context = {
            "lag_name": lag_name,
            "lag_number": lag_number,
            "members": member_ports,
        }

        # Render delete configuration using template
        commands = self.renderer.render_lag_delete(self.driver.platform, **context)

        return commands

    def apply(self, commands: List[str]):
        response = self.driver.push_config(commands)
        return response
