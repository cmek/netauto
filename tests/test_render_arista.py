import pytest
from netauto.render.arista import AristaDeviceRenderer
from netauto.models import Evpn, Vlan, Interface, Lag, RoutingInstance, Asn


class TestAristaDeviceRenderer:
    def setup_method(self):
        self.renderer = AristaDeviceRenderer()

    def test_render_lag(self):
        """Test rendering LAG config for Arista"""
        cfg = self.renderer.render_lag(
            Lag(
                name="Port-Channel10",
                description="SO12345",
                mtu=1500,
                lacp_mode="active",
                system_mac="0000:6E61:7000:0000:0001",
                members=[
                    Interface(name="Ethernet3", description="SO3333"),
                    Interface(name="Ethernet4", description="SO4444"),
                ],
            )
        )
        assert (
            "\n".join(cfg)
            == """interface Port-Channel10
  description SO12345
interface Ethernet3
  channel-group 10 mode active
  exit
interface Ethernet4
  channel-group 10 mode active
  exit"""
        )

    def test_render_interface(self):
        """Test rendering interface config for Arista"""
        cfg = self.renderer.render_interface(
            Interface(
                name="eth3",
                mtu=1500,
                description="test interface",
            ),
        )
        assert (
            "\n".join(cfg)
            == """interface eth3
  mtu 1500
  description test interface"""
        )

    def test_render_vlan(self):
        """Test rendering additional vlan"""
        cfg = self.renderer.render_vlan(
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
            "\n".join(cfg)
            == """vlan 30
  name SO54321
interface eth3
  switchport mode trunk
  switchport trunk allowed vlan add 30"""
        )

    def test_render_vlan_delete(self):
        """Test rendering deleting a vlan"""
        cfg = self.renderer.render_vlan_delete(
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
            "\n".join(cfg)
            == """interface eth3
  switchport mode trunk
  switchport trunk allowed vlan remove 30"""
        )

    def test_render_evpn(self):
        """Test rendering evpn config"""
        cfg = self.renderer.render_evpn(
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
            "\n".join(cfg)
            == """vlan 30
   name SO9999
interface eth3
   switchport mode trunk
   switchport trunk allowed vlan add 30
interface Vxlan1
   vxlan vlan 30 vni 5011
router bgp 65511
   vlan-aware-bundle SO9999
      vlan add 30"""
        )

    def test_render_evpn_delete(self):
        """Test rendering evpn config"""
        cfg = self.renderer.render_evpn_delete(
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
            "\n".join(cfg)
            == """interface eth3
  switchport trunk allowed vlan remove 30
router bgp 65511
  no vlan 30
  exit
interface Vxlan1
  no vxlan vlan 30 vni 5011
  exit"""
        )


    def test_render_routing_instance(self):
        """Test rendering routing instance config"""
        service_order="SO9999"
        cfg = self.renderer.render_routing_instance(
            asn=Asn(asn="65511"),
            vrf=RoutingInstance(
                instance_name=service_order,
                instance_type="mac-vrf",
                rd=f"6511:{service_order[2:]}",
                rt_rd=f"35551:{service_order[2:]}",
            ),
        )
        assert (
            "\n".join(cfg)
        == """router bgp 65511
   vlan-aware-bundle SO9999
      rd 6511:9999
      route-target both 35551:9999
      redistribute learned
      redistribute static"""
    )

    def test_render_routing_instance_delete(self):
        """Test rendering routing instance config"""
        service_order="SO9999"
        cfg = self.renderer.render_routing_instance_delete(
            asn=Asn(asn="65511"),
            vrf=RoutingInstance(
                instance_name=service_order,
                instance_type="mac-vrf",
                rd=f"6511:{service_order[2:]}",
                rt_rd=f"35551:{service_order[2:]}",
            ),
        )
        assert (
            "\n".join(cfg)
        == """router bgp 65511
   no vlan-aware-bundle SO9999"""
    )
