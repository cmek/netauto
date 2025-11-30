from jinja2 import Environment, PackageLoader, select_autoescape
from typing import List, Dict, Any
from pathlib import Path
from . import ocnos_xml
from .models import Interface, Lag


class TemplateRenderer:
    """Renders configuration templates for different network platforms."""

    def __init__(self):
        # Load templates from the package
        self.env = Environment(
            loader=PackageLoader("netauto", "templates"),
            autoescape=select_autoescape(),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def render_interface(self, platform: str, interface: Interface) -> List[str]:
        if platform == "ipinfusion_ocnos":
            xml = ocnos_xml.build_interface_config(interface=interface)
            return [xml]

        template_path = f"{platform}/interface.j2"
        template = self.env.get_template(template_path)
        rendered = template.render(interface)
        return [line for line in rendered.split("\n") if line.strip()]

    def render_lag(self, platform: str, **context) -> List[str]:
        """Render LAG configuration."""
        if platform == "ipinfusion_ocnos":
            # Use XML builder for OcNOS
            xml = ocnos_xml.build_lag_config(
                lag_number=context["lag_number"],
                members=context["members"],
                lacp_mode=context.get("lacp_mode", "active"),
                min_links=context.get("min_links", 1),
            )
            return [xml]

        template_path = f"{platform}/lag.j2"
        template = self.env.get_template(template_path)
        rendered = template.render(**context)
        return [line for line in rendered.split("\n") if line.strip()]

    def render_evpn(self, platform: str, **context) -> List[str]:
        """Render EVPN service configuration."""
        if platform == "ipinfusion_ocnos":
            # Use XML builder for OcNOS
            xml = ocnos_xml.build_evpn_service(
                vlan_id=context["vlan_id"],
                vni=context["vni"],
                vrf_name=context["vrf"]["name"],
                rd=context["vrf"]["rd"],
                rt_import=context["vrf"]["rt_import"],
                rt_export=context["vrf"]["rt_export"],
                s_tag=context.get("s_tag"),
            )
            return [xml]

        template_path = f"{platform}/evpn_service.j2"
        template = self.env.get_template(template_path)
        rendered = template.render(**context)
        return [line for line in rendered.split("\n") if line.strip()]

    def render_lag_delete(self, platform: str, **context) -> List[str]:
        """Render LAG delete configuration."""
        if platform == "ipinfusion_ocnos":
            xml = ocnos_xml.build_lag_delete(
                name=context["lag_name"], members=context.get("members", [])
            )
            return [xml]

        template_path = f"{platform}/lag_delete.j2"
        template = self.env.get_template(template_path)
        rendered = template.render(**context)
        return [line for line in rendered.split("\n") if line.strip()]

    def render_evpn_delete(self, platform: str, **context) -> List[str]:
        """Render EVPN service delete configuration."""
        if platform == "ipinfusion_ocnos":
            xml = ocnos_xml.build_evpn_delete(
                vlan_id=context["vlan_id"], vrf_name=context["vrf_name"]
            )
            return [xml]

        template_path = f"{platform}/evpn_delete.j2"
        template = self.env.get_template(template_path)
        rendered = template.render(**context)
        return [line for line in rendered.split("\n") if line.strip()]
