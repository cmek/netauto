import pytest
import xml.etree.ElementTree as ET
from netauto.ocnos_xml import build_lag_config, build_lag_delete, build_evpn_service, build_evpn_delete

class TestOcnosXml:
    """Test suite for OcNOS XML builder."""

    def _canonicalize(self, xml_str):
        """Canonicalize XML string for comparison (ignore whitespace/ordering)."""
        # Simple approach: Parse and tostring
        # For more robust comparison, we might need lxml, but this should suffice for structure check
        try:
            root = ET.fromstring(xml_str)
            return ET.tostring(root, encoding="unicode")
        except ET.ParseError:
            return xml_str

    def test_build_lag_config(self):
        """Test LAG configuration XML generation."""
        xml = build_lag_config(10, ["eth1", "eth2"], "active", 1)
        
        assert '<interfaces xmlns="http://www.ipinfusion.com/yang/ocnos/ipi-interface">' in xml
        assert '<name>po10</name>' in xml
        assert '<lacp-mode>active</lacp-mode>' in xml
        assert '<name>eth1</name>' in xml

    def test_build_lag_delete(self):
        """Test LAG delete XML generation."""
        xml = build_lag_delete("po10", ["eth1"])
        
        assert 'operation="delete"' in xml
        assert '<name>po10</name>' in xml
        # ElementTree might render as self-closing
        assert 'ieee-802.3ad' in xml and 'operation="delete"' in xml

    def test_build_evpn_service(self):
        """Test EVPN service XML generation."""
        xml = build_evpn_service(
            vlan_id=10, 
            vni=10010, 
            vrf_name="TEST", 
            rd="1:1", 
            rt_import=["1:1"], 
            rt_export=["1:1"],
            s_tag=200
        )
        
        assert '<vlan-database xmlns="http://www.ipinfusion.com/yang/ocnos/ipi-vlan">' in xml
        assert '<id>10</id>' in xml
        assert '<name>EVPN_VLAN_10_STAG_200</name>' in xml
        assert '<vrf xmlns="http://www.ipinfusion.com/yang/ocnos/ipi-vrf">' in xml
        assert '<name>TEST</name>' in xml
        assert '<vxlan xmlns="http://www.ipinfusion.com/yang/ocnos/ipi-vxlan">' in xml
        assert '<vni>10010</vni>' in xml

    def test_build_evpn_delete(self):
        """Test EVPN delete XML generation."""
        xml = build_evpn_delete(10, "TEST")
        
        assert 'operation="delete"' in xml
        assert '<id>10</id>' in xml
        assert '<name>TEST</name>' in xml
