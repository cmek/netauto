import pytest
from netauto.render.ocnos import OcnosDeviceRenderer
from netauto.models import Evpn, Vlan, Interface, Lag, RoutingInstance, Asn


class TestOcnosDeviceRenderer:
    """Test suite for Ocnos renderer"""

    def setup_method(self):
        self.renderer = OcnosDeviceRenderer()

    def test_render_lag(self):
        """Test rendering LAG config for OcNOS (XML)."""
        xml = self.renderer.render_lag(
            Lag(
                name="po1",
                description="SO12345",
                mtu=1500,
                lacp_mode="active",
                system_mac="6E61.7000.0001",
                members=[
                    Interface(name="eth3", description="SO3333"),
                    Interface(name="eth4", description="SO4444"),
                ],
            )
        )
        assert (
            xml
            == """<?xml version="1.0" ?>
<config xmlns:if="http://www.ipinfusion.com/yang/ocnos/ipi-interface" xmlns:ifagg="http://www.ipinfusion.com/yang/ocnos/ipi-if-aggregate">
  <if:interfaces>
    <if:interface>
      <if:name>po1</if:name>
      <if:config>
        <if:mtu>1500</if:mtu>
        <if:description>SO12345</if:description>
        <if:enable-switchport/>
      </if:config>
    </if:interface>
    <if:interface>
      <if:name>eth3</if:name>
      <if:config>
        <if:mtu>1500</if:mtu>
        <if:description>SO3333</if:description>
      </if:config>
      <ifagg:member-aggregation>
        <ifagg:config>
          <ifagg:agg-type>lacp</ifagg:agg-type>
          <ifagg:aggregate-id>1</ifagg:aggregate-id>
          <ifagg:lacp-mode>active</ifagg:lacp-mode>
        </ifagg:config>
      </ifagg:member-aggregation>
    </if:interface>
    <if:interface>
      <if:name>eth4</if:name>
      <if:config>
        <if:mtu>1500</if:mtu>
        <if:description>SO4444</if:description>
      </if:config>
      <ifagg:member-aggregation>
        <ifagg:config>
          <ifagg:agg-type>lacp</ifagg:agg-type>
          <ifagg:aggregate-id>1</ifagg:aggregate-id>
          <ifagg:lacp-mode>active</ifagg:lacp-mode>
        </ifagg:config>
      </ifagg:member-aggregation>
    </if:interface>
  </if:interfaces>
</config>
"""
        )

    def test_render_interface(self):
        """Test rendering interface config for OcNOS (XML)."""
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
<config xmlns:if="http://www.ipinfusion.com/yang/ocnos/ipi-interface">
  <if:interfaces>
    <if:interface>
      <if:name>eth3</if:name>
      <if:config>
        <if:mtu>1500</if:mtu>
        <if:description>test interface</if:description>
      </if:config>
    </if:interface>
  </if:interfaces>
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
<config xmlns:if="http://www.ipinfusion.com/yang/ocnos/ipi-interface" xmlns:ifext="http://www.ipinfusion.com/yang/ocnos/ipi-if-extended">
  <if:interfaces>
    <if:interface>
      <if:name>eth3.30</if:name>
      <if:config>
        <if:mtu>1500</if:mtu>
        <if:description>SO54321</if:description>
        <if:name>eth3.30</if:name>
        <if:enable-switchport/>
      </if:config>
      <ifext:extended>
        <ifext:subinterface-encapsulation>
          <ifext:rewrite>
            <ifext:config>
              <ifext:vlan-action>pop</ifext:vlan-action>
              <ifext:enable-pop>1tag</ifext:enable-pop>
            </ifext:config>
          </ifext:rewrite>
          <ifext:single-tag-vlan-matches>
            <ifext:single-tag-vlan-match>
              <ifext:encapsulation-type>dot1q</ifext:encapsulation-type>
              <ifext:config>
                <ifext:encapsulation-type>dot1q</ifext:encapsulation-type>
                <ifext:outer-vlan-id>30</ifext:outer-vlan-id>
              </ifext:config>
            </ifext:single-tag-vlan-match>
          </ifext:single-tag-vlan-matches>
        </ifext:subinterface-encapsulation>
      </ifext:extended>
    </if:interface>
  </if:interfaces>
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

    def test_render_routing_instance(self):
        """Test rendering routing instance config"""
        service_order = "SO9999"
        xml = self.renderer.render_routing_instance(
            asn=Asn(asn="65511"),
            vrf=RoutingInstance(
                instance_name=service_order,
                instance_type="mac-vrf",
                rd=f"65511:{service_order[2:]}",
                rt_rd=f"35551:{service_order[2:]}",
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
            <bgpvrf:rd-string>65511:9999</bgpvrf:rd-string>
          </bgpvrf:config>
          <bgpvrf:route-targets>
            <bgpvrf:route-target>
              <bgpvrf:rt-rd-string>35551:9999</bgpvrf:rt-rd-string>
              <bgpvrf:config>
                <bgpvrf:rt-rd-string>35551:9999</bgpvrf:rt-rd-string>
                <bgpvrf:direction>import export</bgpvrf:direction>
              </bgpvrf:config>
            </bgpvrf:route-target>
          </bgpvrf:route-targets>
        </bgpvrf:bgp-vrf>
      </vrf:vrf>
    </netinst:network-instance>
  </netinst:network-instances>
</config>
"""
        )

    def test_render_routing_instance_delete(self):
        """Test rendering routing instance config"""
        service_order = "SO9999"
        xml = self.renderer.render_routing_instance_delete(
            asn=Asn(asn="65511"),
            vrf=RoutingInstance(
                instance_name=service_order,
                instance_type="mac-vrf",
                rd=f"65511:{service_order[2:]}",
                rt_rd=f"35551:{service_order[2:]}",
            ),
        )
        assert (
            xml
            == """<?xml version="1.0" ?>
<config xmlns:nc="urn:ietf:params:xml:ns:netconf:base:1.0" xmlns:netinst="http://www.ipinfusion.com/yang/ocnos/ipi-network-instance">
  <netinst:network-instances>
    <netinst:network-instance nc:operation="delete">
      <netinst:instance-name>SO9999</netinst:instance-name>
      <netinst:instance-type>mac-vrf</netinst:instance-type>
    </netinst:network-instance>
  </netinst:network-instances>
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
                vni=99991,
                description="SO9999",
            ),
        )
        assert (
            xml
            == """<?xml version="1.0" ?>
<config xmlns:ethvpn="http://www.ipinfusion.com/yang/ocnos/ipi-ethernet-vpn" xmlns:if="http://www.ipinfusion.com/yang/ocnos/ipi-interface" xmlns:ifext="http://www.ipinfusion.com/yang/ocnos/ipi-if-extended" xmlns:vxlan="http://www.ipinfusion.com/yang/ocnos/ipi-vxlan">
  <if:interfaces>
    <if:interface>
      <if:name>eth3.30</if:name>
      <if:config>
        <if:mtu>1500</if:mtu>
        <if:description>SO54321</if:description>
        <if:name>eth3.30</if:name>
        <if:enable-switchport/>
      </if:config>
      <ifext:extended>
        <ifext:subinterface-encapsulation>
          <ifext:rewrite>
            <ifext:config>
              <ifext:vlan-action>pop</ifext:vlan-action>
              <ifext:enable-pop>1tag</ifext:enable-pop>
            </ifext:config>
          </ifext:rewrite>
          <ifext:single-tag-vlan-matches>
            <ifext:single-tag-vlan-match>
              <ifext:encapsulation-type>dot1q</ifext:encapsulation-type>
              <ifext:config>
                <ifext:encapsulation-type>dot1q</ifext:encapsulation-type>
                <ifext:outer-vlan-id>30</ifext:outer-vlan-id>
              </ifext:config>
            </ifext:single-tag-vlan-match>
          </ifext:single-tag-vlan-matches>
        </ifext:subinterface-encapsulation>
      </ifext:extended>
    </if:interface>
  </if:interfaces>
  <ethvpn:evpn>
    <ethvpn:interfaces>
      <ethvpn:interface>
        <ethvpn:name>eth3.30</ethvpn:name>
        <ethvpn:config>
          <ethvpn:name>eth3.30</ethvpn:name>
        </ethvpn:config>
        <ethvpn:access-interfaces>
          <ethvpn:access-interface>
            <ethvpn:access-if>access-if-evpn</ethvpn:access-if>
            <ethvpn:config>
              <ethvpn:access-if>access-if-evpn</ethvpn:access-if>
              <ethvpn:evpn-identifier>99991</ethvpn:evpn-identifier>
            </ethvpn:config>
          </ethvpn:access-interface>
        </ethvpn:access-interfaces>
      </ethvpn:interface>
    </ethvpn:interfaces>
  </ethvpn:evpn>
  <vxlan:vxlan>
    <vxlan:vxlan-tenants>
      <vxlan:vxlan-tenant>
        <vxlan:vxlan-identifier>99991</vxlan:vxlan-identifier>
        <vxlan:config>
          <vxlan:vxlan-identifier>99991</vxlan:vxlan-identifier>
          <vxlan:tenant-type>ingress-replication</vxlan:tenant-type>
          <vxlan:vrf-name>SO9999</vxlan:vrf-name>
        </vxlan:config>
      </vxlan:vxlan-tenant>
    </vxlan:vxlan-tenants>
  </vxlan:vxlan>
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
                vni=99991,
                description="SO9999",
            ),
        )
        assert (
            xml
            == """<?xml version="1.0" ?>
<config xmlns:ethvpn="http://www.ipinfusion.com/yang/ocnos/ipi-ethernet-vpn" xmlns:if="http://www.ipinfusion.com/yang/ocnos/ipi-interface" xmlns:nc="urn:ietf:params:xml:ns:netconf:base:1.0" xmlns:vxlan="http://www.ipinfusion.com/yang/ocnos/ipi-vxlan">
  <if:interfaces>
    <if:interface nc:operation="delete">
      <if:name>eth3.30</if:name>
    </if:interface>
  </if:interfaces>
  <ethvpn:evpn>
    <ethvpn:interfaces>
      <ethvpn:interface nc:operation="delete">
        <ethvpn:name>eth3.30</ethvpn:name>
      </ethvpn:interface>
    </ethvpn:interfaces>
  </ethvpn:evpn>
  <vxlan:vxlan>
    <vxlan:vxlan-tenants>
      <vxlan:vxlan-tenant nc:operation="delete">
        <vxlan:vxlan-identifier>99991</vxlan:vxlan-identifier>
      </vxlan:vxlan-tenant>
    </vxlan:vxlan-tenants>
  </vxlan:vxlan>
</config>
"""
        )
