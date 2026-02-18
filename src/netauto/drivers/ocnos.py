import difflib
import logging
from collections import defaultdict
from .base import DeviceDriver
from lxml import etree
from ncclient import manager
from ncclient.manager import Manager
from ncclient.operations import RPCError
from ncclient.operations.retrieve import GetReply
from netauto.models import Interface, Vlan, Lag, Evpn, RoutingInstance
from netauto.render import OcnosDeviceRenderer


logger = logging.getLogger(__name__)

OCNOS_NS: dict[str, str] = {
    "if": "http://www.ipinfusion.com/yang/ocnos/ipi-interface",
    "ife": "http://www.ipinfusion.com/yang/ocnos/ipi-if-extended",
    "ife2": "http://www.ipinfusion.com/yang/ocnos/ipi-if-ethernet",
    "ifagg": "http://www.ipinfusion.com/yang/ocnos/ipi-if-aggregate",
    "nc": "urn:ietf:params:xml:ns:netconf:base:1.0",
    "vxlan": "http://www.ipinfusion.com/yang/ocnos/ipi-vxlan",
    "netinst": "http://www.ipinfusion.com/yang/ocnos/ipi-network-instance",
    "bgpvrf": "http://www.ipinfusion.com/yang/ocnos/ipi-bgp-vrf",
}

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

    def _compute_diff(self, running_cfg: str, candidate_cfg: str) -> str:
        def _normalize_xml(xml_str: str) -> str:
            """
            Normalizes XML string for comparison by removing insignificant whitespace.
            """
            parser = etree.XMLParser(remove_blank_text=True)
            tree = etree.fromstring(xml_str.encode(), parser)
            return etree.tostring(tree, pretty_print=True).decode()
            
        normalized_running = _normalize_xml(running_cfg)
        normalized_candidate = _normalize_xml(candidate_cfg)
        running_lines = normalized_running.splitlines(keepends=True)
        candidate_lines = normalized_candidate.splitlines(keepends=True)
        diff_lines = difflib.unified_diff(
            running_lines,
            candidate_lines,
            fromfile="running-config",
            tofile="candidate-config",
        )
        return "".join(diff_lines)

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

    def get_network_instances(self) -> list[RoutingInstance]:
        if self.conn is None or not self.conn.connected: # consider making this a decorator?
            raise ConnectionError("Not connected to device")

        network_instance_subtree = """
        <network-instances xmlns="http://www.ipinfusion.com/yang/ocnos/ipi-network-instance"/>
        """
        try:
            network_instance_filter = ("subtree", network_instance_subtree)
            network_instance_reply: GetReply = self.conn.get(filter=network_instance_filter)
    
        except Exception as e:
            logger.exception(f"Failed to get network-instances: {e}")
            raise
        
        root: etree._Element | None = network_instance_reply.data_ele
        if root is None:
            raise ValueError("Failed to get network-instances")

        network_instances: list[RoutingInstance] = []

        network_instance: etree._Element
        for network_instance in root.iterfind(
            ".//netinst:network-instance", namespaces=OCNOS_NS
        ):
            instance_name = network_instance.findtext(
                "netinst:instance-name", None, namespaces=OCNOS_NS
            )
            instance_type = network_instance.findtext(
                "netinst:instance-type", None, namespaces=OCNOS_NS
            )
            rd = network_instance.findtext(
                ".//bgpvrf:rd-string", None, namespaces=OCNOS_NS
            )
            rt_rd = network_instance.findtext(
                ".//bgpvrf:route-targets/bgpvrf:route-target/bgpvrf:config/bgpvrf:rt-rd-string",
                None,
                namespaces=OCNOS_NS,
            )

            if not instance_name or not instance_type or not rd or not rt_rd:
                continue

            network_instances.append(
                RoutingInstance(
                    instance_name=instance_name.strip(),
                    instance_type=instance_type.strip(),
                    rd=rd.strip(),
                    rt_rd=rt_rd.strip(),
                )
            )

        return network_instances

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
            vxlan_filter: tuple[str, str] = ("subtree", vxlan_subtree)
            vxlan_reply: GetReply = self.conn.get(filter=vxlan_filter)

            root: etree._Element | None = vxlan_reply.data_ele
            if root is None:
                return []

            vnis: set[int] = set()

            for tenant in root.xpath(".//vxlan:vxlan-tenant", namespaces=OCNOS_NS):
                tenant: etree._Element
                vni_text: str | None = tenant.findtext(".//*[local-name()='vxlan-identifier']", None, namespaces=OCNOS_NS)
    
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

    def push_config(self, commands: list[str], dry_run: bool = False) -> str:
        """
        Pushes configuration to OcNOS using ncclient.

        For NETCONF, `commands` is expected to be a list of XML config payload strings.
        Many renderers return [xml_string], but multiple payloads are supported.
        """
        if not commands:
            logger.info("No commands to push")
            return ""

        locked = False
        try:
            running_reply = self.conn.get_config(source="running")
            logger.debug("retrieved running config")
            running_xml = getattr(running_reply, "data_xml", None) or running_reply.xml

            logger.info("locking candidate config")
            self.conn.lock(target="candidate")
            locked = True

            for cmd in commands:
                logger.info("applying config to candidate '%s'", cmd)
                edit_reply = self.conn.edit_config(target="candidate", config=cmd)

                if hasattr(edit_reply, "ok") and edit_reply.ok is False:
                    raise RPCError(edit_reply.xml)

            candidate_reply = self.conn.get_config(source="candidate")
            candidate_xml = getattr(candidate_reply, "data_xml", None) or candidate_reply.xml

            diff = self._compute_diff(running_xml, candidate_xml)

            if dry_run:
                logger.info("dry run enabled, discarding changes")
                self.conn.discard_changes()
                return diff

            logger.info("committing candidate config")
            self.conn.commit()

            try:
                logger.info("copying running to startup")
                self.conn.copy_config(source="running", target="startup")
            except RPCError as e:
                logger.warning("copy_config running->startup failed on '%s'", e)

            return diff

        except Exception as e:
            logger.error("Failed to push config commands. '%s'", e)
            try:
                self.conn.discard_changes()
            except Exception:
                pass
            raise

        finally:
            if locked:
                try:
                    self.conn.unlock(target="candidate")
                except Exception:
                    pass


    def push_interface(
        self, interface: Interface, delete: bool = False, dry_run: bool = False
    ) -> str:
        """
        Pushes interface configuration to OcNOS.
        """
        config_xml: list[str] = (
            self.renderer.render_interface_delete(interface)
            if delete
            else self.renderer.render_interface(interface)
        )
        return self.push_config([config_xml], dry_run=dry_run)


    def push_lag(self, lag: Lag, delete: bool = False, dry_run: bool = False) -> str:
        """
        Pushes lag configuration to OcNOS.
        """
        config_xml = (
            self.renderer.render_lag_delete(lag)
            if delete
            else self.renderer.render_lag(lag)
        )
        return self.push_config([config_xml], dry_run=dry_run)

    def push_vlan(
        self,
        interface: Interface,
        vlan: Vlan,
        delete: bool = False,
        dry_run: bool = False,
    ) -> str:
        """
        Pushes vlan configuration to OcNOS.
        """
        config_xml = (
            self.renderer.render_vlan_delete(interface, vlan)
            if delete
            else self.renderer.render_vlan(interface, vlan)
        )
        return self.push_config([config_xml], dry_run=dry_run)

    def push_evpn(
        self,
        interface: Interface,
        evpn: Evpn,
        delete: bool = False,
        dry_run: bool = False,
    ) -> str:
        """
        Pushes evpn configuration to OcNOS.
        """
        config_xml = (
            self.renderer.render_evpn_delete(interface, evpn)
            if delete
            else self.renderer.render_evpn(interface, evpn)
        )
        return self.push_config([config_xml], dry_run=dry_run)
