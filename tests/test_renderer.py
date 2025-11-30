import pytest
from netauto.renderer import TemplateRenderer
from netauto.models import Vrf


class TestTemplateRenderer:
    """Test suite for TemplateRenderer."""

    def setup_method(self):
        self.renderer = TemplateRenderer()

    def test_render_lag_arista(self):
        """Test rendering LAG configuration for Arista EOS."""
        
        context = {
            'lag_name': 'Port-Channel1',
            'lag_number': 1,
            'members': ['Ethernet1', 'Ethernet2'],
            'vlans': [10, 20],
            'lacp_mode': 'active',
            'has_vlans': True
        }
        
        commands = self.renderer.render_lag('arista_eos', **context)
        commands_str = "\n".join(commands)
        
        assert "interface Port-Channel1" in commands_str
        assert "switchport mode trunk" in commands_str
        assert "switchport trunk allowed vlan 10,20" in commands_str
        assert "interface Ethernet1" in commands_str
        assert "channel-group 1 mode active"  in commands_str

    def test_render_lag_ocnos(self):
        """Test rendering LAG config for OcNOS (XML)."""
        commands = self.renderer.render_lag(
            "ipinfusion_ocnos",
            lag_name="po5",
            lag_number=5,
            members=["eth3", "eth4"]
        )
        xml = commands[0]
        print(xml)
        assert xml == """<?xml version="1.0" ?>
<config>
  <interfaces xmlns="http://www.ipinfusion.com/yang/ocnos/ipi-interface">
    <interface>
      <name>po5</name>
      <config>
        <mtu>1500</mtu>
        <enable-switchport/>
      </config>
    </interface>
    <interface>
      <name>eth3</name>
      <config>
        <name>eth3</name>
      </config>
      <member-aggregation xmlns="http://www.ipinfusion.com/yang/ocnos/ipi-if-aggregate">
        <config>
          <agg-type>lacp</agg-type>
          <aggregate-id>5</aggregate-id>
          <lacp-mode>active</lacp-mode>
        </config>
      </member-aggregation>
    </interface>
    <interface>
      <name>eth4</name>
      <config>
        <name>eth4</name>
      </config>
      <member-aggregation xmlns="http://www.ipinfusion.com/yang/ocnos/ipi-if-aggregate">
        <config>
          <agg-type>lacp</agg-type>
          <aggregate-id>5</aggregate-id>
          <lacp-mode>active</lacp-mode>
        </config>
      </member-aggregation>
    </interface>
  </interfaces>
</config>
"""
#        assert '<interfaces xmlns="http://www.ipinfusion.com/yang/ocnos/ipi-interface">' in xml
#        assert '<name>po5</name>' in xml
#        assert '<name>eth3</name>' in xml

    def test_render_evpn_arista(self):
        """Test rendering EVPN config for Arista."""
        
        context = {
            'vlan_id': 100,
            'vni': 10100,
            'vrf': {
                'name': 'TENANT_A',
                'rd': '65001:100',
                'rt_import': ['65001:100'],
                'rt_export': ['65001:100']
            },
            'bgp_as': 65001
        }
        
        commands = self.renderer.render_evpn('arista_eos', **context)
        commands_str = "\n".join(commands)
        
        assert "vlan 100" in commands_str
        # Template uses: vxlan vlan <vlan_id> vni <vni>
        assert "vxlan vlan 100 vni 10100" in commands_str
        assert "vrf definition TENANT_A" in commands_str

    def test_render_evpn_ocnos(self):
        """Test rendering EVPN config for OcNOS (XML)."""
        commands = self.renderer.render_evpn(
            "ipinfusion_ocnos",
            vlan_id=200,
            vni=20200,
            vrf={
                'name': 'TENANT_A',
                'rd': '65001:200',
                'rt_import': ['65001:200'],
                'rt_export': ['65001:200']
            }
        )
        xml = commands[0]
        assert '<vlan-database xmlns="http://www.ipinfusion.com/yang/ocnos/ipi-vlan">' in xml
        assert '<id>200</id>' in xml
        assert '<vni>20200</vni>' in xml
        assert '<name>TENANT_A</name>' in xml

    def test_render_lag_no_vlans(self):
        """Test rendering LAG with no VLANs (routed)."""
        renderer = TemplateRenderer()
        
        context = {
            'lag_name': 'Port-Channel10',
            'lag_number': 10,
            'members': ['Ethernet1'],
            'vlans': [],
            'lacp_mode': 'active',
            'has_vlans': False
        }
        
        commands = renderer.render_lag('arista_eos', **context)
        commands_str = "\n".join(commands)
        
        assert "no switchport" in commands_str
        assert "switchport trunk" not in commands_str
