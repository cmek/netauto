import pytest
from netauto.render.ocnos import OcnosDeviceRenderer
from netauto.models import Evpn, Vlan, Interface


class TestOcnosDeviceRenderer:
    """Test suite for Ocnos renderer"""

    def setup_method(self):
        self.renderer = OcnosDeviceRenderer()

    def test_render_interface(self):
        """Test rendering LAG config for OcNOS (XML)."""
        xml = self.renderer.render_interface(
            Interface(
                name="eth3",
                mtu=1500,
                description="test interface",
            ),
        )
        assert (
            xml
            == """<?xml version="1.0" ?>
<config>
  <interfaces xmlns="http://www.ipinfusion.com/yang/ocnos/ipi-interface">
    <interface>
      <name>eth3</name>
      <config>
        <mtu>1500</mtu>
        <description>test interface</description>
      </config>
    </interface>
  </interfaces>
</config>
"""
        )

    def test_render_vlan(self):
        """Test rendering additional vlan"""
        xml = self.renderer.render_vlan(
            Interface(
                name="eth3",
                mtu=1500,
                description="test interface",
            ),
            Vlan(
                vlan_id=30,
                name="SO54321",
                s_tag=None,
            ),
        )
        assert (
            xml
            == """<?xml version="1.0" ?>
<config>
  <interfaces xmlns="http://www.ipinfusion.com/yang/ocnos/ipi-interface">
    <interface>
      <name>eth3.30</name>
      <config>
        <mtu>1500</mtu>
        <description>SO54321</description>
        <name>eth3.30</name>
        <enable-switchport/>
      </config>
      <extended xmlns="http://www.ipinfusion.com/yang/ocnos/ipi-if-extended">
        <subinterface-encapsulation>
          <rewrite>
            <config>
              <vlan-action>pop</vlan-action>
              <enable-pop>1tag</enable-pop>
            </config>
          </rewrite>
          <single-tag-vlan-matches>
            <single-tag-vlan-match>
              <encapsulation-type>dot1q</encapsulation-type>
              <config>
                <encapsulation-type>dot1q</encapsulation-type>
                <outer-vlan-id>30</outer-vlan-id>
              </config>
            </single-tag-vlan-match>
          </single-tag-vlan-matches>
        </subinterface-encapsulation>
      </extended>
    </interface>
  </interfaces>
</config>
"""
        )

    def test_render_vlan_delete(self):
        """Test rendering deleting a vlan"""
        xml = self.renderer.render_vlan_delete(
            Interface(
                name="eth3",
                mtu=1500,
                description="test interface",
            ),
            Vlan(
                vlan_id=30,
                name="SO54321",
                s_tag=None,
            ),
        )
        assert (
            xml
            == """<?xml version="1.0" ?>
<config xmlns:if="http://www.ipinfusion.com/yang/ocnos/ipi-interface" xmlns:nc="urn:ietf:params:xml:ns:netconf:base:1.0">
  <if:interfaces>
    <if:interface nc:operation="delete">
      <if:name>eth3.30</if:name>
    </if:interface>
  </if:interfaces>
</config>
"""
        )

    def test_render_evpn(self):
        """Test rendering evpn config"""
        xml = self.renderer.render_evpn(
            Interface(
                name="eth3",
                mtu=1500,
                description="test interface",
            ),
            Evpn(
                vlan=Vlan(
                    vlan_id=30,
                    name="SO54321",
                    s_tag=None,
                ),
                asn=65511,
                vni=5011,
                description="SO9999",
            ),
        )
        assert (
            xml
            == """<?xml version="1.0" ?>
<config xmlns:bgpvrf="http://www.ipinfusion.com/yang/ocnos/ipi-bgp-vrf" xmlns:netinst="http://www.ipinfusion.com/yang/ocnos/ipi-network-instance" xmlns:vrf="http://www.ipinfusion.com/yang/ocnos/ipi-vrf">
  <netinst:network-instances>
    <netinst:network-instance>
      <netinst:instance-name>SO9999</netinst:instance-name>
      <netinst:instance-type>mac-vrf</netinst:instance-type>
      <netinst:config>
        <netinst:instance-name>SO9999</netinst:instance-name>
        <netinst:instance-type>mac-vrf</netinst:instance-type>
      </netinst:config>
      <vrf:vrf>
        <vrf:config>
          <vrf:vrf-name>SO9999</vrf:vrf-name>
        </vrf:config>
        <bgpvrf:bgp-vrf>
          <bgpvrf:config>
            <bgpvrf:rd-string>65511:5011</bgpvrf:rd-string>
          </bgpvrf:config>
          <bgpvrf:route-targets>
            <bgpvrf:route-target>
              <bgpvrf:rt-rd-string>65511:5011</bgpvrf:rt-rd-string>
              <bgpvrf:config>
                <bgpvrf:rt-rd-string>65511:5011</bgpvrf:rt-rd-string>
                <bgpvrf:direction>import export</bgpvrf:direction>
              </bgpvrf:config>
            </bgpvrf:route-target>
          </bgpvrf:route-targets>
        </bgpvrf:bgp-vrf>
      </vrf:vrf>
    </netinst:network-instance>
  </netinst:network-instances>
  <interfaces xmlns="http://www.ipinfusion.com/yang/ocnos/ipi-interface">
    <interface>
      <name>eth3.30</name>
      <config>
        <mtu>1500</mtu>
        <description>SO54321</description>
        <name>eth3.30</name>
        <enable-switchport/>
      </config>
      <extended xmlns="http://www.ipinfusion.com/yang/ocnos/ipi-if-extended">
        <subinterface-encapsulation>
          <rewrite>
            <config>
              <vlan-action>pop</vlan-action>
              <enable-pop>1tag</enable-pop>
            </config>
          </rewrite>
          <single-tag-vlan-matches>
            <single-tag-vlan-match>
              <encapsulation-type>dot1q</encapsulation-type>
              <config>
                <encapsulation-type>dot1q</encapsulation-type>
                <outer-vlan-id>30</outer-vlan-id>
              </config>
            </single-tag-vlan-match>
          </single-tag-vlan-matches>
        </subinterface-encapsulation>
      </extended>
    </interface>
  </interfaces>
</config>
"""
        )

    def test_render_evpn_delete(self):
        """Test rendering evpn config"""
        xml = self.renderer.render_evpn_delete(
            Interface(
                name="eth3",
                mtu=1500,
                description="test interface",
            ),
            Evpn(
                vlan=Vlan(
                    vlan_id=30,
                    name="SO54321",
                    s_tag=None,
                ),
                asn=65511,
                vni=5011,
                description="SO9999",
            ),
        )
        assert (
            xml
            == """<?xml version="1.0" ?>
<config xmlns:bgpvrf="http://www.ipinfusion.com/yang/ocnos/ipi-bgp-vrf" xmlns:if="http://www.ipinfusion.com/yang/ocnos/ipi-interface" xmlns:nc="urn:ietf:params:xml:ns:netconf:base:1.0" xmlns:netinst="http://www.ipinfusion.com/yang/ocnos/ipi-network-instance" xmlns:vrf="http://www.ipinfusion.com/yang/ocnos/ipi-vrf">
  <netinst:network-instances>
    <netinst:network-instance nc:operation="delete">
      <netinst:instance-name>SO9999</netinst:instance-name>
      <netinst:instance-type>mac-vrf</netinst:instance-type>
      <vrf:vrf nc:operation="delete">
        <vrf:config>
          <vrf:vrf-name>SO9999</vrf:vrf-name>
        </vrf:config>
        <bgpvrf:bgp-vrf nc:operation="delete">
          <bgpvrf:config>
            <bgpvrf:rd-string>65511:5011</bgpvrf:rd-string>
          </bgpvrf:config>
          <bgpvrf:route-targets>
            <bgpvrf:route-target nc:operation="delete">
              <bgpvrf:rt-rd-string>65511:5011</bgpvrf:rt-rd-string>
              <bgpvrf:config>
                <bgpvrf:rt-rd-string>65511:5011</bgpvrf:rt-rd-string>
                <bgpvrf:direction>import export</bgpvrf:direction>
              </bgpvrf:config>
            </bgpvrf:route-target>
          </bgpvrf:route-targets>
        </bgpvrf:bgp-vrf>
      </vrf:vrf>
    </netinst:network-instance>
  </netinst:network-instances>
  <if:interfaces>
    <if:interface nc:operation="delete">
      <if:name>eth3.30</if:name>
    </if:interface>
  </if:interfaces>
</config>
"""
        )
