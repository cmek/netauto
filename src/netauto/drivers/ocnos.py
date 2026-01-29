from .base import DeviceDriver
# from scrapli_netconf.driver import NetconfDriver as ScrapliNetconfDriver
import re
from netauto.models import Interface, Vlan, Lag, Evpn
from typing import List, Dict
import difflib

import xml.etree.ElementTree as ET
from lxml import etree
from netauto.render import OcnosDeviceRenderer
import logging
from ncclient import manager
from ncclient.manager import Manager
from pathlib import Path  # Remove me once testing is done
from ncclient.operations.retrieve import GetReply
from ncclient.operations import RPCError

logger = logging.getLogger(__name__)

OCNOS_NS = {
    "if": "http://www.ipinfusion.com/yang/ocnos/ipi-interface",
    "ife": "http://www.ipinfusion.com/yang/ocnos/ipi-if-extended",
    "ife2": "http://www.ipinfusion.com/yang/ocnos/ipi-if-ethernet",
    "ifagg": "http://www.ipinfusion.com/yang/ocnos/ipi-if-aggregate",
    "nc": "urn:ietf:params:xml:ns:netconf:base:1.0",
    "vxlan": "http://www.ipinfusion.com/yang/ocnos/ipi-vxlan",
}

def pretty_xml(xml_str: str) -> str:
    node = etree.fromstring(xml_str.encode("utf-8"))
    return etree.tostring(node, pretty_print=True, encoding="unicode")


class OcnosDriver(DeviceDriver):
    def __init__(self, host: str, user: str, password: str) -> None:
        self.connection_data = {
            "host": host,
            "port": 830,
            "username": user,
            "password": password,
            "hostkey_verify": False, # Change to true for prod?
            "allow_agent": False,
            "timeout": 30,
        }
        self.conn: Manager = self.connect()
        self.renderer = OcnosDeviceRenderer()

    @property
    def platform(self) -> str:
        return "ipinfusion_ocnos"

    @property
    def lag_prefix(self) -> str:
        return "po"
    

#     def get_vlans(self) -> Dict[int, Vlan]:
#         """
#         return all vlans found on all interfaces
#         XXX this doesn't include any access vlans since we're currently not collecting them
#         """
#         vlans = []
#         interfaces = self.get_interfaces()
#         for intf in interfaces:
#             for vlan in intf.trunk_vlans:
#                 vlans.append(vlan)
#         return vlans


    def connect(self) -> Manager:
        if hasattr(self, "conn"):
            return self.conn
        conn: Manager | None = manager.connect(**self.connection_data)
        if conn is None:
            raise ConnectionError("NETCONF connection failed (manager.connect returned None)")
        return conn

    def disconnect(self) -> None:
        if self.conn is not None:
            self.conn.close_session()

    def _extract_interfaces(self, interfaces_data: GetReply) -> list[Interface | Lag]:
        """
        extracts interfaces from the xml response
        """
        # we will hold vlan subinterfaces here while iterating through interface list
        vlan_interfaces: dict[str, list] = {}
        # and the same thing for lag interfaces
        lag_interfaces: dict[str, list] = {}
        interfaces: list[Interface | Lag] = []

        root: etree._Element | None = interfaces_data.data_ele
        if root is None:
            return interfaces

        ## work around bug (or a feature??) of OCNOS where some of the interfaces
        # are not returned under the <interfaces> tag but instead they appear
        # to be added at the same level. Because of that placement they are under
        # different namespaces so we need to look twice (or use something
        # like [local-name()='interface'] in xpath
        for intf in root.xpath("//*[local-name()='interface']"):
            intf: etree._Element

            intf_name = intf.findtext(".//if:name", None, namespaces=OCNOS_NS) or intf.findtext(".//nc:name", None, namespaces=OCNOS_NS)
            if intf_name is None:
                # Ask szymon how he wants to handle errors
                logger.warning("failed to find interface name in data")
                logger.debug(
                    "interface data:\n%s",
                    etree.tostring(intf, pretty_print=True, encoding="unicode")
                )
                continue

            intf_name = intf_name.strip()

            intf_description = intf.findtext(".//if:description", None, namespaces=OCNOS_NS) or intf.findtext(".//nc:description", None, namespaces=OCNOS_NS)
            if intf_description:
                intf_description = intf_description.strip()

            logical_text = (
                intf.findtext(".//if:logical", None, namespaces=OCNOS_NS)
                or intf.findtext(".//nc:logical", None, namespaces=OCNOS_NS)
            )

            intf_logical = (
                logical_text.strip().lower() in {"true", "1", "yes"}
                if logical_text is not None
                else False
            )

            # # Encapsulation / VLAN info. # Never used
            # intf_encapsulation_type = intf.findtext(".//ife:encapsulation-type", None, namespaces=OCNOS_NS)
            intf_outer_vlan_id = intf.findtext(".//ife:outer-vlan-id", None, namespaces=OCNOS_NS)
            intf_aggregate_id = intf.findtext(".//ifagg:config/ifagg:aggregate-id", None, namespaces=OCNOS_NS)
            intf_hardware_type = intf.findtext(".//ife:hardware-type", None, namespaces=OCNOS_NS)

            if intf_aggregate_id:
                lag_member_of = f"{self.lag_prefix}{intf_aggregate_id.strip()}"
    
                if lag_member_of not in lag_interfaces:
                    lag_interfaces[lag_member_of] = []

                lag_interfaces[lag_member_of].append(intf_name)
            else:
                lag_member_of = None

            if intf_logical is True:
                physical_if_name, _ = intf_name.rsplit(".", 1)

                if not intf_outer_vlan_id:
                    logger.warning(
                        logger.warning(f"Logical interface {intf_name} has no outer VLAN ID, skipping")
                    )
                    continue

                if physical_if_name not in vlan_interfaces:
                    vlan_interfaces[physical_if_name] = []

                # store vlan subinterface for later processing
                logger.info(
                    f"adding VLAN {intf_outer_vlan_id} to interface {physical_if_name}"
                )
                vlan_interfaces[physical_if_name].append(
                    Vlan(
                        vlan_id=int(intf_outer_vlan_id),
                        name=intf_description, # Originally had a or "" is it needed?
                        s_tag = None,
                    )
                )
                continue

            try:
                if intf_hardware_type == "AGG":
                    logging.info(f"adding LAG interface {intf_name}")
                    interfaces.append(
                        Lag(
                            name=intf_name,
                            description=intf_description,
                            trunk_vlans=[],
                            access_vlan=None,
                        )
                    )
                else:
                    interfaces.append(
                        Interface(
                            name=intf_name,
                            description=intf_description,
                            trunk_vlans=[],
                            access_vlan=None,
                            lag_member_of=lag_member_of,
                        )
                    )
            except Exception as e:
                logger.error(
                    f"Error creating Interface object for {intf_description}: {e}, {etree.tostring(intf)}"
                )

        for interface in interfaces:
            if interface.name in lag_interfaces:
                if isinstance(interface, Lag):
                    interface.members = lag_interfaces[interface.name]

            if interface.name in vlan_interfaces:
                interface.trunk_vlans = vlan_interfaces[interface.name]

        return interfaces

    def get_config(self) -> str:
        """
        Retrieves the whole config (running by default) via NETCONF.
        Returns the raw XML payload as a string, or "" on failure.
        """
        try:
            reply = self.conn.get_config(source="running")
            return reply.data_xml or ""

        except RPCError as e:
            # NETCONF server returned an <rpc-error>
            logger.error("NETCONF RPC error while getting config: %s", e)
            return ""
        except Exception as e:
            logger.exception("Failed to get configuration: %s", e)
            return ""

    def _extract_system_macs(self, evpn_data: GetReply) -> dict[str, str] | None:
        """
        extracts system macs from the evpn xml response

        <rpc-reply xmlns="urn:ietf:params:xml:ns:netconf:base:1.0" message-id="105" last-modified="2025-11-24T17:03:02Z">
          <data>
            <evpn xmlns="http://www.ipinfusion.com/yang/ocnos/ipi-ethernet-vpn">
              <interfaces>
                <interface>
                  <name>po1</name>
                  <config>
                    <name>po1</name>
                    <system-mac>6E61.7000.0044</system-mac>
                  </config>
                  <state>
                    <name>po1</name>
                    <system-mac>6E61.7000.0044</system-mac>
                  </state>
                </interface>
              </interfaces>
            </evpn>
          </data>
        </rpc-reply>
        """
        system_macs = {}
        root: etree._Element | None = evpn_data.data_ele
        if root is None:
            return system_macs

        ns = {"evpn": "http://www.ipinfusion.com/yang/ocnos/ipi-ethernet-vpn"}

        for intf in root.xpath("//*[local-name()='interface']"):
            intf: etree._Element
            name = intf.findtext(".//evpn:name", None, namespaces=ns)
            system_mac = intf.findtext(".//evpn:system-mac", None, namespaces=ns)
            if system_mac:
                system_macs[name] = system_mac

        return system_macs

    def get_interfaces(self) -> list[Interface | Lag]:
        if self.conn is None or not self.conn.connected: # consider making this a decorator?
            raise ConnectionError("Not connected to device")

        interfaces_subtree = """
        <interfaces xmlns="http://www.ipinfusion.com/yang/ocnos/ipi-interface"/>
        """

        evpn_filter = """
        <evpn xmlns="http://www.ipinfusion.com/yang/ocnos/ipi-ethernet-vpn">
            <interfaces>
            </interfaces>
        </evpn>
        """

        try:
            interfaces_filter = ("subtree", interfaces_subtree)
            evpn_filter = ("subtree", evpn_filter)

            interfaces_reply: GetReply = self.conn.get(filter=interfaces_filter)
            evpn_reply: GetReply = self.conn.get(filter=evpn_filter)
            interfaces = self._extract_interfaces(interfaces_reply)
            system_macs = self._extract_system_macs(evpn_reply) or {}
                      
            for iface in interfaces:
                if not isinstance(iface, Lag):
                    continue
    
                mac = system_macs.get(iface.name)
                if mac:
                    iface.system_mac = mac

            return interfaces

        except Exception as e:
            logger.exception(f"Failed to get interfaces: {e}")
            raise

    # This could cause additional calls of get_interfaces, we could do a cache of it locally?
    def get_vlans(self) -> list[Vlan]:
        return [
            vlan
            for intf in self.get_interfaces()
            if isinstance(intf, Interface)
            for vlan in intf.trunk_vlans
        ]

    # This could cause additional calls of get_interfaces, we could do a cache of it locally?
    def get_system_macs(self) -> list[str]:
        return [
            intf.system_mac
            for intf in self.get_interfaces()
            if isinstance(intf, Lag) and intf.system_mac
        ]

    def get_vnis(self) -> list[int]:
        """
        Retrieves VNIs from OcNOS using Netconf.
        """
        if self.conn is None or not self.conn.connected:  # consider making this a decorator?
            raise ConnectionError("Not connected to device")

        vxlan_subtree = """
        <vxlan xmlns="http://www.ipinfusion.com/yang/ocnos/ipi-vxlan"/>
        """
    
        try:
            vxlan_filter = ("subtree", vxlan_subtree)
            vxlan_reply: GetReply = self.conn.get(filter=vxlan_filter)

            root: etree._Element | None = vxlan_reply.data_ele
            if root is None:
                return []

            vnis: set[int] = set()

            for tenant in root.xpath(".//vxlan:vxlan-tenant", namespaces=OCNOS_NS):
                tenant: etree._Element
                vni_text = tenant.findtext(".//*[local-name()='vxlan-identifier']", None, namespaces=OCNOS_NS)
    
                if not vni_text:
                    continue

                vni_text = vni_text.strip()

                try:
                    vnis.add(int(vni_text))
                except ValueError:
                    logger.debug("invalid vni: %r", vni_text)

            return sorted(vnis)

        except Exception as e:  # i dont like this, revise it when ive got more data 
            logger.exception("Failed to get VNIs: %s", e)
            return []

#     def push_config(self, commands: List[str], dry_run: bool = False) -> str:
#         """
#         Pushes configuration to OcNOS.
#         For Netconf, 'commands' is expected to be a list containing a single XML string
#         (since our renderer now returns [xml_string]).
#         """
#         if commands is None or len(commands) == 0:
#             logger.info("No commands to push")
#             return ""
#         try:
#             logger.info(f"retrieved running config from {self.conn.host}")
#             running_cfg = self.conn.get_config(source="running")

#             logger.info(f"locking candidate config on {self.conn.host}")
#             resp = self.conn.lock(target="candidate")
#             resp.raise_for_status()

#             for cmd in commands:
#                 logger.info(f"applying config to candidate on {self.conn.host}:\n{cmd}")
#                 resp = self.conn.edit_config(config=cmd, target="candidate")
#                 print(f"edit_config response: {resp.result}")
#                 resp.raise_for_status()

#             candidate_cfg = self.conn.get_config(source="candidate")

#             # OCNOS produces all sorts of broken XML:
#             # - spaces in namespace URIs
#             #  <nacm xmlns="urn:ietf:params:xml:n s:yang:ietf-netconf-acm">
#             #    </nacm>
#             # - randomly quoted tags:
#             # <safi>unicast
#             #   /safi&gt;
#             #    <activate/>
#             #  </safi>
#             #       <config><afi>l2vpn</afi><safi>evpn</safi><activate/>
#             # /config&gt;
#             #       </config>

#             # So for now we'll just compute a text diff instead of XML diff
#             # diff = xmldiff.diff_trees(etree.fromstring(running_cfg.result.replace("urn:ietf:params:xml:n s:yang:ietf-netconf-acm", "urn:ietf:params:xml:ns:yang:ietf-netconf-acm")), etree.fromstring(candidate_cfg.result.replace("urn:ietf:params:xml:n s:yang:ietf-netconf-acm", "urn:ietf:params:xml:ns:yang:ietf-netconf-acm")))

#             diff = self._compute_diff(running_cfg.result, candidate_cfg.result)
#             # logger.info(f"computed config diff on {self.conn.host}:\n{diff}")
#             if dry_run:
#                 logger.info(f"dry run enabled, discarding changes on {self.conn.host}")
#                 self.conn.discard()
#                 return diff
#             else:
#                 response = self.conn.commit()
#                 response.raise_for_status()
#             # XXX this does nothing
#             r = self.conn.copy_config(source="running", target="startup")
#             r.raise_for_status()
#             self.conn.unlock(target="candidate")
#             return diff
#         except Exception as e:
#             logger.error(
#                 f"Failed to push config commands: {e}. Discarding changes on {self.conn.host}"
#             )
#             self.conn.discard()
#             self.conn.unlock(target="candidate")
#             raise

    def push_config(self, commands: List[str], dry_run: bool = False) -> str:
        pass


#     def push_interface(
#         self, interface: Interface, delete: bool = False, dry_run: bool = False
#     ) -> str:
#         """
#         Pushes interface configuration to OcNOS.
#         """

#         config_xml = (
#             self.renderer.render_interface_delete(interface)
#             if delete
#             else self.renderer.render_interface(interface)
#         )
#         return self.push_config([config_xml], dry_run=dry_run)


    def push_interface(
        self, interface: Interface, delete: bool = False, dry_run: bool = False
    ) -> str:
        pass

#     def push_lag(self, lag: Lag, delete: bool = False, dry_run: bool = False) -> str:
#         """
#         Pushes lag configuration to OcNOS.
#         """
#         config_xml = (
#             self.renderer.render_lag_delete(lag)
#             if delete
#             else self.renderer.render_lag(lag)
#         )
#         return self.push_config([config_xml], dry_run=dry_run)

    def push_lag(self, lag: Lag, delete: bool = False, dry_run: bool = False) -> str:
        pass

#     def push_vlan(
#         self,
#         interface: Interface,
#         vlan: Vlan,
#         delete: bool = False,
#         dry_run: bool = False,
#     ) -> str:
#         """
#         Pushes vlan configuration to OcNOS.
#         """
#         config_xml = (
#             self.renderer.render_vlan_delete(interface, vlan)
#             if delete
#             else self.renderer.render_vlan(interface, vlan)
#         )
#         return self.push_config([config_xml], dry_run=dry_run)

    def push_vlan(
        self,
        interface: Interface,
        vlan: Vlan,
        delete: bool = False,
        dry_run: bool = False,
    ) -> str:
        pass

#     def push_evpn(
#         self,
#         interface: Interface,
#         evpn: Evpn,
#         delete: bool = False,
#         dry_run: bool = False,
#     ) -> str:
#         """
#         Pushes evpn configuration to OcNOS.
#         """
#         config_xml = (
#             self.renderer.render_evpn_delete(interface, evpn)
#             if delete
#             else self.renderer.render_evpn(interface, evpn)
#         )
#         return self.push_config([config_xml], dry_run=dry_run)

    def push_evpn(
        self,
        interface: Interface,
        evpn: Evpn,
        delete: bool = False,
        dry_run: bool = False,
    ) -> str:
        pass