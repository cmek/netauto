from typing import List
from .models import EvpnService, Vrf
from .drivers import DeviceDriver
from .renderer import TemplateRenderer

class EvpnManager:
    def __init__(self, driver: DeviceDriver):
        self.driver = driver
        self.renderer = TemplateRenderer()

    def deploy_service(self, service: EvpnService, vrf: Vrf, bgp_as: int = 65001) -> List[str]:
        """
        Generates configuration to deploy an EVPN service using templates.
        Validates that the VNI is not already in use.
        """
        # Validate VNI is not in use
        existing_vnis = self.driver.get_vnis()
        if service.vni in existing_vnis:
            raise ValueError(
                f"VNI {service.vni} is already in use "
                f"(mapped to VLAN {existing_vnis[service.vni].get('vlan_id', 'unknown')})"
            )

        # Prepare context for template
        context = {
            'vlan_id': service.vlan_id,
            'vni': service.vni,
            's_tag': service.s_tag,
            'vrf': {
                'name': vrf.name,
                'rd': vrf.rd,
                'rt_import': vrf.rt_import,
                'rt_export': vrf.rt_export
            },
            'bgp_as': bgp_as
        }

        # Render configuration using template
        commands = self.renderer.render_evpn(self.driver.platform, **context)

        return commands

    def delete_service(self, service: EvpnService, vrf_name: str, bgp_as: int = 65001) -> List[str]:
        """
        Generates configuration to delete an EVPN service using templates.
        """
        # Prepare context for template
        context = {
            'vlan_id': service.vlan_id,
            'vni': service.vni,
            'vrf_name': vrf_name,
            'bgp_as': bgp_as
        }

        # Render delete configuration using template
        commands = self.renderer.render_evpn_delete(self.driver.platform, **context)

        return commands

    def apply(self, commands: List[str]):
        self.driver.push_config(commands)
