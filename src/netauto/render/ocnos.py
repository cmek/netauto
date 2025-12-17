from .base import DeviceRenderer
import xml.etree.ElementTree as ET
import xml.dom.minidom
from typing import List
from netauto.models import Interface, Lag, Vlan, Evpn


class OcnosDeviceRenderer(DeviceRenderer):
    NS = {
        "nc": "urn:ietf:params:xml:ns:netconf:base:1.0",
        "if": "http://www.ipinfusion.com/yang/ocnos/ipi-interface",
        "ifext": "http://www.ipinfusion.com/yang/ocnos/ipi-if-extended",
        "vrf": "http://www.ipinfusion.com/yang/ocnos/ipi-vrf",
        "bgpvrf": "http://www.ipinfusion.com/yang/ocnos/ipi-bgp-vrf",
        "netinst": "http://www.ipinfusion.com/yang/ocnos/ipi-network-instance",
        "ifagg": "http://www.ipinfusion.com/yang/ocnos/ipi-if-aggregate",
    }

    def __init__(self):
        super().__init__()
        for prefix, uri in self.NS.items():
            ET.register_namespace(prefix, uri)

    def _tag(self, prefix: str, tag: str) -> str:
        """Helper to create namespaced tags."""
        return f"{{{self.NS[prefix]}}}{tag}"

    def _tostring(self, element: ET.Element) -> str:
        """Converts an Element to a string."""
        raw = ET.tostring(element, encoding="unicode")
        # this is not the most efficient approach ;)
        parsed = xml.dom.minidom.parseString(raw)
        return parsed.toprettyxml(indent="  ")

    def _config_root(self) -> ET.Element:
        """Create the root <config> element for OcNOS XML configuration."""
        return ET.Element("config")

        #    def _append_interface_system_mac(self, interface: Lag) -> ET.Element:
        # ET.SubElement(
        #    intf_config, self._tag("if", "system-mac")
        # ).text = system_mac

    def _append_interface(
        self,
        root: ET.Element,
        interface: Interface | Lag,
        port_channel_id: int | None = None,
        lacp_mode: str | None = None,
        skip_interfaces=False,
    ) -> ET.Element:
        if not skip_interfaces:
            interfaces = ET.SubElement(root, self._tag("if", "interfaces"))
            intf = ET.SubElement(interfaces, self._tag("if", "interface"))
        else:
            intf = ET.SubElement(root, self._tag("if", "interface"))
        ET.SubElement(intf, self._tag("if", "name")).text = interface.name
        intf_config = ET.SubElement(intf, self._tag("if", "config"))
        ET.SubElement(intf_config, self._tag("if", "mtu")).text = str(interface.mtu)
        ET.SubElement(
            intf_config, self._tag("if", "description")
        ).text = interface.description
        if isinstance(interface, Lag):
            ET.SubElement(intf_config, self._tag("if", "enable-switchport"))

        if port_channel_id is not None:
            agg = ET.SubElement(intf, self._tag("ifagg", "member-aggregation"))
            agg_config = ET.SubElement(agg, self._tag("ifagg", "config"))
            ET.SubElement(agg_config, self._tag("ifagg", "agg-type")).text = "lacp"
            ET.SubElement(agg_config, self._tag("ifagg", "aggregate-id")).text = str(
                port_channel_id
            )
            ET.SubElement(agg_config, self._tag("ifagg", "lacp-mode")).text = lacp_mode

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
        port_channel_id = int(lag.name.replace("po", ""))

        config = self._config_root()
        interfaces = ET.SubElement(config, self._tag("if", "interfaces"))
        interfaces = self._append_interface(interfaces, lag, skip_interfaces=True)
        for member in lag.members:
            interfaces = self._append_interface(
                interfaces,
                member,
                port_channel_id=port_channel_id,
                lacp_mode=lag.lacp_mode,
                skip_interfaces=True,
            )

        return self._tostring(config)

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

        intf = interfaces.find(
            f".//if:interface[if:name='{interface.name}.{vlan.vlan_id}']", self.NS
        )
        intf_config = intf.find(self._tag("if", "config"))
        ET.SubElement(
            intf_config, self._tag("if", "name")
        ).text = f"{interface.name}.{vlan.vlan_id}"
        ET.SubElement(intf_config, self._tag("if", "enable-switchport"))

        extended = ET.SubElement(intf, self._tag("ifext", "extended"))
        subenc = ET.SubElement(
            extended, self._tag("ifext", "subinterface-encapsulation")
        )
        rewrite = ET.SubElement(subenc, self._tag("ifext", "rewrite"))
        rewrite_config = ET.SubElement(rewrite, self._tag("ifext", "config"))
        ET.SubElement(rewrite_config, self._tag("ifext", "vlan-action")).text = "pop"
        ET.SubElement(rewrite_config, self._tag("ifext", "enable-pop")).text = "1tag"

        singletag = ET.SubElement(subenc, self._tag("ifext", "single-tag-vlan-matches"))
        singletagmatch = ET.SubElement(
            singletag, self._tag("ifext", "single-tag-vlan-match")
        )
        ET.SubElement(
            singletagmatch, self._tag("ifext", "encapsulation-type")
        ).text = "dot1q"
        singletagmatch_config = ET.SubElement(
            singletagmatch, self._tag("ifext", "config")
        )
        ET.SubElement(
            singletagmatch_config, self._tag("ifext", "encapsulation-type")
        ).text = "dot1q"
        ET.SubElement(
            singletagmatch_config, self._tag("ifext", "outer-vlan-id")
        ).text = str(vlan.vlan_id)

        return root

    def render_vlan(self, interface: Interface, vlan: Vlan) -> List[str]:
        """Render LAG configuration commands for the given platform."""
        config = self._config_root()
        cfg = self._append_vlan(config, interface, vlan)
        return self._tostring(cfg)

    def _append_vlan_delete(
        self, config: ET.Element, interface: Interface, vlan: Vlan
    ) -> ET.Element:
        interfaces = ET.SubElement(config, self._tag("if", "interfaces"))
        iface = ET.SubElement(interfaces, self._tag("if", "interface"))
        iface.set(self._tag("nc", "operation"), "delete")
        ET.SubElement(
            iface,
            self._tag("if", "name"),
        ).text = f"{interface.name}.{vlan.vlan_id}"
        return config

    def render_vlan_delete(self, interface: Interface, vlan: Vlan) -> List[str]:
        """Render LAG configuration commands for the given platform."""
        config = self._config_root()
        config = self._append_vlan_delete(config, interface, vlan)

        return self._tostring(config)

    def _append_vrf(self, root: ET.Element, evpn: Evpn) -> ET.Element:
        #      <network-instance>
        # <instance-name>so12345</instance-name>
        # <instance-type>mac-vrf</instance-type>

        network_instances = ET.SubElement(
            root, self._tag("netinst", "network-instances")
        )
        network_instance = ET.SubElement(
            network_instances, self._tag("netinst", "network-instance")
        )
        ET.SubElement(
            network_instance, self._tag("netinst", "instance-name")
        ).text = evpn.description
        ET.SubElement(
            network_instance, self._tag("netinst", "instance-type")
        ).text = "mac-vrf"

        # <config>
        #  <instance-name>so12345</instance-name>
        #  <instance-type>mac-vrf</instance-type>
        # </config>
        config = ET.SubElement(network_instance, self._tag("netinst", "config"))
        ET.SubElement(
            config, self._tag("netinst", "instance-name")
        ).text = evpn.description
        ET.SubElement(config, self._tag("netinst", "instance-type")).text = "mac-vrf"

        #        <vrf xmlns="http://www.ipinfusion.com/yang/ocnos/ipi-vrf">
        #          <config>
        #            <vrf-name>so12345</vrf-name>
        #          </config>
        vrf = ET.SubElement(network_instance, self._tag("vrf", "vrf"))
        vrf_config = ET.SubElement(vrf, self._tag("vrf", "config"))
        ET.SubElement(vrf_config, self._tag("vrf", "vrf-name")).text = evpn.description

        #          <bgp-vrf xmlns="http://www.ipinfusion.com/yang/ocnos/ipi-bgp-vrf">
        #            <config>
        #              <rd-string>65511:99</rd-string>
        #            </config>
        bgp_vrf = ET.SubElement(vrf, self._tag("bgpvrf", "bgp-vrf"))
        bgp_vrf_config = ET.SubElement(bgp_vrf, self._tag("bgpvrf", "config"))
        ET.SubElement(
            bgp_vrf_config, self._tag("bgpvrf", "rd-string")
        ).text = f"{evpn.asn}:{evpn.vni}"

        #             <route-targets>
        #               <route-target>
        #                 <rt-rd-string>37186:99</rt-rd-string>
        #                 <config>
        #                   <rt-rd-string>37186:99</rt-rd-string>
        #                   <direction>import export</direction>
        route_targets = ET.SubElement(bgp_vrf, self._tag("bgpvrf", "route-targets"))
        route_target = ET.SubElement(route_targets, self._tag("bgpvrf", "route-target"))
        ET.SubElement(
            route_target, self._tag("bgpvrf", "rt-rd-string")
        ).text = f"{evpn.asn}:{evpn.vni}"
        rt_config = ET.SubElement(route_target, self._tag("bgpvrf", "config"))
        ET.SubElement(
            rt_config, self._tag("bgpvrf", "rt-rd-string")
        ).text = f"{evpn.asn}:{evpn.vni}"
        ET.SubElement(
            rt_config, self._tag("bgpvrf", "direction")
        ).text = "import export"

        return root

    def render_evpn(self, interface: Interface, evpn: Evpn) -> List[str]:
        """Render EVPN service configuration commands for the given platform."""
        config = self._config_root()
        config = self._append_vrf(config, evpn)
        config = self._append_vlan(config, interface, evpn.vlan)

        return self._tostring(config)

    def _append_vrf_delete(self, root: ET.Element, evpn: Evpn) -> ET.Element:
        network_instances = ET.SubElement(
            root, self._tag("netinst", "network-instances")
        )
        network_instance = ET.SubElement(
            network_instances, self._tag("netinst", "network-instance")
        )
        network_instance.set(self._tag("nc", "operation"), "delete")
        ET.SubElement(
            network_instance, self._tag("netinst", "instance-name")
        ).text = evpn.description
        ET.SubElement(
            network_instance, self._tag("netinst", "instance-type")
        ).text = "mac-vrf"

        vrf = ET.SubElement(network_instance, self._tag("vrf", "vrf"))
        vrf.set(self._tag("nc", "operation"), "delete")
        vrf_config = ET.SubElement(vrf, self._tag("vrf", "config"))
        ET.SubElement(vrf_config, self._tag("vrf", "vrf-name")).text = evpn.description

        bgp_vrf = ET.SubElement(vrf, self._tag("bgpvrf", "bgp-vrf"))
        bgp_vrf.set(self._tag("nc", "operation"), "delete")
        bgp_vrf_config = ET.SubElement(bgp_vrf, self._tag("bgpvrf", "config"))
        ET.SubElement(
            bgp_vrf_config, self._tag("bgpvrf", "rd-string")
        ).text = f"{evpn.asn}:{evpn.vni}"

        route_targets = ET.SubElement(bgp_vrf, self._tag("bgpvrf", "route-targets"))
        route_target = ET.SubElement(route_targets, self._tag("bgpvrf", "route-target"))
        route_target.set(self._tag("nc", "operation"), "delete")
        ET.SubElement(
            route_target, self._tag("bgpvrf", "rt-rd-string")
        ).text = f"{evpn.asn}:{evpn.vni}"
        rt_config = ET.SubElement(route_target, self._tag("bgpvrf", "config"))
        ET.SubElement(
            rt_config, self._tag("bgpvrf", "rt-rd-string")
        ).text = f"{evpn.asn}:{evpn.vni}"
        ET.SubElement(
            rt_config, self._tag("bgpvrf", "direction")
        ).text = "import export"

        return root

    def render_evpn_delete(self, interface: Interface, evpn: Evpn) -> List[str]:
        """Render EVPN service configuration commands for the given platform."""
        config = self._config_root()
        config = self._append_vrf_delete(config, evpn)
        config = self._append_vlan_delete(config, interface, evpn.vlan)

        return self._tostring(config)
