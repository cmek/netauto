import pytest
from netauto.render.arista import AristaDeviceRenderer
from netauto.models import Evpn, Vlan, Interface, Lag, RoutingInstance, Asn, AzureEvpn


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

    def test_render_lag_with_trunk_vlans(self):
        """LAG create migrates trunk VLANs onto the Port-Channel."""
        cfg = self.renderer.render_lag(
            Lag(
                name="Port-Channel10",
                description="SO12345",
                lacp_mode="active",
                mode="trunk",
                trunk_vlans=[Vlan(vlan_id=10), Vlan(vlan_id=20)],
                members=[
                    Interface(name="Ethernet3"),
                    Interface(name="Ethernet4"),
                ],
            )
        )
        assert (
            "\n".join(cfg)
            == """interface Port-Channel10
  description SO12345
  switchport
  switchport mode trunk
  switchport trunk allowed vlan 10,20
interface Ethernet3
  channel-group 10 mode active
  exit
interface Ethernet4
  channel-group 10 mode active
  exit"""
        )

    def test_render_lag_plain(self):
        """A LAG with no VLANs/description renders just the bundle."""
        cfg = self.renderer.render_lag(
            Lag(
                name="Port-Channel10",
                lacp_mode="active",
                members=[
                    Interface(name="Ethernet3"),
                    Interface(name="Ethernet4"),
                ],
            )
        )
        assert (
            "\n".join(cfg)
            == """interface Port-Channel10
interface Ethernet3
  channel-group 10 mode active
  exit
interface Ethernet4
  channel-group 10 mode active
  exit"""
        )

    def test_render_lag_delete(self):
        """LAG delete splits members back to standalone ports (plain split)."""
        cfg = self.renderer.render_lag_delete(
            Lag(
                name="Port-Channel10",
                members=[
                    Interface(name="Ethernet3"),
                    Interface(name="Ethernet4"),
                ],
            )
        )
        assert (
            "\n".join(cfg)
            == """interface Ethernet3
  no channel-group
  exit
interface Ethernet4
  no channel-group
  exit
no interface Port-Channel10"""
        )

    def test_render_lag_add_members(self):
        """Adding a member renders only its channel-group, not the LAG."""
        cfg = self.renderer.render_lag_add_members(
            Lag(
                name="Port-Channel10",
                lacp_mode="active",
                members=[Interface(name="Ethernet7")],
            )
        )
        assert (
            "\n".join(cfg)
            == """interface Ethernet7
  channel-group 10 mode active
  exit"""
        )

    def test_render_lag_remove_members(self):
        """Removing a member renders only 'no channel-group' (LAG kept)."""
        cfg = self.renderer.render_lag_remove_members(
            Lag(name="Port-Channel10", members=[Interface(name="Ethernet7")])
        )
        assert (
            "\n".join(cfg)
            == """interface Ethernet7
  no channel-group
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
            == """router bgp 65511
   vlan-aware-bundle SO9999
      no vlan 30
interface Vxlan1
   no vxlan vlan 30 vni 5011
interface eth3
   switchport trunk allowed vlan remove 30
no vlan 30"""
        )


    def test_render_evpn_uses_vni_verbatim(self):
        """The VNI is allocated externally and used as-is for the VXLAN id; the
        vlan-aware-bundle keeps the service key. service_type does not change it."""
        for service_type in ("cloud_vc", "p2p_vc"):
            cfg = "\n".join(
                self.renderer.render_evpn(
                    Interface(name="Ethernet6"),
                    Evpn(
                        vlan=Vlan(vlan_id=100, name="SO555"),
                        asn=65001,
                        vni=5000,
                        description="SO555",
                        service_type=service_type,
                    ),
                )
            )
            assert "vxlan vlan 100 vni 5000\n" in cfg + "\n"
            assert "vlan-aware-bundle SO555" in cfg

    def test_render_azure_customer_multi_ctag(self):
        """Customer side tunnels each C-TAG into the S-TAG via dot1q-tunnel."""
        cfg = "\n".join(
            self.renderer.render_azure_evpn(
                Interface(name="Ethernet6"),
                AzureEvpn(
                    description="SO555", asn=65001, vni=6000, s_tag=500,
                    role="customer", c_tags=[10, 20, 30],
                ),
            )
        )
        assert "switchport vlan translation 10 dot1q-tunnel 500" in cfg
        assert "switchport vlan translation 20 dot1q-tunnel 500" in cfg
        assert "switchport vlan translation 30 dot1q-tunnel 500" in cfg
        assert "vxlan vlan 500 vni 6000" in cfg
        assert "vlan-aware-bundle SO555" in cfg

    def test_render_azure_cni_standard_has_no_translation(self):
        cfg = "\n".join(
            self.renderer.render_azure_evpn(
                Interface(name="Ethernet6"),
                AzureEvpn(description="SO555", asn=65001, vni=6000, s_tag=500, role="cni"),
            )
        )
        assert "vxlan vlan 500 vni 6000" in cfg
        assert "vlan translation" not in cfg
        assert "dot1q-tunnel" not in cfg

    def test_render_azure_cni_rewrite_translates_to_internal_stag(self):
        cfg = "\n".join(
            self.renderer.render_azure_evpn(
                Interface(name="Ethernet6"),
                AzureEvpn(
                    description="SO555", asn=65001, vni=6000, s_tag=500,
                    role="cni", rewrite=True, internal_s_tag=2500,
                ),
            )
        )
        # Azure S-TAG 500 translated to internal 2500; VXLAN keyed on internal
        assert "switchport vlan translation 500 2500" in cfg
        assert "vxlan vlan 2500 vni 6000" in cfg
        assert "vlan 2500" in cfg

    def test_render_azure_cni_rewrite_requires_internal_stag(self):
        with pytest.raises(ValueError):
            self.renderer.render_azure_evpn(
                Interface(name="Ethernet6"),
                AzureEvpn(description="SO555", asn=65001, vni=6000, s_tag=500,
                          role="cni", rewrite=True),
            )

    def test_render_azure_customer_delete(self):
        cfg = "\n".join(
            self.renderer.render_azure_evpn_delete(
                Interface(name="Ethernet6"),
                AzureEvpn(description="SO555", asn=65001, vni=6000, s_tag=500,
                          role="customer", c_tags=[10, 20]),
            )
        )
        assert "no vxlan vlan 500 vni 6000" in cfg
        assert "no switchport vlan translation 10 dot1q-tunnel 500" in cfg
        assert "no switchport vlan translation 20 dot1q-tunnel 500" in cfg
        assert "no vlan 500" in cfg

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
