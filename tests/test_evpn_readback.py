"""EVPN read-back / inspection tests.

Two angles:
  * **Arista** — parse realistic running-config snippets into EvpnCircuit.
  * **OcNOS** — a true render -> parse round-trip: render a circuit, assemble a
    get-config-style <data> tree, parse it back, assert the model is recovered.
Plus EvpnManager.verify_circuit drift detection.
"""

import pytest
from lxml import etree

from netauto.allocation import find_conflicts
from netauto.evpn import EvpnManager
from netauto.models import AzureEvpn, Asn, Evpn, Interface, RoutingInstance, Vlan
from netauto.parsers.arista import AristaConfigParser
from netauto.parsers.ocnos import OcnosConfigXMLParser
from netauto.render.ocnos import OcnosDeviceRenderer


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _ri(service_key, asn, rt_prefix):
    num = service_key[2:]
    return RoutingInstance(
        instance_name=service_key, instance_type="mac-vrf",
        rd=f"{asn}:{num}", rt_rd=f"{rt_prefix}:{num}",
    )


def _ocnos_device_tree(*payloads: str) -> etree._Element:
    """Merge rendered <config> payloads into one <data> tree, as a get-config
    reply would present them (the validation files concatenate two <config>
    docs, which isn't a single tree)."""
    data = etree.Element("data")
    for xml in payloads:
        for child in list(etree.fromstring(xml.encode())):
            data.append(child)
    return data


def _ocnos_roundtrip(service, rt_prefix):
    """Render a circuit + its VRF, reassemble as a device tree, parse it back."""
    r = OcnosDeviceRenderer()
    ri = _ri(service.description, service.asn, rt_prefix)
    vrf = r.render_routing_instance(Asn(asn=service.asn), ri)
    if isinstance(service, AzureEvpn):
        circ = r.render_azure_evpn(Interface(name="eth4"), service)
    else:
        circ = r.render_evpn(Interface(name="eth4"), service)
    tree = _ocnos_device_tree(vrf, circ)
    return OcnosConfigXMLParser(tree).parse_evpn_circuits()


class _FakeDriver:
    def __init__(self, platform, config):
        self.platform = platform
        self._config = config

    def get_config(self):
        return self._config


# --------------------------------------------------------------------------- #
# Arista — running-config snippets -> EvpnCircuit
# --------------------------------------------------------------------------- #
ARISTA_RC = """!
vlan 100
   name SO101010
!
vlan 700
   name SO303030
!
vlan 2703
   name SO303033
!
interface Ethernet6
   switchport mode trunk
   switchport trunk allowed vlan 100
!
interface Ethernet7
   switchport mode trunk
   switchport trunk allowed vlan 700
   switchport vlan translation 11 dot1q-tunnel 700
   switchport vlan translation 21 dot1q-tunnel 700
   switchport vlan translation 31 dot1q-tunnel 700
!
interface Ethernet8
   switchport mode trunk
   switchport trunk allowed vlan 2703
   switchport vlan translation 703 2703
!
interface Vxlan1
   vxlan source-interface Loopback0
   vxlan vlan 100 vni 5000
   vxlan vlan 700 vni 7000
   vxlan vlan 2703 vni 7003
!
router bgp 65001
   vlan-aware-bundle SO101010
      rd 65001:101010
      route-target both 37195:101010
      vlan 100
   vlan-aware-bundle SO303030
      rd 65001:303030
      route-target both 37186:303030
      vlan 700
   vlan-aware-bundle SO303033
      rd 65001:303033
      route-target both 37186:303033
      vlan 2703
!
"""


class TestAristaReadBack:
    def setup_method(self):
        self.circuits = {
            c.evpn.vni: c for c in AristaConfigParser(ARISTA_RC).parse_evpn_circuits()
        }

    def test_plain_circuit(self):
        c = self.circuits[5000]
        assert isinstance(c.evpn, Evpn)
        # a plain Arista circuit just trunks the VLAN — the access port is not
        # reliably determinable from config, so it is intentionally None.
        assert c.interface is None
        assert c.evpn.vlan.vlan_id == 100
        assert c.evpn.description == "SO101010"
        assert c.routing_instance.rt_rd == "37195:101010"

    def test_azure_customer_multi_ctag(self):
        c = self.circuits[7000]
        assert isinstance(c.evpn, AzureEvpn)
        assert c.evpn.role == "customer"
        assert c.interface == "Ethernet7"
        assert c.evpn.s_tag == 700
        assert c.evpn.c_tags == [11, 21, 31]

    def test_azure_cni_rewrite(self):
        c = self.circuits[7003]
        assert isinstance(c.evpn, AzureEvpn)
        assert c.evpn.role == "cni"
        assert c.evpn.rewrite is True
        assert c.evpn.s_tag == 703          # Azure-provided
        assert c.evpn.internal_s_tag == 2703
        assert c.interface == "Ethernet8"

    def test_qinq_aggregation_falls_back_to_generic_circuit(self):
        # A shared cloud on-ramp S-TAG (AWS DX) aggregating >3 customer C-TAGs
        # exceeds the Azure customer model. Read-back must not abort the whole
        # device; it records a generic circuit preserving VNI/RT/VRF instead.
        rc = """!
interface Ethernet10
   switchport mode trunk
   switchport vlan translation 1762 dot1q-tunnel 4050
!
interface Ethernet11
   switchport mode trunk
   switchport vlan translation 2205 dot1q-tunnel 4050
!
interface Ethernet12
   switchport mode trunk
   switchport vlan translation 2321 dot1q-tunnel 4050
!
interface Ethernet13
   switchport mode trunk
   switchport vlan translation 2796 dot1q-tunnel 4050
!
interface Vxlan1
   vxlan source-interface Loopback0
   vxlan vlan 4050 vni 304050
!
router bgp 65001
   vlan-aware-bundle aws-dx-1-primary
      rd 65001:304050
      route-target both 37195:304050
      vlan 4050
!
"""
        (c,) = AristaConfigParser(rc).parse_evpn_circuits()
        assert isinstance(c.evpn, Evpn)        # not AzureEvpn
        assert c.evpn.vni == 304050
        assert c.evpn.description == "aws-dx-1-primary"
        assert c.routing_instance.rt_rd == "37195:304050"
        assert c.interface is None


# --------------------------------------------------------------------------- #
# OcNOS — render -> parse round-trip
# --------------------------------------------------------------------------- #
class TestOcnosRoundTrip:
    def test_plain_roundtrip(self):
        intent = Evpn(vlan=Vlan(vlan_id=30, name="SO9001"), asn=65003, vni=5001,
                      description="SO9001", service_type="cloud_vc")
        (c,) = _ocnos_roundtrip(intent, 37195)
        assert isinstance(c.evpn, Evpn)
        assert c.interface == "eth4"
        assert c.evpn.vni == 5001
        assert c.evpn.vlan.vlan_id == 30
        assert c.evpn.description == "SO9001"
        assert c.evpn.asn == 65003
        assert c.routing_instance.rt_rd == "37195:9001"

    def test_azure_customer_roundtrip(self):
        intent = AzureEvpn(description="SO9002", asn=65003, vni=7001, s_tag=701,
                           role="customer", c_tags=[11, 21])
        (c,) = _ocnos_roundtrip(intent, 37186)
        assert isinstance(c.evpn, AzureEvpn)
        assert c.evpn.role == "customer"
        assert c.evpn.s_tag == 701
        assert sorted(c.evpn.c_tags) == [11, 21]
        assert c.evpn.vni == 7001
        assert c.interface == "eth4"

    def test_azure_cni_rewrite_roundtrip(self):
        intent = AzureEvpn(description="SO9003", asn=65003, vni=7002, s_tag=702,
                           role="cni", rewrite=True)
        (c,) = _ocnos_roundtrip(intent, 37186)
        assert isinstance(c.evpn, AzureEvpn)
        assert c.evpn.role == "cni"
        assert c.evpn.rewrite is True
        assert c.evpn.s_tag == 702

    def test_qinq_aggregation_falls_back_to_generic_circuit(self):
        # >3 C-TAGs pushed into one shared S-TAG (AWS-DX-style aggregation) on a
        # single service. Built as two valid renders (3 + 1 c_tags) sharing the
        # S-TAG/VNI/VRF so they group into one 4-C-TAG circuit on read-back, which
        # exceeds the Azure model -> generic-circuit fallback (no device abort).
        r = OcnosDeviceRenderer()
        ri = RoutingInstance(instance_name="aws-dx-cust", instance_type="mac-vrf",
                             rd="65002:304050", rt_rd="37195:304050")
        a = AzureEvpn(description="aws-dx-cust", asn=65002, vni=304050, s_tag=4050,
                      role="customer", c_tags=[11, 21, 31])
        b = AzureEvpn(description="aws-dx-cust", asn=65002, vni=304050, s_tag=4050,
                      role="customer", c_tags=[41])
        tree = _ocnos_device_tree(
            r.render_routing_instance(Asn(asn=65002), ri),
            r.render_azure_evpn(Interface(name="eth4"), a),
            r.render_azure_evpn(Interface(name="eth4"), b),
        )
        (c,) = OcnosConfigXMLParser(tree).parse_evpn_circuits()
        assert isinstance(c.evpn, Evpn)        # not AzureEvpn
        assert c.evpn.vni == 304050
        assert c.evpn.description == "aws-dx-cust"
        assert c.routing_instance.instance_name == "aws-dx-cust"
        assert c.routing_instance.rt_rd == "37195:304050"

    def test_blank_subinterface_description_recovers_vrf(self):
        # A sub-interface with an EVPN binding but no `description` reads back with
        # description="" — but its VRF (service identity) is still recovered from
        # the VXLAN tenant mapping, so the audit keys it correctly rather than
        # treating it as an unnamed, conflicting service.
        r = OcnosDeviceRenderer()
        intent = Evpn(vlan=Vlan(vlan_id=425, name="vlan-425"), asn=65001,
                      vni=210425, description="vlan-425")
        ri = _ri("vlan-425", 65001, 37195)
        tree = _ocnos_device_tree(
            r.render_routing_instance(Asn(asn=65001), ri),
            r.render_evpn(Interface(name="eth4"), intent),
        )
        # Drop the access sub-interface's description to simulate an undescribed
        # port (the VXLAN tenant's vrf-name is in a different namespace, untouched).
        oc_desc = "{http://www.ipinfusion.com/yang/ocnos/ipi-interface}description"
        for desc in list(tree.iter(oc_desc)):
            desc.getparent().remove(desc)

        (c,) = OcnosConfigXMLParser(tree).parse_evpn_circuits()
        assert c.evpn.vni == 210425
        assert c.evpn.description == ""  # the port genuinely has no description
        assert c.routing_instance is not None
        assert c.routing_instance.instance_name == "vlan-425"


# --------------------------------------------------------------------------- #
# Mixed Arista/OcNOS fabric — the audit must collapse the two ends of one
# service even across platforms (and even when one end's port has no description)
# --------------------------------------------------------------------------- #
# Arista end of service "SO500500": vlan-aware-bundle named by the service key,
# exactly as create_circuit enforces (instance_name == description).
ARISTA_RC_500 = """!
vlan 50
   name SO500500
!
interface Ethernet9
   switchport mode trunk
   switchport trunk allowed vlan 50
!
interface Vxlan1
   vxlan source-interface Loopback0
   vxlan vlan 50 vni 20500
!
router bgp 65001
   vlan-aware-bundle SO500500
      rd 65001:500500
      route-target both 37195:500500
      vlan 50
!
"""


class TestMixedFabricAudit:
    def _ocnos_end(self, *, blank_description: bool):
        # OcNOS end of the same service "SO500500" — same VNI, same fabric RT,
        # different device ASN (each device's rd uses its own ASN).
        r = OcnosDeviceRenderer()
        intent = Evpn(vlan=Vlan(vlan_id=50, name="SO500500"), asn=65002,
                      vni=20500, description="SO500500")
        ri = _ri("SO500500", 65002, 37195)
        tree = _ocnos_device_tree(
            r.render_routing_instance(Asn(asn=65002), ri),
            r.render_evpn(Interface(name="eth4"), intent),
        )
        if blank_description:
            oc_desc = "{http://www.ipinfusion.com/yang/ocnos/ipi-interface}description"
            for desc in list(tree.iter(oc_desc)):
                desc.getparent().remove(desc)
        return OcnosConfigXMLParser(tree).parse_evpn_circuits()

    def test_same_service_across_platforms_is_not_a_collision(self):
        arista = AristaConfigParser(ARISTA_RC_500).parse_evpn_circuits()
        ocnos = self._ocnos_end(blank_description=False)
        conflicts = find_conflicts(arista + ocnos)
        assert conflicts["vni_collisions"] == {}
        assert conflicts["rt_collisions"] == {}

    def test_blank_ocnos_end_across_platforms_is_not_a_collision(self):
        # The real-world bug: the OcNOS access port has no description, so its
        # description reads back as "". Keying on the VRF name (recovered via the
        # VXLAN tenant mapping) still collapses it onto the Arista end.
        arista = AristaConfigParser(ARISTA_RC_500).parse_evpn_circuits()
        ocnos = self._ocnos_end(blank_description=True)
        assert ocnos[0].evpn.description == ""
        assert ocnos[0].routing_instance.instance_name == "SO500500"
        conflicts = find_conflicts(arista + ocnos)
        assert conflicts["vni_collisions"] == {}
        assert conflicts["rt_collisions"] == {}


# --------------------------------------------------------------------------- #
# verify_circuit — drift detection
# --------------------------------------------------------------------------- #
class TestVerifyCircuit:
    def _mgr(self):
        return EvpnManager(_FakeDriver("arista_eos", ARISTA_RC))

    def test_match(self):
        intent = Evpn(vlan=Vlan(vlan_id=100, name="SO101010"), asn=65001, vni=5000,
                      description="SO101010", service_type="cloud_vc")
        ri = _ri("SO101010", 65001, 37195)
        d = self._mgr().verify_circuit("Ethernet6", intent, ri)
        assert d.present and d.matches and d.differences == []

    def test_drift_reports_fields(self):
        intent = Evpn(vlan=Vlan(vlan_id=999, name="SO101010"), asn=65001, vni=5000,
                      description="SO101010")
        ri = _ri("SO101010", 65001, 37195)
        ri.rt_rd = "37195:000000"
        d = self._mgr().verify_circuit("Ethernet6", intent, ri)
        assert d.present and not d.matches
        joined = " ".join(d.differences)
        assert "vlan" in joined and "rt" in joined

    def test_missing(self):
        intent = Evpn(vlan=Vlan(vlan_id=1), asn=1, vni=424242, description="X")
        d = self._mgr().verify_circuit("Ethernet6", intent)
        assert not d.present and not d.matches

    def test_azure_customer_match(self):
        intent = AzureEvpn(description="SO303030", asn=65001, vni=7000, s_tag=700,
                           role="customer", c_tags=[11, 21, 31])
        d = self._mgr().verify_circuit("Ethernet7", intent, _ri("SO303030", 65001, 37186))
        assert d.present and d.matches, d.differences


# Bundle-less leaf: VXLAN vlan->vni mappings with `vlan <id> / name <service>` but
# NO vlan-aware-bundle / EVPN rd-rt in `router bgp` (observed on some EOS leaf
# roles, e.g. ar-*.ct1). parse_evpns must still recover one EVPN per mapping,
# using the device BGP ASN and the VLAN name as the service identifier.
ARISTA_RC_BUNDLELESS = """! Command: show running-config
!
vlan 920
   name SO108883
!
vlan 2450
   name SO115152
!
vlan 800
   name quarantine
!
interface Vxlan1
   vxlan source-interface Loopback0
   vxlan vlan 920 vni 15920
   vxlan vlan 2450 vni 12450
   vxlan vlan 800 vni 10800
!
router bgp 64603
   router-id 172.16.100.3
   neighbor SPINE peer group
   address-family ipv4
      neighbor SPINE activate
!
"""


class TestAristaBundlelessEvpn:
    def setup_method(self):
        cfg = AristaConfigParser(ARISTA_RC_BUNDLELESS).parse_config()
        self.evpns = {e.vlan.vlan_id: e for e in cfg.evpns}

    def test_named_vlans_recovered_without_bundle(self):
        # the service VLANs are emitted despite no vlan-aware-bundle / rd-rt
        assert 920 in self.evpns and 2450 in self.evpns
        e = self.evpns[920]
        assert e.vlan.name == "SO108883"
        assert e.description == "SO108883"   # service id, taken from the VLAN name
        assert e.vni == 15920
        assert e.asn == 64603                # device BGP ASN, since there is no rd

    def test_infra_named_vlan_also_emitted_but_harmless(self):
        # 'quarantine' has a name so it is emitted; it carries no service id, so
        # the ACX sync's _service_order_id / cloud-key match simply skips it.
        assert self.evpns[800].description == "quarantine"
