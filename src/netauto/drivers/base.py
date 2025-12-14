from abc import ABC, abstractmethod
from typing import List, Dict, Any
from netauto.models import Interface, Vlan


class DeviceDriver(ABC):
    @property
    @abstractmethod
    def platform(self) -> str:
        """Return the platform identifier (e.g., 'arista_eos', 'ipinfusion_ocnos')."""
        pass

    @property
    @abstractmethod
    def lag_prefix(self) -> str:
        """Returns the prefix used for LAG interfaces (e.g. "Port-Channel" or "po")."""
        pass

    @abstractmethod
    def connect(self):
        pass

    @abstractmethod
    def disconnect(self):
        pass

    @abstractmethod
    def get_interfaces(self) -> Dict[str, Interface]:
        """Returns a dictionary of interface name to Interface model."""
        pass

    @abstractmethod
    def get_vlans(self) -> Dict[int, Vlan]:
        """Returns a dictionary of vlan_id to Vlan model."""
        pass

    @abstractmethod
    def get_vnis(self) -> Dict[int, Dict[str, Any]]:
        """Returns a dictionary of VNI to VNI information (vlan_id, etc.)."""
        pass

    @abstractmethod
    def push_config(self, commands: List[str], dry_run: bool = False) -> str:
        """Pushes a list of configuration commands to the device.

        Args:
            commands (List[str]): List of configuration commands to push.
            dry_run (bool): If True, do not commit changes, just simulate.

        Returns:
            str: The configuration diff after applying the commands. Or the intended changes in dry-run mode.
        """
        pass
