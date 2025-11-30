import xml.etree.ElementTree as ET
import xml.dom.minidom
from typing import List, Dict, Any, Optional
from .models import Interface, Lag


def is_rpc_reply_ok(xml_string):
    root = ET.fromstring(xml_string)
    # Check for <rpc-error> element
    if root.find(".//{*}rpc-error") is not None:
        return False
    # Check for <ok> element
    if root.find(".//{*}ok") is not None:
        return True
    return False


def extract_rpc_error_info(xml_string):
    root = ET.fromstring(xml_string)
    error_elem = root.find(".//{*}rpc-error")
    if error_elem is None:
        return None  # No error found

    error_info = {}
    for tag in [
        "error-type",
        "error-tag",
        "error-severity",
        "error-app-tag",
        "error-path",
        "error-message",
    ]:
        elem = error_elem.find(f".//{{*}}{tag}")
        if elem is not None:
            error_info[tag] = elem.text

    # Extract <error-info> subfields if present
    error_info_elem = error_elem.find(".//{*}error-info")
    if error_info_elem is not None:
        for child in error_info_elem:
            error_info[child.tag.split("}", 1)[-1]] = child.text

    return error_info


def _create_config_base() -> ET.Element:
    """Creates the base <config> element."""
    return ET.Element("config")


def _tostring(element: ET.Element) -> str:
    """Converts an Element to a string."""
    raw = ET.tostring(element, encoding="unicode")
    # this is not the most efficient approach ;)
    parsed = xml.dom.minidom.parseString(raw)
    return parsed.toprettyxml(indent="  ")


def build_interface_config(interface: Interface) -> str:
    config = _create_config_base()

    interfaces = ET.SubElement(
        config, "interfaces", xmlns="http://www.ipinfusion.com/yang/ocnos/ipi-interface"
    )

    intf = ET.SubElement(interfaces, "interface")
    ET.SubElement(intf, "name").text = interface.name
    intf_config = ET.SubElement(intf, "config")
    ET.SubElement(intf_config, "mtu").text = str(interface.mtu)
    ET.SubElement(intf_config, "description").text = interface.description

    return _tostring(config)


def build_lag_config(
    lag_number: int,
    members: List[str],
    lacp_mode: str = "active",
    min_links: int = 1,
    mtu: int = 1500,
) -> str:
    """
        Builds XML configuration for creating a LAG.

        Structure (Example):
        <interfaces xmlns="http://www.ipinfusion.com/yang/ocnos/ipi-interface">
           <interface>
              <name>po10</name>
              <config>
                <name>po10</name>
                <enable-switchport></enable-switchport>
                <mtu>1500</mtu>
              </config>
            </interface>
    # member interfaces
            <interface>
              <name>eth4</name>
              <config>
                <name>eth4</name>
              </config>
              <member-aggregation xmlns="http://www.ipinfusion.com/yang/ocnos/ipi-if-aggregate">
                <config>
                  <agg-type>lacp</agg-type>
                  <aggregate-id>10</aggregate-id>
                  <lacp-mode>active</lacp-mode>
                </config>
              </member-aggregation>
            </interface>
    """
    config = _create_config_base()
    name = f"po{lag_number}"

    interfaces = ET.SubElement(
        config, "interfaces", xmlns="http://www.ipinfusion.com/yang/ocnos/ipi-interface"
    )

    # po (LAG) interface
    lag_intf = ET.SubElement(interfaces, "interface")
    ET.SubElement(lag_intf, "name").text = name
    lag_intf_config = ET.SubElement(lag_intf, "config")
    ET.SubElement(lag_intf_config, "mtu").text = str(mtu)
    ET.SubElement(lag_intf_config, "enable-switchport")

    # Member Interfaces
    for member in members:
        mem_intf = ET.SubElement(interfaces, "interface")
        ET.SubElement(mem_intf, "name").text = member
        mem_intf_config = ET.SubElement(mem_intf, "config")
        ET.SubElement(mem_intf_config, "name").text = member

        member_agg = ET.SubElement(
            mem_intf,
            "member-aggregation",
            xmlns="http://www.ipinfusion.com/yang/ocnos/ipi-if-aggregate",
        )
        member_agg_config = ET.SubElement(member_agg, "config")
        ET.SubElement(member_agg_config, "agg-type").text = "lacp"
        ET.SubElement(member_agg_config, "aggregate-id").text = str(lag_number)
        ET.SubElement(member_agg_config, "lacp-mode").text = lacp_mode

    return _tostring(config)


def build_lag_delete(name: str, members: List[str]) -> str:
    """
    Builds XML configuration for deleting a LAG.
    """
    config = _create_config_base()

    # Delete LAG Interface
    lag_intf = ET.SubElement(
        config,
        "interface",
        xmlns="http://www.ipinfusion.com/yang/ocnos/ipi-interface",
        operation="delete",
    )
    ET.SubElement(lag_intf, "name").text = name

    # Unbind members (optional depending on device behavior, but safer to remove config)
    for member in members:
        mem_intf = ET.SubElement(
            config,
            "interface",
            xmlns="http://www.ipinfusion.com/yang/ocnos/ipi-interface",
        )
        ET.SubElement(mem_intf, "name").text = member
        eth_opts = ET.SubElement(mem_intf, "ether-options")
        ieee = ET.SubElement(eth_opts, "ieee-802.3ad", operation="delete")

    return _tostring(config)


def build_evpn_service(
    vlan_id: int,
    vni: int,
    vrf_name: str,
    rd: str,
    rt_import: List[str],
    rt_export: List[str],
    s_tag: Optional[int] = None,
) -> str:
    """
    Builds XML configuration for an EVPN service.
    """
    config = _create_config_base()

    # VLAN
    vlan_db = ET.SubElement(
        config, "vlan-database", xmlns="http://www.ipinfusion.com/yang/ocnos/ipi-vlan"
    )
    vlan = ET.SubElement(vlan_db, "vlan")
    ET.SubElement(vlan, "id").text = str(vlan_id)

    vlan_name = f"EVPN_VLAN_{vlan_id}"
    if s_tag:
        vlan_name += f"_STAG_{s_tag}"
    ET.SubElement(vlan, "name").text = vlan_name

    # VRF
    vrf = ET.SubElement(
        config, "vrf", xmlns="http://www.ipinfusion.com/yang/ocnos/ipi-vrf"
    )
    ET.SubElement(vrf, "name").text = vrf_name
    ET.SubElement(vrf, "rd").text = rd

    # Address Family L2VPN EVPN
    af = ET.SubElement(vrf, "address-family")
    ET.SubElement(af, "type").text = "l2vpn"
    ET.SubElement(af, "safi").text = "evpn"

    # Route Targets
    for rt in rt_import:
        rt_elem = ET.SubElement(af, "route-target")
        ET.SubElement(rt_elem, "type").text = "import"
        ET.SubElement(rt_elem, "value").text = rt

    for rt in rt_export:
        rt_elem = ET.SubElement(af, "route-target")
        ET.SubElement(rt_elem, "type").text = "export"
        ET.SubElement(rt_elem, "value").text = rt

    # VXLAN
    vxlan = ET.SubElement(
        config, "vxlan", xmlns="http://www.ipinfusion.com/yang/ocnos/ipi-vxlan"
    )
    ET.SubElement(vxlan, "vlan").text = str(vlan_id)
    ET.SubElement(vxlan, "vni").text = str(vni)

    return _tostring(config)


def build_evpn_delete(vlan_id: int, vrf_name: str) -> str:
    """
    Builds XML configuration for deleting an EVPN service.
    """
    config = _create_config_base()

    # Delete VLAN
    vlan_db = ET.SubElement(
        config, "vlan-database", xmlns="http://www.ipinfusion.com/yang/ocnos/ipi-vlan"
    )
    vlan = ET.SubElement(vlan_db, "vlan", operation="delete")
    ET.SubElement(vlan, "id").text = str(vlan_id)

    # Delete VRF (Note: This might be too aggressive if VRF is shared, but for this POC we assume 1:1 or managed deletion)
    # Ideally we only remove the AF or RTs if shared, but let's assume we delete the VRF for now as per previous logic
    vrf = ET.SubElement(
        config,
        "vrf",
        xmlns="http://www.ipinfusion.com/yang/ocnos/ipi-vrf",
        operation="delete",
    )
    ET.SubElement(vrf, "name").text = vrf_name

    # Delete VXLAN mapping
    vxlan = ET.SubElement(
        config,
        "vxlan",
        xmlns="http://www.ipinfusion.com/yang/ocnos/ipi-vxlan",
        operation="delete",
    )
    ET.SubElement(vxlan, "vlan").text = str(vlan_id)

    return _tostring(config)
