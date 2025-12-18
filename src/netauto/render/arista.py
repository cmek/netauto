from .base import DeviceRenderer
from jinja2 import Environment, PackageLoader, select_autoescape
from typing import List
from pathlib import Path
from netauto.models import Interface, Lag, Evpn, Vlan


class AristaDeviceRenderer(DeviceRenderer):
    """Renders configuration templates for Arista EOS devices."""

    def __init__(self):
        # Load templates from the package
        self.env = Environment(
            loader=PackageLoader("netauto", "templates"),
            autoescape=select_autoescape(),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def render_interface(self, interface: Interface) -> List[str]:
        template_path = f"arista_eos/interface.j2"
        template = self.env.get_template(template_path)
        rendered = template.render(interface=interface)
        return [line for line in rendered.split("\n") if line.strip()]

    def render_interface_delete(self, interface: Interface) -> List[str]:
        pass

    def render_lag(self, lag: Lag) -> List[str]:
        """Render LAG configuration."""
        template_path = f"arista_eos/lag.j2"
        template = self.env.get_template(template_path)
        rendered = template.render(lag=lag)
        return [line for line in rendered.split("\n") if line.strip()]

    def render_lag_delete(self, lag: Lag) -> List[str]:
        pass

    def render_evpn(self, interface: Interface, evpn: Evpn) -> List[str]:
        """Render EVPN service configuration."""
        template_path = f"arista_eos/evpn.j2"
        template = self.env.get_template(template_path)
        rendered = template.render(interface=interface, evpn=evpn)
        return [line for line in rendered.split("\n") if line.strip()]

    def render_evpn_delete(self, interface: Interface, evpn: Evpn) -> List[str]:
        """Render EVPN service delete configuration."""
        template_path = f"arista_eos/evpn_delete.j2"
        template = self.env.get_template(template_path)
        rendered = template.render(interface=interface, evpn=evpn)
        return [line for line in rendered.split("\n") if line.strip()]

    def render_vlan(self, interface: Interface, vlan: Vlan) -> List[str]:
        """Render VLAN configuration."""
        template_path = f"arista_eos/vlan.j2"
        template = self.env.get_template(template_path)
        rendered = template.render(interface=interface, vlan=vlan)
        return [line for line in rendered.split("\n") if line.strip()]

    def render_vlan_delete(self, interface: Interface, vlan: Vlan) -> List[str]:
        """Render VLAN delete configuration."""
        template_path = f"arista_eos/vlan_delete.j2"
        template = self.env.get_template(template_path)
        rendered = template.render(interface=interface, vlan=vlan)
        return [line for line in rendered.split("\n") if line.strip()]
