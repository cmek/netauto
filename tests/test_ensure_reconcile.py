"""Declarative ensure (idempotency) + plan_reconcile tests."""

from netauto.drivers import MockDriver
from netauto.evpn import EvpnManager, plan_reconcile
from netauto.models import Evpn, EvpnCircuit, Interface, RoutingInstance, Vlan


def _rc(vlan, vni):
    return f"""!
vlan {vlan}
   name SO101010
!
interface Vxlan1
   vxlan vlan {vlan} vni {vni}
!
router bgp 65001
   vlan-aware-bundle SO101010
      rd 65001:101010
      route-target both 37195:101010
      vlan {vlan}
!
"""


def _driver(running_config: str):
    d = MockDriver(
        platform="arista_eos",
        initial_interfaces=[Interface(name="Ethernet6")],
        initial_switchports=[Interface(name="Ethernet6", mode="trunk")],
    )
    d.get_config = lambda: running_config  # what get_circuits/verify read back
    return d


INTENT = Evpn(vlan=Vlan(vlan_id=100, name="SO101010"), asn=65001, vni=5000,
              description="SO101010", service_type="cloud_vc")
RI = RoutingInstance(instance_name="SO101010", instance_type="mac-vrf",
                     rd="65001:101010", rt_rd="37195:101010")


class TestEnsureCircuit:
    def test_creates_when_absent(self):
        d = _driver("")  # nothing on the device
        res = EvpnManager(d).ensure_circuit("Ethernet6", INTENT, RI)
        assert res.action == "created"
        assert d.pushed_commands  # a push happened

    def test_unchanged_when_matches(self):
        d = _driver(_rc(100, 5000))
        res = EvpnManager(d).ensure_circuit("Ethernet6", INTENT, RI)
        assert res.action == "unchanged"
        assert d.pushed_commands == []  # idempotent: no push

    def test_updates_when_drifted(self):
        d = _driver(_rc(200, 5000))  # same VNI, wrong VLAN
        res = EvpnManager(d).ensure_circuit("Ethernet6", INTENT, RI)
        assert res.action == "updated"
        assert any("vlan" in diff for diff in res.differences)
        assert d.pushed_commands  # re-applied to converge


def _circuit(vni, vlan, key="SO1", rt="37195:1", interface="eth4"):
    return EvpnCircuit(
        evpn=Evpn(vlan=Vlan(vlan_id=vlan), asn=1, vni=vni, description=key),
        routing_instance=RoutingInstance(instance_name=key, instance_type="mac-vrf",
                                         rd="1:1", rt_rd=rt),
        interface=interface,
    )


class TestPlanReconcile:
    def test_to_create_and_in_sync_and_delete(self):
        intended = [_circuit(5000, 100), _circuit(5001, 101, key="SO2")]
        actual = [_circuit(5001, 101, key="SO2"), _circuit(9999, 50, key="SOX")]
        plan = plan_reconcile(intended, actual)
        assert plan.to_create == [5000]      # intended, not on device
        assert plan.in_sync == [5001]        # present and matching
        assert plan.to_delete == [9999]      # on device, not intended
        assert plan.to_update == {}

    def test_to_update_reports_drift(self):
        intended = [_circuit(5000, 100, rt="37195:1")]
        actual = [_circuit(5000, 200, rt="37195:999")]  # vlan + rt drifted
        plan = plan_reconcile(intended, actual)
        assert 5000 in plan.to_update
        joined = " ".join(plan.to_update[5000])
        assert "vlan" in joined and "rt" in joined
