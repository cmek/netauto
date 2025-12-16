from .base import DeviceRenderer
import xml.etree.ElementTree as ET
import xml.dom.minidom
from typing import List, Dict, Any, Optional
from netauto.models import Interface, Lag, Vlan, Evpn


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

    def _append_vlan_delete(
        self, config: ET.Element, interface: Interface, vlan: Vlan
    ) -> ET.Element:
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

        return config

    def render_vlan_delete(self, interface: Interface, vlan: Vlan) -> List[str]:
        """Render LAG configuration commands for the given platform."""
        config = self._config_root()
        config = self._append_vlan_delete(config, interface, vlan)

        return self._tostring(config)

    def _append_vrf(self, root: ET.Element, evpn: Evpn) -> ET.Element:
        NS_NC = "urn:ietf:params:xml:ns:netconf:base:1.0"
        NS_IF = "http://www.ipinfusion.com/yang/ocnos/ipi-interface"
        NS_VRF = "http://www.ipinfusion.com/yang/ocnos/ipi-vrf"
        NS_BGPVRF = "http://www.ipinfusion.com/yang/ocnos/ipi-bgp-vrf"
        NS_NETINST = "http://www.ipinfusion.com/yang/ocnos/ipi-network-instance"
        ET.register_namespace("nc", NS_NC)
        ET.register_namespace("if", NS_IF)
        ET.register_namespace("vrf", NS_VRF)
        ET.register_namespace("bgpvrf", NS_BGPVRF)
        ET.register_namespace("netinst", NS_NETINST)

        #      <network-instance>
        # <instance-name>so12345</instance-name>
        # <instance-type>mac-vrf</instance-type>

        network_instances = ET.SubElement(root, f"{{{NS_NETINST}}}network-instances")
        network_instance = ET.SubElement(
            network_instances, f"{{{NS_NETINST}}}network-instance"
        )
        ET.SubElement(
            network_instance, f"{{{NS_NETINST}}}instance-name"
        ).text = evpn.description
        ET.SubElement(
            network_instance, f"{{{NS_NETINST}}}instance-type"
        ).text = "mac-vrf"

        # <config>
        #  <instance-name>so12345</instance-name>
        #  <instance-type>mac-vrf</instance-type>
        # </config>

        config = ET.SubElement(network_instance, f"{{{NS_NETINST}}}config")
        ET.SubElement(config, f"{{{NS_NETINST}}}instance-name").text = evpn.description
        ET.SubElement(config, f"{{{NS_NETINST}}}instance-type").text = "mac-vrf"
        #        <vrf xmlns="http://www.ipinfusion.com/yang/ocnos/ipi-vrf">
        #          <config>
        #            <vrf-name>so12345</vrf-name>
        #          </config>

        vrf = ET.SubElement(network_instance, f"{{{NS_VRF}}}vrf")
        vrf_config = ET.SubElement(vrf, f"{{{NS_VRF}}}config")
        ET.SubElement(vrf_config, f"{{{NS_VRF}}}vrf-name").text = evpn.description

        #          <bgp-vrf xmlns="http://www.ipinfusion.com/yang/ocnos/ipi-bgp-vrf">
        #            <config>
        #              <rd-string>65511:99</rd-string>
        #            </config>

        bgp_vrf = ET.SubElement(vrf, f"{{{NS_BGPVRF}}}bgp-vrf")
        bgp_vrf_config = ET.SubElement(bgp_vrf, f"{{{NS_BGPVRF}}}config")
        ET.SubElement(
            bgp_vrf_config, f"{{{NS_BGPVRF}}}rd-string"
        ).text = f"{evpn.asn}:{evpn.vni}"

        #             <route-targets>
        #               <route-target>
        #                 <rt-rd-string>37186:99</rt-rd-string>
        #                 <config>
        #                   <rt-rd-string>37186:99</rt-rd-string>
        #                   <direction>import export</direction>
        route_targets = ET.SubElement(bgp_vrf, f"{{{NS_BGPVRF}}}route-targets")
        route_target = ET.SubElement(route_targets, f"{{{NS_BGPVRF}}}route-target")
        ET.SubElement(
            route_target, f"{{{NS_BGPVRF}}}rt-rd-string"
        ).text = f"{evpn.asn}:{evpn.vni}"
        rt_config = ET.SubElement(route_target, f"{{{NS_BGPVRF}}}config")
        ET.SubElement(
            rt_config, f"{{{NS_BGPVRF}}}rt-rd-string"
        ).text = f"{evpn.asn}:{evpn.vni}"
        ET.SubElement(rt_config, f"{{{NS_BGPVRF}}}direction").text = "import export"

        return root

    def render_evpn(self, interface: Interface, evpn: Evpn) -> List[str]:
        """Render EVPN service configuration commands for the given platform."""
        config = self._config_root()
        config = self._append_vrf(config, evpn)
        config = self._append_vlan(config, interface, evpn.vlan)

        return self._tostring(config)

    def _append_vrf_delete(self, root: ET.Element, evpn: Evpn) -> ET.Element:
        NS_NC = "urn:ietf:params:xml:ns:netconf:base:1.0"
        NS_IF = "http://www.ipinfusion.com/yang/ocnos/ipi-interface"
        NS_VRF = "http://www.ipinfusion.com/yang/ocnos/ipi-vrf"
        NS_BGPVRF = "http://www.ipinfusion.com/yang/ocnos/ipi-bgp-vrf"
        NS_NETINST = "http://www.ipinfusion.com/yang/ocnos/ipi-network-instance"
        ET.register_namespace("nc", NS_NC)
        ET.register_namespace("if", NS_IF)
        ET.register_namespace("vrf", NS_VRF)
        ET.register_namespace("bgpvrf", NS_BGPVRF)
        ET.register_namespace("netinst", NS_NETINST)

        network_instances = ET.SubElement(root, f"{{{NS_NETINST}}}network-instances")
        network_instance = ET.SubElement(
            network_instances, f"{{{NS_NETINST}}}network-instance"
        )
        network_instance.set(f"{{{NS_NC}}}operation", "delete")
        ET.SubElement(
            network_instance, f"{{{NS_NETINST}}}instance-name"
        ).text = evpn.description
        ET.SubElement(
            network_instance, f"{{{NS_NETINST}}}instance-type"
        ).text = "mac-vrf"

        # <config>
        #  <instance-name>so12345</instance-name>
        #  <instance-type>mac-vrf</instance-type>
        # </config>

        #        config = ET.SubElement(network_instance, f"{{{NS_NETINST}}}config")
        #        ET.SubElement(config, f"{{{NS_NETINST}}}instance-name").text = evpn.description
        #        ET.SubElement(config, f"{{{NS_NETINST}}}instance-type").text = "mac-vrf"
        ##        <vrf xmlns="http://www.ipinfusion.com/yang/ocnos/ipi-vrf">
        ##          <config>
        #            <vrf-name>so12345</vrf-name>
        #          </config>

        vrf = ET.SubElement(network_instance, f"{{{NS_VRF}}}vrf")
        vrf.set(f"{{{NS_NC}}}operation", "delete")
        vrf_config = ET.SubElement(vrf, f"{{{NS_VRF}}}config")
        ET.SubElement(vrf_config, f"{{{NS_VRF}}}vrf-name").text = evpn.description

        #          <bgp-vrf xmlns="http://www.ipinfusion.com/yang/ocnos/ipi-bgp-vrf">
        #            <config>
        #              <rd-string>65511:99</rd-string>
        #            </config>

        bgp_vrf = ET.SubElement(vrf, f"{{{NS_BGPVRF}}}bgp-vrf")
        bgp_vrf.set(f"{{{NS_NC}}}operation", "delete")
        bgp_vrf_config = ET.SubElement(bgp_vrf, f"{{{NS_BGPVRF}}}config")
        ET.SubElement(
            bgp_vrf_config, f"{{{NS_BGPVRF}}}rd-string"
        ).text = f"{evpn.asn}:{evpn.vni}"

        #             <route-targets>
        #               <route-target>
        #                 <rt-rd-string>37186:99</rt-rd-string>
        #                 <config>
        #                   <rt-rd-string>37186:99</rt-rd-string>
        #                   <direction>import export</direction>
        route_targets = ET.SubElement(bgp_vrf, f"{{{NS_BGPVRF}}}route-targets")
        route_target = ET.SubElement(route_targets, f"{{{NS_BGPVRF}}}route-target")
        route_target.set(f"{{{NS_NC}}}operation", "delete")
        ET.SubElement(
            route_target, f"{{{NS_BGPVRF}}}rt-rd-string"
        ).text = f"{evpn.asn}:{evpn.vni}"
        rt_config = ET.SubElement(route_target, f"{{{NS_BGPVRF}}}config")
        ET.SubElement(
            rt_config, f"{{{NS_BGPVRF}}}rt-rd-string"
        ).text = f"{evpn.asn}:{evpn.vni}"
        ET.SubElement(rt_config, f"{{{NS_BGPVRF}}}direction").text = "import export"

        return root

    def render_evpn_delete(self, interface: Interface, evpn: Evpn) -> List[str]:
        """Render EVPN service configuration commands for the given platform."""
        config = self._config_root()
        config = self._append_vrf_delete(config, evpn)
        config = self._append_vlan_delete(config, interface, evpn.vlan)

        return self._tostring(config)
