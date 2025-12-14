from .base import DeviceDriver
from scrapli_netconf.driver import NetconfDriver as ScrapliNetconfDriver
import re
from netauto.models import Interface, Vlan, Lag
from typing import List, Dict, Any
import difflib

import xml.etree.ElementTree as ET
from lxml import etree
from netauto.render import OcnosDeviceRenderer
import logging

logger = logging.getLogger(__name__)

OCNOS_NS = {
    "if": "http://www.ipinfusion.com/yang/ocnos/ipi-interface",
    "ife": "http://www.ipinfusion.com/yang/ocnos/ipi-if-extended",
    "ife2": "http://www.ipinfusion.com/yang/ocnos/ipi-if-ethernet",
    "ifagg": "http://www.ipinfusion.com/yang/ocnos/ipi-if-aggregate",
    "nc": "urn:ietf:params:xml:ns:netconf:base:1.0",
}


class OcnosDriver(DeviceDriver):
    def __init__(self, host: str, user: str, password: str):
        self.conn = ScrapliNetconfDriver(
            host=host,
            auth_username=user,
            auth_password=password,
            auth_strict_key=False,
            transport="paramiko",
        )
        self.renderer = OcnosDeviceRenderer()

    def _get_text(self, elem: ET.Element | None) -> str | None:
        return elem.text.strip() if elem is not None and elem.text is not None else None

    def _get_bool(self, elem: ET.Element | None, default: bool = False) -> bool:
        if elem is None or elem.text is None:
            return default
        return elem.text.strip().lower() in {"true", "1", "yes"}

    @property
    def platform(self) -> str:
        return "ipinfusion_ocnos"

    @property
    def lag_prefix(self) -> str:
        return "po"

    def connect(self):
        self.conn.open()

    def disconnect(self):
        self.conn.close()

    def _fix_ocnos_xml(self, xml: str) -> str:
        """
        Clean up known-broken OCNOS XML before parsing with lxml.
        Adjust/extend patterns as you discover them.
        """
        # 1) Collapse whitespace inside xmlns="" values
        #    e.g. urn:ietf:params:xml:n s:yang:ietf-netconf-acm -> ...:ns:yang:...
        xml = re.sub(
            r'(xmlns(:\w+)?="[^"]*)\s+([^"]*")',
            lambda m: m.group(1) + m.group(3),  # drop the space(s)
            xml,
        )
        return xml

    def _extract_interfaces(self, interfaces_data):
        """
        extracts interfaces from the xml response
        """
        ## another bug in OcNOS...
        interfaces_data = interfaces_data.replace(
            "ipi-if-ext ended", "ipi-if-extended"
        ).replace("ipi-if-ex tended", "ipi-if-extended")
        interfaces_data = self._fix_ocnos_xml(interfaces_data)
        root = etree.fromstring(interfaces_data)

        # we will hold vlan subinterfaces here while iterating through interface list
        vlan_interfaces = {}
        # and the same thing for lag interfaces
        lag_interfaces = {}

        interfaces = []

        ## work around bug (or a feature??) of OCNOS where some of the interfaces
        # are not returned under the <interfaces> tag but instead they appear
        # to be added at the same level. Because of that placement they are under
        # different namespaces so we need to look twice (or use something
        # like [local-name()='interface'] in xpath
        for intf in root.xpath("//*[local-name()='interface']"):
            name = self._get_text(intf.find(f".//if:name", OCNOS_NS))
            description = self._get_text(intf.find(".//if:description", OCNOS_NS))
            logical = self._get_bool(
                intf.find(".//if:logical", OCNOS_NS), default=False
            )

            # Encapsulation / VLAN info
            encapsulation_type = self._get_text(
                intf.find(".//ife:encapsulation-type", OCNOS_NS)
            )
            outer_vlan_id = self._get_text(intf.find(".//ife:outer-vlan-id", OCNOS_NS))
            aggregate_id = self._get_text(
                intf.find(".//ifagg:config/ifagg:aggregate-id", OCNOS_NS)
            )
            hardware_type = self._get_text(intf.find(".//ife:hardware-type", OCNOS_NS))

            if aggregate_id is not None:
                lag_member_of = f"{self.lag_prefix}{aggregate_id}"
                if lag_member_of not in lag_interfaces:
                    lag_interfaces[lag_member_of] = []
                lag_interfaces[lag_member_of].append(name)
            else:
                lag_member_of = None

            if logical is True:
                physical_if_name, _ = name.rsplit(".", 1)
                if outer_vlan_id is None:
                    logger.warning(
                        f"Logical interface {name} has no outer VLAN ID, skipping"
                    )
                    continue
                if physical_if_name not in vlan_interfaces:
                    vlan_interfaces[physical_if_name] = []
                # store vlan subinterface for later processing
                logger.info(
                    f"adding VLAN {outer_vlan_id} to interface {physical_if_name}"
                )
                vlan_interfaces[physical_if_name].append(
                    Vlan(vlan_id=int(outer_vlan_id), name=description or "")
                )
                continue

            try:
                if hardware_type == "AGG":
                    logging.info(f"adding LAG interface {name}")
                    interfaces.append(
                        Lag(
                            name=name,
                            description=description,
                            trunk_vlans=[],
                            access_vlan=None,
                        )
                    )
                else:
                    interfaces.append(
                        Interface(
                            name=name,
                            description=description,
                            trunk_vlans=[],
                            access_vlan=None,
                            lag_member_of=lag_member_of,
                        )
                    )
            except Exception as e:
                logger.error(
                    f"Error creating Interface object for {name}: {e}, {etree.tostring(intf)}"
                )

        for interface in interfaces:
            if interface.name in lag_interfaces:
                if isinstance(interface, Lag):
                    interface.members = lag_interfaces[interface.name]
            if interface.name in vlan_interfaces:
                interface.trunk_vlans = [
                    vlan for vlan in vlan_interfaces[interface.name]
                ]
        return interfaces

    def get_config(self) -> str:
        """
        Retrieves the whole config. This is mostly useful for testing
        """
        try:
            return self.conn.get_config()
        except Exception as e:
            logger.error(f"Failed to get configuration: {e}")
            return ""

    def get_interfaces(self) -> Dict[str, Interface]:
        """
        Retrieves interfaces from OcNOS using Netconf.
        """
        # Filter to get interface configuration/state
        # Note: Actual filter depends on OcNOS YANG model. Using a broad filter or subtree for now.
        # Assuming IETF interfaces or OcNOS specific model.
        # For this implementation, we'll assume a standard structure similar to what we build.

        # Using a simple subtree filter for interfaces
        filter_ = """
        <interfaces xmlns="http://www.ipinfusion.com/yang/ocnos/ipi-interface">
        </interfaces>
        """
        try:
            response = self.conn.get(filter_=filter_)
            response.raise_for_status()

            interfaces = self._extract_interfaces(response.result)
            return interfaces
        except Exception as e:
            logger.error(f"Failed to get interfaces: {e}")
            raise

    def get_vlans(self) -> Dict[int, Vlan]:
        filter_ = """
        <vlan-database xmlns="http://www.ipinfusion.com/yang/ocnos/ipi-vlan">
        </vlan-database>
        """
        try:
            response = self.conn.get(filter_=filter_)
            if not response.result:
                return {}

            root = ET.fromstring(response.result)
            ns = {"ocnos": "http://www.ipinfusion.com/yang/ocnos/ipi-vlan"}

            vlans = {}
            for vlan in root.findall(".//ocnos:vlan", ns):
                vlan_id_elem = vlan.find("ocnos:id", ns)
                if vlan_id_elem is not None:
                    vlan_id = int(vlan_id_elem.text)
                    name_elem = vlan.find("ocnos:name", ns)
                    name = name_elem.text if name_elem is not None else f"VLAN{vlan_id}"
                    vlans[vlan_id] = Vlan(vlan_id=vlan_id, name=name)
            return vlans
        except Exception as e:
            logger.error(f"Failed to get VLANs: {e}")
            return {}

    def get_vnis(self) -> Dict[int, Dict[str, Any]]:
        filter_ = """
        <vxlan xmlns="http://www.ipinfusion.com/yang/ocnos/ipi-vxlan">
        </vxlan>
        """
        try:
            response = self.conn.get(filter_=filter_)
            if not response.result:
                return {}

            root = ET.fromstring(response.result)
            ns = {"ocnos": "http://www.ipinfusion.com/yang/ocnos/ipi-vxlan"}

            vnis = {}
            for vxlan in root.findall(
                ".//ocnos:vxlan", ns
            ):  # Assuming list of vxlan mappings
                # Note: Structure might be different, e.g. single vxlan container with list
                # Adjusting for potential list item
                vni_elem = vxlan.find("ocnos:vni", ns)
                vlan_elem = vxlan.find("ocnos:vlan", ns)

                if vni_elem is not None and vlan_elem is not None:
                    vni = int(vni_elem.text)
                    vlan_id = int(vlan_elem.text)
                    vnis[vni] = {"vlan_id": vlan_id}
            return vnis
        except Exception as e:
            logger.error(f"Failed to get VNIs: {e}")
            return {}

    def _normalize_xml(self, xml_str: str) -> str:
        """
        Normalizes XML string for comparison by removing insignificant whitespace.
        """
        # fix Ocnos bug:
        xml_str = self._fix_ocnos_xml(xml_str)
        parser = etree.XMLParser(remove_blank_text=True)
        tree = etree.fromstring(xml_str.encode(), parser)
        return etree.tostring(tree, pretty_print=True).decode()

    def _compute_diff(self, running_cfg: str, candidate_cfg: str) -> str:
        normalized_running = self._normalize_xml(running_cfg)
        normalized_candidate = self._normalize_xml(candidate_cfg)
        running_lines = normalized_running.splitlines(keepends=True)
        candidate_lines = normalized_candidate.splitlines(keepends=True)
        diff_lines = difflib.unified_diff(
            running_lines,
            candidate_lines,
            fromfile="running-config",
            tofile="candidate-config",
        )
        return "".join(diff_lines)

    def push_config(self, commands: List[str], dry_run: bool = False) -> str:
        """
        Pushes configuration to OcNOS.
        For Netconf, 'commands' is expected to be a list containing a single XML string
        (since our renderer now returns [xml_string]).
        """
        try:
            logger.info(f"retrieved running config from {self.conn.host}")
            running_cfg = self.conn.get_config(source="running")

            logger.info(f"locking candidate config on {self.conn.host}")
            resp = self.conn.lock(target="candidate")
            resp.raise_for_status()

            for cmd in commands:
                logger.info(f"applying config to candidate on {self.conn.host}:\n{cmd}")
                resp = self.conn.edit_config(config=cmd, target="candidate")
                print("result: ", resp.result)
                resp.raise_for_status()

            candidate_cfg = self.conn.get_config(source="candidate")

            # OCNOS produces all sorts of broken XML:
            # - spaces in namespace URIs
            #  <nacm xmlns="urn:ietf:params:xml:n s:yang:ietf-netconf-acm">
            #    </nacm>
            # - randomly quoted tags:
            # <safi>unicast
            #   /safi&gt;
            #    <activate/>
            #  </safi>
            #       <config><afi>l2vpn</afi><safi>evpn</safi><activate/>
            # /config&gt;
            #       </config>

            # So for now we'll just compute a text diff instead of XML diff
            # diff = xmldiff.diff_trees(etree.fromstring(running_cfg.result.replace("urn:ietf:params:xml:n s:yang:ietf-netconf-acm", "urn:ietf:params:xml:ns:yang:ietf-netconf-acm")), etree.fromstring(candidate_cfg.result.replace("urn:ietf:params:xml:n s:yang:ietf-netconf-acm", "urn:ietf:params:xml:ns:yang:ietf-netconf-acm")))

            diff = self._compute_diff(running_cfg.result, candidate_cfg.result)
            logger.info(f"computed config diff on {self.conn.host}:\n{diff}")
            if dry_run:
                logger.info(f"dry run enabled, discarding changes on {self.conn.host}")
                self.conn.discard()
                return diff
            else:
                response = self.conn.commit()
                print("result: ", response.result)
                response.raise_for_status()
            # XXX this does nothing
            r = self.conn.copy_config(source="running", target="startup")
            r.raise_for_status()
            self.conn.unlock(target="candidate")
            return diff
        except Exception as e:
            logger.error(
                f"Failed to push config commands: {e}. Discarding changes on {self.conn.host}"
            )
            self.conn.discard()
            self.conn.unlock(target="candidate")
            raise

    def push_interface(
        self, interface: Interface, delete: bool = False, dry_run: bool = False
    ) -> str:
        """
        Pushes interface configuration to OcNOS.
        """

        config_xml = (
            self.renderer.render_interface_delete(interface)
            if delete
            else self.renderer.render_interface(interface)
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
