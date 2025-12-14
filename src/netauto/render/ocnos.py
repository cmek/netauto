from .base import DeviceRenderer
import xml.etree.ElementTree as ET
import xml.dom.minidom
from typing import List, Dict, Any, Optional
from netauto.models import Interface, Lag, Vlan, EvpnService


class OcnosDeviceRenderer(DeviceRenderer):
    def _tostring(self, element: ET.Element) -> str:
        """Converts an Element to a string."""
        raw = ET.tostring(element, encoding="unicode")
        # this is not the most efficient approach ;)
        parsed = xml.dom.minidom.parseString(raw)
        return parsed.toprettyxml(indent="  ")

    def _config_root(self) -> ET.Element:
        """Create the root <config> element for OcNOS XML configuration."""
        return ET.Element("config")

    def _append_interface(self, root: ET.Element, interface: Interface) -> ET.Element:
        interfaces = ET.SubElement(
            root,
            "interfaces",
            xmlns="http://www.ipinfusion.com/yang/ocnos/ipi-interface",
        )
        intf = ET.SubElement(interfaces, "interface")
        ET.SubElement(intf, "name").text = interface.name
        intf_config = ET.SubElement(intf, "config")
        ET.SubElement(intf_config, "mtu").text = str(interface.mtu)
        ET.SubElement(intf_config, "description").text = interface.description

        return root

    def render_interface(self, interface) -> List[str]:
        """Render interface configuration."""
        # Implementation for OcNOS interface rendering
        config = self._config_root()
        if_config = self._append_interface(config, interface)
        return self._tostring(if_config)

    def render_interface_delete(self, interface: Interface) -> List[str]:
        """Render interface configuration commands for the given platform."""
        pass

    def render_lag(self, lag: Lag) -> List[str]:
        """Render LAG configuration commands for the given platform."""
        pass

    def render_lag_delete(self, lag: Lag) -> List[str]:
        """Render LAG configuration commands for the given platform."""
        pass

    def _append_vlan(
        self, root: ET.Element, interface: Interface, vlan: Vlan
    ) -> ET.Element:
        interfaces = self._append_interface(
            root,
            Interface(
                name=f"{interface.name}.{vlan.vlan_id}",
                mtu=interface.mtu,
                description=vlan.name,
            ),
        )

        intf = interfaces.find(f".//interface[name='{interface.name}.{vlan.vlan_id}']")
        intf_config = intf.find("config")
        ET.SubElement(intf_config, "name").text = f"{interface.name}.{vlan.vlan_id}"
        ET.SubElement(intf_config, "enable-switchport")

        extended = ET.SubElement(
            intf,
            "extended",
            xmlns="http://www.ipinfusion.com/yang/ocnos/ipi-if-extended",
        )
        subenc = ET.SubElement(extended, "subinterface-encapsulation")
        rewrite = ET.SubElement(subenc, "rewrite")
        rewrite_config = ET.SubElement(rewrite, "config")
        ET.SubElement(rewrite_config, "vlan-action").text = "pop"
        ET.SubElement(rewrite_config, "enable-pop").text = "1tag"

        singletag = ET.SubElement(subenc, "single-tag-vlan-matches")
        singletagmatch = ET.SubElement(singletag, "single-tag-vlan-match")
        ET.SubElement(singletagmatch, "encapsulation-type").text = "dot1q"
        singletagmatch_config = ET.SubElement(singletagmatch, "config")
        ET.SubElement(singletagmatch_config, "encapsulation-type").text = "dot1q"
        ET.SubElement(singletagmatch_config, "outer-vlan-id").text = str(vlan.vlan_id)

        return root

    def render_vlan(self, interface: Interface, vlan: Vlan) -> List[str]:
        """Render LAG configuration commands for the given platform."""
        config = self._config_root()
        cfg = self._append_vlan(config, interface, vlan)
        return self._tostring(cfg)

    def render_vlan_delete(self, interface: Interface, vlan: Vlan) -> List[str]:
        """Render LAG configuration commands for the given platform."""
        config = self._config_root()
        NS_NC = "urn:ietf:params:xml:ns:netconf:base:1.0"
        NS_IF = "http://www.ipinfusion.com/yang/ocnos/ipi-interface"
        ET.register_namespace("nc", NS_NC)
        ET.register_namespace("if", NS_IF)
        interfaces = ET.SubElement(config, f"{{{NS_IF}}}interfaces")
        iface = ET.SubElement(interfaces, f"{{{NS_IF}}}interface")
        iface.set(f"{{{NS_NC}}}operation", "delete")
        ET.SubElement(
            iface, f"{{{NS_IF}}}name"
        ).text = f"{interface.name}.{vlan.vlan_id}"
        return self._tostring(config)

    def render_evpn(self, svc: EvpnService) -> List[str]:
        """Render EVPN service configuration commands for the given platform."""
        pass

    def render_evpn_delete(self, svc: EvpnService) -> List[str]:
        """Render EVPN service configuration commands for the given platform."""
        pass
