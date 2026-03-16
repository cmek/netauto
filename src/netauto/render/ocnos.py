from .base import DeviceRenderer
import xml.etree.ElementTree as ET
import xml.dom.minidom
from typing import List, Optional
from netauto.models import Interface, Lag, Vlan, Evpn, Asn, RoutingInstance


class OcnosDeviceRenderer(DeviceRenderer):
    NS = {
        "nc": "urn:ietf:params:xml:ns:netconf:base:1.0",
        "if": "http://www.ipinfusion.com/yang/ocnos/ipi-interface",
        "ifext": "http://www.ipinfusion.com/yang/ocnos/ipi-if-extended",
        "ethvpn": "http://www.ipinfusion.com/yang/ocnos/ipi-ethernet-vpn",
        "vrf": "http://www.ipinfusion.com/yang/ocnos/ipi-vrf",
        "bgpvrf": "http://www.ipinfusion.com/yang/ocnos/ipi-bgp-vrf",
        "netinst": "http://www.ipinfusion.com/yang/ocnos/ipi-network-instance",
        "ifagg": "http://www.ipinfusion.com/yang/ocnos/ipi-if-aggregate",
        "evpnmpls": "http://www.ipinfusion.com/yang/ocnos/ipi-evpn-mpls",
        "vxlan": "http://www.ipinfusion.com/yang/ocnos/ipi-vxlan",
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

        create_parent_agg: bool = False,
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
        if create_parent_agg and isinstance(interface, Lag):
            ET.SubElement(intf_config, self._tag("if", "name")).text = interface.name
        ET.SubElement(
            intf_config, self._tag("if", "description")
        ).text = interface.description
        if isinstance(interface, Lag):
            ET.SubElement(intf_config, self._tag("if", "enable-switchport"))

            # Mainly because i deleted the whole agg in a delete and needed to remake it.
            if create_parent_agg and interface.min_links > 1:
                aggregator = ET.SubElement(intf, self._tag("ifagg", "aggregator"))
                aggregator_config = ET.SubElement(
                    aggregator, self._tag("ifagg", "config")
                )
                ET.SubElement(
                    aggregator_config, self._tag("ifagg", "min-links")
                ).text = str(interface.min_links)

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

    def render_lag(
        self, lag: Lag, create_parent_agg: bool = False
    ) -> List[str]:
        """Render LAG configuration commands for the given platform."""
        port_channel_id = int(lag.name.replace("po", ""))

        config = self._config_root()
        interfaces = ET.SubElement(config, self._tag("if", "interfaces"))
        interfaces = self._append_interface(
            interfaces,
            lag,
            create_parent_agg=create_parent_agg,
            skip_interfaces=True,
        )
        for member in lag.members:
            self._append_interface(
                interfaces,
                member,
                skip_interfaces=True,
            )
            # Add extra lag stuff here for some consistency
            intf = interfaces.find(
                f"./if:interface[if:name='{member.name}']",
                self.NS,
            )
            if intf is None:
                continue
            agg = ET.SubElement(intf, self._tag("ifagg", "member-aggregation"))
            agg_config = ET.SubElement(agg, self._tag("ifagg", "config"))
            ET.SubElement(agg_config, self._tag("ifagg", "agg-type")).text = "lacp"
            ET.SubElement(agg_config, self._tag("ifagg", "aggregate-id")).text = str(
                port_channel_id
            )
            ET.SubElement(agg_config, self._tag("ifagg", "lacp-mode")).text = (
                lag.lacp_mode
            )

        return self._tostring(config)

    def render_lag_delete(self, lag: Lag) -> List[str]:
        """Render LAG configuration commands for the given platform."""
        pass

    def _append_vlan(
        self,
        root: ET.Element,
        interface: Interface,
        vlan: Vlan,
        from_azure: Optional[bool] = False,
        evpn: Optional[Evpn] = None,
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

        # Could we move this into a j2 template or something cause
        if vlan.s_tag:
            ET.SubElement(
                rewrite_config, self._tag("ifext", "vlan-action")
            ).text = "push"
            ET.SubElement(
                rewrite_config, self._tag("ifext", "push-outer-vlan-id")
            ).text = str(vlan.s_tag)
            ET.SubElement(
                rewrite_config, self._tag("ifext", "push-tpid")
            ).text = "0x8100"
        else:
            ET.SubElement(
                rewrite_config, self._tag("ifext", "vlan-action")
            ).text = "pop"
            ET.SubElement(
                rewrite_config, self._tag("ifext", "enable-pop")
            ).text = "1tag"

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

    def render_vlan(
        self, interface: Interface, vlan: Vlan, from_azure: Optional[bool] = False
    ) -> List[str]:
        """Render LAG configuration commands for the given platform."""
        config = self._config_root()
        cfg = self._append_vlan(config, interface, vlan, from_azure)
        return self._tostring(cfg)

    def _append_vxlan_tenant(self, root: ET.Element, evpn: Evpn) -> ET.Element:
        """
        <vxlan xmlns="http://www.ipinfusion.com/yang/ocnos/ipi-vxlan">
          <global>
            <config>
              <enable-vxlan/>
              <vtep-ipv4>172.18.1.1</vtep-ipv4>
            </config>
          </global>
          <vxlan-tenants>
            <vxlan-tenant>
              <vxlan-identifier>10801</vxlan-identifier>
              <config>
                <vxlan-identifier>10801</vxlan-identifier>
                <tenant-type>ingress-replication</tenant-type>
                <vrf-name>peering</vrf-name>
              </config>
            </vxlan-tenant>
        """
        vxlan = ET.SubElement(root, self._tag("vxlan", "vxlan"))
        tenants = ET.SubElement(vxlan, self._tag("vxlan", "vxlan-tenants"))
        tenant = ET.SubElement(tenants, self._tag("vxlan", "vxlan-tenant"))
        ET.SubElement(tenant, self._tag("vxlan", "vxlan-identifier")).text = str(
            evpn.vni
        )
        tenant_config = ET.SubElement(tenant, self._tag("vxlan", "config"))
        ET.SubElement(tenant_config, self._tag("vxlan", "vxlan-identifier")).text = str(
            evpn.vni
        )
        ET.SubElement(
            tenant_config, self._tag("vxlan", "tenant-type")
        ).text = "ingress-replication"
        ET.SubElement(
            tenant_config, self._tag("vxlan", "vrf-name")
        ).text = evpn.description
        return root

    def _append_vxlan_tenant_delete(self, root: ET.Element, evpn: Evpn) -> ET.Element:
        """ """
        vxlan = ET.SubElement(root, self._tag("vxlan", "vxlan"))
        tenants = ET.SubElement(vxlan, self._tag("vxlan", "vxlan-tenants"))
        tenant = ET.SubElement(tenants, self._tag("vxlan", "vxlan-tenant"))
        tenant.set(self._tag("nc", "operation"), "delete")
        ET.SubElement(tenant, self._tag("vxlan", "vxlan-identifier")).text = str(
            evpn.vni
        )
        # tenant_config = ET.SubElement(tenant, self._tag("vxlan", "config"))
        # ET.SubElement(tenant_config, self._tag("vxlan", "vxlan-identifier")).text = str(
        #    evpn.vni
        # )
        # ET.SubElement(
        #    tenant_config, self._tag("vxlan", "tenant-type")
        # ).text = "ingress-replication"
        # ET.SubElement(
        #    tenant_config, self._tag("vxlan", "vrf-name")
        # ).text = evpn.description
        return root

    # i had to make a bunch of helpers to get it going, they might be useful
    def _append_evpn_mpls_tenant(self, root: ET.Element, evpn: Evpn) -> ET.Element:
        evpn_mpls = ET.SubElement(root, self._tag("evpnmpls", "evpn-mpls"))
        global_cfg = ET.SubElement(evpn_mpls, self._tag("evpnmpls", "global"))
        global_cfg_config = ET.SubElement(global_cfg, self._tag("evpnmpls", "config"))

        if len(evpn.description) > 10:
            raise ValueError(
                f"OcNOS EVPN EVI name must be 10 chars or fewer: '{evpn.description}'"
            )

        ET.SubElement(global_cfg_config, self._tag("evpnmpls", "enable-evpn-mpls"))

        mpls_tenants = ET.SubElement(evpn_mpls, self._tag("evpnmpls", "mpls-tenants"))
        mpls_tenant = ET.SubElement(mpls_tenants, self._tag("evpnmpls", "mpls-tenant"))

        ET.SubElement(
            mpls_tenant, self._tag("evpnmpls", "tenant-identifier")
        ).text = str(evpn.vni)

        tenant_config = ET.SubElement(mpls_tenant, self._tag("evpnmpls", "config"))

        ET.SubElement(
            tenant_config, self._tag("evpnmpls", "tenant-identifier")
        ).text = str(evpn.vni)
        ET.SubElement(
            tenant_config, self._tag("evpnmpls", "vrf-name")
        ).text = evpn.description
        ET.SubElement(
            tenant_config, self._tag("evpnmpls", "tenant-description")
        ).text = evpn.description

        return root

    # this should only be needed if it didnt exist,
    # naturally in my testing it didnt exist
    def render_evpn_mpls_tenant(self, evpn: Evpn) -> str:
        config = self._config_root()
        config = self._append_evpn_mpls_tenant(config, evpn)
        return self._tostring(config)

    # mostly helpers due to exclusivity between evpn mpls and vxlan stuff
    def _append_evpn_mpls_global(self, root: ET.Element, *, delete: bool = False) -> ET.Element:
        evpn_mpls = ET.SubElement(root, self._tag("evpnmpls", "evpn-mpls"))
        global_cfg = ET.SubElement(evpn_mpls, self._tag("evpnmpls", "global"))
        global_cfg_config = ET.SubElement(global_cfg, self._tag("evpnmpls", "config"))
        enable_node = ET.SubElement(global_cfg_config, self._tag("evpnmpls", "enable-evpn-mpls"))
        if delete:
            enable_node.set(self._tag("nc", "operation"), "delete")
        return root

    # mostly helpers due to exclusivity between evpn mpls and vxlan stuff
    def render_evpn_mpls_enable(self) -> str:
        config = self._config_root()
        config = self._append_evpn_mpls_global(config, delete=False)
        return self._tostring(config)

    # mostly helpers due to exclusivity between evpn mpls and vxlan stuff
    def render_evpn_mpls_disable(self) -> str:
        config = self._config_root()
        config = self._append_evpn_mpls_global(config, delete=True)
        return self._tostring(config)

    def _append_evpn_mpls_tenant_delete(
        self, root: ET.Element, evpn: Evpn
    ) -> ET.Element:
        evpn_mpls = ET.SubElement(root, self._tag("evpnmpls", "evpn-mpls"))
        mpls_tenants = ET.SubElement(evpn_mpls, self._tag("evpnmpls", "mpls-tenants"))
        mpls_tenant = ET.SubElement(mpls_tenants, self._tag("evpnmpls", "mpls-tenant"))
        mpls_tenant.set(self._tag("nc", "operation"), "delete")

        ET.SubElement(
            mpls_tenant, self._tag("evpnmpls", "tenant-identifier")
        ).text = str(evpn.vni)

        return root

    def render_evpn_mpls_tenant_delete(self, evpn: Evpn) -> str:
        config = self._config_root()
        config = self._append_evpn_mpls_tenant_delete(config, evpn)
        return self._tostring(config)

    def _append_ethernet_vpn_vrf_service(
        self, root: ET.Element, evpn: Evpn, service_type: str = "vlan-aware-bundle"
    ) -> ET.Element:
        evpn_root = ET.SubElement(root, self._tag("ethvpn", "evpn"))
        vrfs = ET.SubElement(evpn_root, self._tag("ethvpn", "vrfs"))
        vrf = ET.SubElement(vrfs, self._tag("ethvpn", "vrf"))

        ET.SubElement(vrf, self._tag("ethvpn", "vrf-name")).text = evpn.description

        vrf_config = ET.SubElement(vrf, self._tag("ethvpn", "config"))

        ET.SubElement(
            vrf_config, self._tag("ethvpn", "vrf-name")
        ).text = evpn.description
        ET.SubElement(
            vrf_config, self._tag("ethvpn", "service-type")
        ).text = service_type

        return root

    # this should only be needed if it didnt exist,
    # naturally in my testing it didnt exist
    def render_ethernet_vpn_vrf_service(
        self, evpn: Evpn, service_type: str = "vlan-aware-bundle"
    ) -> str:
        config = self._config_root()
        config = self._append_ethernet_vpn_vrf_service(config, evpn, service_type)
        return self._tostring(config)

    def _append_ethernet_vpn_vrf_service_delete(
        self, root: ET.Element, vrf_name: str
    ) -> ET.Element:
        evpn_root = ET.SubElement(root, self._tag("ethvpn", "evpn"))
        vrfs = ET.SubElement(evpn_root, self._tag("ethvpn", "vrfs"))
        vrf = ET.SubElement(vrfs, self._tag("ethvpn", "vrf"))
        vrf.set(self._tag("nc", "operation"), "delete")
        ET.SubElement(vrf, self._tag("ethvpn", "vrf-name")).text = vrf_name
        return root

    def render_ethernet_vpn_vrf_service_delete(self, vrf_name: str) -> str:
        config = self._config_root()
        config = self._append_ethernet_vpn_vrf_service_delete(config, vrf_name)
        return self._tostring(config)

    def _append_ethernet_vpn_access(
        self,
        root: ET.Element,
        interface_name: str,
        vni: int,
        *,
        include_arp_cache_disable: bool = False,
        include_nd_cache_disable: bool = False,
    ) -> ET.Element:
        evpn_root = ET.SubElement(root, self._tag("ethvpn", "evpn"))
        interfaces = ET.SubElement(evpn_root, self._tag("ethvpn", "interfaces"))
        interface = ET.SubElement(interfaces, self._tag("ethvpn", "interface"))
        ET.SubElement(interface, self._tag("ethvpn", "name")).text = interface_name

        interface_config = ET.SubElement(interface, self._tag("ethvpn", "config"))
        ET.SubElement(
            interface_config, self._tag("ethvpn", "name")
        ).text = interface_name

        access_interfaces = ET.SubElement(
            interface, self._tag("ethvpn", "access-interfaces")
        )
        access_interface = ET.SubElement(
            access_interfaces, self._tag("ethvpn", "access-interface")
        )
        ET.SubElement(
            access_interface, self._tag("ethvpn", "access-if")
        ).text = "access-if-evpn"

        access_config = ET.SubElement(access_interface, self._tag("ethvpn", "config"))
        ET.SubElement(
            access_config, self._tag("ethvpn", "access-if")
        ).text = "access-if-evpn"
        ET.SubElement(access_config, self._tag("ethvpn", "evpn-identifier")).text = str(
            vni
        )

        if include_arp_cache_disable:
            ET.SubElement(access_config, self._tag("ethvpn", "arp-cache-disable"))
        if include_nd_cache_disable:
            ET.SubElement(access_config, self._tag("ethvpn", "nd-cache-disable"))

        return root

    # this should only be needed if it didnt exist,
    # naturally in my testing it didnt exist
    def render_ethernet_vpn_access(
        self,
        interface_name: str,
        vni: int,
        *,
        include_arp_cache_disable: bool = False,
        include_nd_cache_disable: bool = False,
    ) -> str:
        config = self._config_root()
        config = self._append_ethernet_vpn_access(
            config,
            interface_name,
            vni,
            include_arp_cache_disable=include_arp_cache_disable,
            include_nd_cache_disable=include_nd_cache_disable,
        )
        return self._tostring(config)

    def _append_ethernet_vpn_access_delete(
        self, root: ET.Element, interface_name: str
    ) -> ET.Element:
        evpn_root = ET.SubElement(root, self._tag("ethvpn", "evpn"))
        interfaces = ET.SubElement(evpn_root, self._tag("ethvpn", "interfaces"))
        interface = ET.SubElement(interfaces, self._tag("ethvpn", "interface"))
        ET.SubElement(interface, self._tag("ethvpn", "name")).text = interface_name
        interface.set(self._tag("nc", "operation"), "delete")

        #        access_interfaces = ET.SubElement(
        #            interface, self._tag("ethvpn", "access-interfaces")
        #        )
        #        access_interface = ET.SubElement(
        #            access_interfaces, self._tag("ethvpn", "access-interface")
        #        )
        #        access_interface.set(self._tag("nc", "operation"), "delete")
        #        ET.SubElement(
        #            access_interface, self._tag("ethvpn", "access-if")
        #        ).text = "access-if-evpn"
        return root

    def render_ethernet_vpn_access_delete(self, interface_name: str) -> str:
        config = self._config_root()
        config = self._append_ethernet_vpn_access_delete(config, interface_name)
        return self._tostring(config)

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

    # mostly helpers due to exclusivity between evpn mpls and vxlan stuff
    def _append_vxlan_global(self, root: ET.Element, *, delete: bool = False) -> ET.Element:
        vxlan = ET.SubElement(root, self._tag("vxlan", "vxlan"))
        global_cfg = ET.SubElement(vxlan, self._tag("vxlan", "global"))
        config = ET.SubElement(global_cfg, self._tag("vxlan", "config"))
        enable_node = ET.SubElement(config, self._tag("vxlan", "enable-vxlan"))
        if delete:
            enable_node.set(self._tag("nc", "operation"), "delete")
        return root

    # mostly helpers due to exclusivity between evpn mpls and vxlan stuff
    def render_vxlan_enable(self) -> str:
        config = self._config_root()
        config = self._append_vxlan_global(config, delete=False)
        return self._tostring(config)

    # mostly helpers due to exclusivity between evpn mpls and vxlan stuff
    def render_vxlan_disable(self) -> str:
        config = self._config_root()
        config = self._append_vxlan_global(config, delete=True)
        return self._tostring(config)

    def _append_vrf(
        self, root: ET.Element, asn: Asn, vrf: RoutingInstance
    ) -> ET.Element:
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
        ).text = vrf.instance_name
        ET.SubElement(
            network_instance, self._tag("netinst", "instance-type")
        ).text = vrf.instance_type

        # <config>
        #  <instance-name>so12345</instance-name>
        #  <instance-type>mac-vrf</instance-type>
        # </config>
        config = ET.SubElement(network_instance, self._tag("netinst", "config"))
        ET.SubElement(
            config, self._tag("netinst", "instance-name")
        ).text = vrf.instance_name
        ET.SubElement(
            config, self._tag("netinst", "instance-type")
        ).text = vrf.instance_type

        #        <vrf xmlns="http://www.ipinfusion.com/yang/ocnos/ipi-vrf">
        #          <config>
        #            <vrf-name>so12345</vrf-name>
        #          </config>
        vrf_el = ET.SubElement(network_instance, self._tag("vrf", "vrf"))
        vrf_config = ET.SubElement(vrf_el, self._tag("vrf", "config"))
        ET.SubElement(vrf_config, self._tag("vrf", "vrf-name")).text = vrf.instance_name

        #          <bgp-vrf xmlns="http://www.ipinfusion.com/yang/ocnos/ipi-bgp-vrf">
        #            <config>
        #              <rd-string>65511:99</rd-string>
        #            </config>
        bgp_vrf = ET.SubElement(vrf_el, self._tag("bgpvrf", "bgp-vrf"))
        bgp_vrf_config = ET.SubElement(bgp_vrf, self._tag("bgpvrf", "config"))
        ET.SubElement(
            bgp_vrf_config, self._tag("bgpvrf", "rd-string")
        ).text = f"{vrf.rd}"

        #             <route-targets>
        #               <route-target>
        #                 <rt-rd-string>37186:99</rt-rd-string>
        #                 <config>
        #                   <rt-rd-string>37186:99</rt-rd-string>
        #                   <direction>import export</direction>
        # route_target = ET.SubElement(bgp_vrf, self._tag("bgpvrf", "route-target"))
        route_targets = ET.SubElement(bgp_vrf, self._tag("bgpvrf", "route-targets"))
        route_target = ET.SubElement(route_targets, self._tag("bgpvrf", "route-target"))
        ET.SubElement(
            route_target, self._tag("bgpvrf", "rt-rd-string")
        ).text = f"{vrf.rt_rd}"
        rt_config = ET.SubElement(route_target, self._tag("bgpvrf", "config"))
        ET.SubElement(
            rt_config, self._tag("bgpvrf", "rt-rd-string")
        ).text = f"{vrf.rt_rd}"
        ET.SubElement(
            rt_config, self._tag("bgpvrf", "direction")
        ).text = "import export"

        return root

    def render_evpn(
        self, interface: Interface, evpn: Evpn, from_azure: Optional[bool] = None
    ) -> str:  # ty is really unhappy about this we should look at a signature clean up once functions verified
        """Render EVPN service configuration commands for the given platform."""
        if from_azure:
            if evpn.vlan.s_tag is None:
                raise ValueError("Azure rendering requires vlan.s_tag")

            root = self._config_root()
            is_cni = interface.arp_cache is False or interface.nd_cache is False

            # will this always evaluate true\/
            if is_cni:
                interface_xml = self._tostring(
                    self._append_azure_cni_interface(
                        self._config_root(), interface, evpn
                    )
                )
            else:
                interface_xml = self._tostring(
                    self._append_azure_customer_interface(
                        self._config_root(), interface, evpn
                    )
                )

            azure_xml = [
                interface_xml,
                self.render_evpn_mpls_tenant(evpn),
                self.render_ethernet_vpn_vrf_service(evpn),
            ]

            for xml in azure_xml:
                parsed = ET.fromstring(xml)
                for child in list(parsed):
                    root.append(child)

            return self._tostring(root)

        config = self._config_root()
        # config = self._append_vrf(config, evpn)
        config = self._append_vlan(
            config,
            interface,
            evpn.vlan,
            from_azure=from_azure,
            evpn=evpn,
        )
        config = self._append_ethernet_vpn_access(
            config, f"{interface.name}.{evpn.vlan.vlan_id}", evpn.vni
        )
        config = self._append_vxlan_tenant(config, evpn)

        return self._tostring(config)

    def _append_azure_cni_interface(
        self, root: ET.Element, interface: Interface, evpn: Evpn
    ) -> ET.Element:
        if evpn.vlan.s_tag is None:
            raise ValueError("Azure CNI rendering requires vlan.s_tag")

        root = self._append_interface(
            root,
            Interface(
                name=f"{interface.name}.{evpn.vlan.s_tag}",
                mtu=interface.mtu,
                description=evpn.vlan.name,
            ),
        )

        intf = root.find(
            f".//if:interface[if:name='{interface.name}.{evpn.vlan.s_tag}']", self.NS
        )
        intf_config = intf.find(self._tag("if", "config"))
        ET.SubElement(
            intf_config, self._tag("if", "name")
        ).text = f"{interface.name}.{evpn.vlan.s_tag}"
        ET.SubElement(intf_config, self._tag("if", "enable-switchport"))

        extended = ET.SubElement(intf, self._tag("ifext", "extended"))
        subenc = ET.SubElement(
            extended, self._tag("ifext", "subinterface-encapsulation")
        )
        rewrite = ET.SubElement(subenc, self._tag("ifext", "rewrite"))
        rewrite_config = ET.SubElement(rewrite, self._tag("ifext", "config"))
        ET.SubElement(rewrite_config, self._tag("ifext", "vlan-action")).text = "pop"
        ET.SubElement(rewrite_config, self._tag("ifext", "enable-pop")).text = "1tag"

        single_tag = ET.SubElement(
            subenc, self._tag("ifext", "single-tag-vlan-matches")
        )
        single_tag_match = ET.SubElement(
            single_tag, self._tag("ifext", "single-tag-vlan-match")
        )
        ET.SubElement(
            single_tag_match, self._tag("ifext", "encapsulation-type")
        ).text = "dot1q"
        single_tag_match_config = ET.SubElement(
            single_tag_match, self._tag("ifext", "config")
        )
        ET.SubElement(
            single_tag_match_config, self._tag("ifext", "encapsulation-type")
        ).text = "dot1q"
        ET.SubElement(
            single_tag_match_config, self._tag("ifext", "outer-vlan-id")
        ).text = str(evpn.vlan.s_tag)

        return root

    def _append_azure_customer_interface(
        self,
        root: ET.Element,
        interface: Interface,
        evpn: Evpn,
        *,
        push_tpid: str = "0x8100",
    ) -> ET.Element:
        # just validating
        if evpn.vlan.s_tag is None:
            raise ValueError("Azure customer rendering requires vlan.s_tag")

        root = self._append_interface(
            root,
            Interface(
                name=f"{interface.name}.{evpn.vlan.vlan_id}",
                mtu=interface.mtu,
                description=evpn.vlan.name,
            ),
        )

        intf = root.find(
            f".//if:interface[if:name='{interface.name}.{evpn.vlan.vlan_id}']", self.NS
        )
        intf_config = intf.find(self._tag("if", "config"))
        ET.SubElement(
            intf_config, self._tag("if", "name")
        ).text = f"{interface.name}.{evpn.vlan.vlan_id}"
        ET.SubElement(intf_config, self._tag("if", "enable-switchport"))

        extended = ET.SubElement(intf, self._tag("ifext", "extended"))
        subenc = ET.SubElement(
            extended, self._tag("ifext", "subinterface-encapsulation")
        )
        rewrite = ET.SubElement(subenc, self._tag("ifext", "rewrite"))
        rewrite_config = ET.SubElement(rewrite, self._tag("ifext", "config"))
        ET.SubElement(rewrite_config, self._tag("ifext", "vlan-action")).text = "push"
        ET.SubElement(
            rewrite_config, self._tag("ifext", "push-outer-vlan-id")
        ).text = str(evpn.vlan.s_tag)
        ET.SubElement(rewrite_config, self._tag("ifext", "push-tpid")).text = push_tpid

        single_tag = ET.SubElement(
            subenc, self._tag("ifext", "single-tag-vlan-matches")
        )
        single_tag_match = ET.SubElement(
            single_tag, self._tag("ifext", "single-tag-vlan-match")
        )
        ET.SubElement(
            single_tag_match, self._tag("ifext", "encapsulation-type")
        ).text = "dot1q"
        single_tag_match_config = ET.SubElement(
            single_tag_match, self._tag("ifext", "config")
        )
        ET.SubElement(
            single_tag_match_config, self._tag("ifext", "encapsulation-type")
        ).text = "dot1q"
        ET.SubElement(
            single_tag_match_config, self._tag("ifext", "outer-vlan-id")
        ).text = str(evpn.vlan.vlan_id)

        return root

    def _append_vrf_delete(
        self, root: ET.Element, asn: Asn, vrf: RoutingInstance
    ) -> ET.Element:
        network_instances = ET.SubElement(
            root, self._tag("netinst", "network-instances")
        )
        network_instance = ET.SubElement(
            network_instances, self._tag("netinst", "network-instance")
        )
        network_instance.set(self._tag("nc", "operation"), "delete")
        ET.SubElement(
            network_instance, self._tag("netinst", "instance-name")
        ).text = vrf.instance_name
        ET.SubElement(
            network_instance, self._tag("netinst", "instance-type")
        ).text = "mac-vrf"

        #        vrf_el = ET.SubElement(network_instance, self._tag("vrf", "vrf"))
        #        vrf_el.set(self._tag("nc", "operation"), "delete")
        #        vrf_config = ET.SubElement(vrf_el, self._tag("vrf", "config"))
        #        ET.SubElement(vrf_config, self._tag("vrf", "vrf-name")).text = vrf.instance_name
        #
        #        bgp_vrf = ET.SubElement(vrf_el, self._tag("bgpvrf", "bgp-vrf"))
        #        bgp_vrf.set(self._tag("nc", "operation"), "delete")
        #        bgp_vrf_config = ET.SubElement(bgp_vrf, self._tag("bgpvrf", "config"))
        #        ET.SubElement(
        #            bgp_vrf_config, self._tag("bgpvrf", "rd-string")
        #        ).text = f"{vrf.rd}"
        #
        #        # route_target = ET.SubElement(bgp_vrf, self._tag("bgpvrf", "route-target"))
        #        route_targets = ET.SubElement(bgp_vrf, self._tag("bgpvrf", "route-targets"))
        #        route_target = ET.SubElement(route_targets, self._tag("bgpvrf", "route-target"))
        #        route_target.set(self._tag("nc", "operation"), "delete")
        #        ET.SubElement(
        #            route_target, self._tag("bgpvrf", "rt-rd-string")
        #        ).text = f"{vrf.rt_rd}"
        #        rt_config = ET.SubElement(route_target, self._tag("bgpvrf", "config"))
        #        ET.SubElement(
        #            rt_config, self._tag("bgpvrf", "rt-rd-string")
        #        ).text = f"{vrf.rt_rd}"
        #        ET.SubElement(
        #            rt_config, self._tag("bgpvrf", "direction")
        #        ).text = "import export"

        return root

    def render_evpn_delete(
        self, interface: Interface, evpn: Evpn, from_azure: Optional[bool] = None
    ) -> List[str]:
        """Render EVPN service configuration commands for the given platform."""
        # Azure needs a bunch more removed, we should probablyupdate the base signatures
        if from_azure:
            if evpn.vlan.s_tag is None:
                raise ValueError("Azure delete rendering requires vlan.s_tag")

            root = self._config_root()
            is_cni = interface.arp_cache is False or interface.nd_cache is False
            if is_cni:
                interface_name = f"{interface.name}.{evpn.vlan.s_tag}"
                vlan_for_delete = Vlan(
                    vlan_id=evpn.vlan.s_tag,
                    name=evpn.vlan.name,
                    s_tag=None,
                )
            else:
                interface_name = f"{interface.name}.{evpn.vlan.vlan_id}"
                vlan_for_delete = evpn.vlan

            azure_delete_xml = [
                self.render_ethernet_vpn_access_delete(interface_name),
                self.render_evpn_mpls_tenant_delete(evpn),
                self.render_ethernet_vpn_vrf_service_delete(evpn.description),
                # self._tostring(self._append_vrf_delete(self._config_root(), evpn)),
                self.render_vlan_delete(interface, vlan_for_delete),
            ]
            for xml in azure_delete_xml:
                parsed = ET.fromstring(xml)
                for child in list(parsed):
                    root.append(child)
            return self._tostring(root)

        config = self._config_root()
        # config = self._append_vrf_delete(config, evpn)
        config = self._append_vlan_delete(config, interface, evpn.vlan)
        config = self._append_ethernet_vpn_access_delete(
            config, f"{interface.name}.{evpn.vlan.vlan_id}"
        )
        config = self._append_vxlan_tenant_delete(config, evpn)

        return self._tostring(config)

    def render_routing_instance(self, asn: Asn, vrf: RoutingInstance) -> List[str]:
        """Render routing instance configuration commands for the given platform."""

        config = self._config_root()
        config = self._append_vrf(config, asn, vrf)

        return self._tostring(config)

    def render_routing_instance_delete(
        self, asn: Asn, vrf: RoutingInstance
    ) -> List[str]:
        """Render routing instance configuration commands for the given platform."""

        config = self._config_root()
        config = self._append_vrf_delete(config, asn, vrf)

        return self._tostring(config)
