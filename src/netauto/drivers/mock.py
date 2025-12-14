from typing import List, Dict, Any
from ..models import Interface, Vlan
from .base import DeviceDriver


class MockDriver(DeviceDriver):
    def __init__(
        self,
        initial_interfaces: List[Interface] = None,
        initial_vlans: List[Vlan] = None,
        initial_vnis: Dict[int, Dict[str, Any]] = None,
        platform: str = "arista_eos",
    ):
        self.interfaces = {i.name: i for i in (initial_interfaces or [])}
        self.vlans = {v.vlan_id: v for v in (initial_vlans or [])}
        self.vnis = initial_vnis or {}  # Dict[vni -> {vlan_id, ...}]
        self.pushed_commands = []
        self._platform = platform

    @property
    def platform(self) -> str:
        return self._platform

    @property
    def lag_prefix(self) -> str:
        return "Port-Channel"

    def connect(self):
        print("MockDriver: Connected")

    def disconnect(self):
        print("MockDriver: Disconnected")

    def get_interfaces(self) -> Dict[str, Interface]:
        return self.interfaces

    def get_vlans(self) -> Dict[int, Vlan]:
        return self.vlans

    def get_vnis(self) -> Dict[int, Dict[str, Any]]:
        return self.vnis

    def push_config(self, commands: List[str]):
        print(f"MockDriver: Pushing {len(commands)} commands")
        for cmd in commands:
            print(f"  + {cmd}")
        self.pushed_commands.extend(commands)
