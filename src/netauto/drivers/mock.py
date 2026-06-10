from typing import List, Dict, Any
from ..models import Interface, Vlan, Lag, Evpn
from .base import DeviceDriver
from netauto.render import AristaDeviceRenderer, OcnosDeviceRenderer


class MockDriver(DeviceDriver):
    """In-memory driver for testing config generation without a real device.

    Records everything pushed in ``pushed_commands`` and renders LAG config with
    the renderer matching ``platform`` so a single Mock can exercise both vendors.
    """

    def __init__(
        self,
        initial_interfaces: List[Interface] = None,
        initial_vlans: List[Vlan] = None,
        initial_vnis: Dict[int, Dict[str, Any]] = None,
        initial_switchports: List[Interface] = None,
        platform: str = "arista_eos",
    ):
        self.interfaces = {i.name: i for i in (initial_interfaces or [])}
        self.vlans = {v.vlan_id: v for v in (initial_vlans or [])}
        self.vnis = initial_vnis or {}  # Dict[vni -> {vlan_id, ...}]
        self.switchports = {i.name: i for i in (initial_switchports or [])}
        self.pushed_commands = []
        self._platform = platform
        self.renderer = (
            OcnosDeviceRenderer()
            if platform == "ipinfusion_ocnos"
            else AristaDeviceRenderer()
        )

    @property
    def platform(self) -> str:
        return self._platform

    @property
    def lag_prefix(self) -> str:
        return "po" if self._platform == "ipinfusion_ocnos" else "Port-Channel"

    def connect(self):
        print("MockDriver: Connected")

    def disconnect(self):
        print("MockDriver: Disconnected")

    def get_config(self, config_type: str = "running", format: str | None = None) -> str:
        # No real device; return the recorded commands as a pseudo-config.
        return "\n".join(str(c) for c in self.pushed_commands)

    def get_interfaces(self) -> Dict[str, Interface]:
        return self.interfaces

    def get_vlans(self) -> Dict[int, Vlan]:
        return self.vlans

    def get_vnis(self) -> Dict[int, Dict[str, Any]]:
        return self.vnis

    def get_switchports(self) -> Dict[str, Interface]:
        return self.switchports

    def push_config(self, commands: List[str], dry_run: bool = False) -> str:
        print(f"MockDriver: Pushing {len(commands)} commands (dry_run={dry_run})")
        for cmd in commands:
            print(f"  + {cmd}")
        if not dry_run:
            self.pushed_commands.extend(commands)
        return "\n".join(str(c) for c in commands)

    def push_lag(self, lag: Lag, delete: bool = False, dry_run: bool = False) -> str:
        rendered = (
            self.renderer.render_lag_delete(lag)
            if delete
            else self.renderer.render_lag(lag)
        )
        # Arista renderer returns a list of lines; OcNOS returns a single XML string.
        commands = rendered if isinstance(rendered, list) else [rendered]
        return self.push_config(commands, dry_run=dry_run)

    def push_evpn(
        self,
        interface: Interface,
        evpn: Evpn,
        delete: bool = False,
        dry_run: bool = False,
    ) -> str:
        rendered = (
            self.renderer.render_evpn_delete(interface, evpn)
            if delete
            else self.renderer.render_evpn(interface, evpn)
        )
        # Arista renderer returns a list of lines; OcNOS returns a single XML string.
        commands = rendered if isinstance(rendered, list) else [rendered]
        return self.push_config(commands, dry_run=dry_run)
