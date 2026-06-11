import pytest

from netauto.allocation import (
    JsonFileRegistry,
    find_conflicts,
    make_routing_instance,
    service_number,
)
from netauto.exceptions import RtCollision, VniInUse
from netauto.models import AzureEvpn, Evpn, EvpnCircuit, RoutingInstance, Vlan


def _circuit(service_key, vni, rt):
    return EvpnCircuit(
        evpn=Evpn(vlan=Vlan(vlan_id=10), asn=1, vni=vni, description=service_key),
        routing_instance=RoutingInstance(
            instance_name=service_key, instance_type="mac-vrf", rd="1:1", rt_rd=rt
        ),
    )


class TestIdentifiers:
    def test_service_number(self):
        assert service_number("SO123456") == "123456"

    def test_make_routing_instance(self):
        ri = make_routing_instance("SO123456", device_asn=65001, rt_asn=37195)
        assert ri.rd == "65001:123456"
        assert ri.rt_rd == "37195:123456"
        assert ri.instance_name == "SO123456"


class TestFindConflicts:
    def test_same_service_two_ends_is_not_a_conflict(self):
        circuits = [_circuit("SOA", 5000, "37195:A"), _circuit("SOA", 5000, "37195:A")]
        conflicts = find_conflicts(circuits)
        assert conflicts["vni_collisions"] == {}
        assert conflicts["rt_collisions"] == {}

    def test_same_vni_different_service_is_a_collision(self):
        circuits = [_circuit("SOA", 5000, "37195:A"), _circuit("SOB", 5000, "37195:B")]
        conflicts = find_conflicts(circuits)
        assert conflicts["vni_collisions"] == {5000: ["SOA", "SOB"]}

    def test_same_rt_different_service_is_a_collision(self):
        circuits = [_circuit("SOA", 5000, "37195:X"), _circuit("SOB", 5001, "37195:X")]
        conflicts = find_conflicts(circuits)
        assert conflicts["rt_collisions"] == {"37195:X": ["SOA", "SOB"]}


class TestJsonFileRegistry:
    def _reg(self, tmp_path):
        return JsonFileRegistry(tmp_path / "vni.json", base_vni=10000)

    def test_allocate_is_unique_and_idempotent(self, tmp_path):
        reg = self._reg(tmp_path)
        a = reg.allocate("SOA")
        b = reg.allocate("SOB")
        assert a == 10000 and b == 10001
        assert reg.allocate("SOA") == a  # idempotent
        assert reg.get("SOA") == a

    def test_release_frees_the_vni(self, tmp_path):
        reg = self._reg(tmp_path)
        reg.allocate("SOA")
        reg.release("SOA")
        assert reg.get("SOA") is None
        # next allocation reuses the freed slot
        assert reg.allocate("SOB") == 10000

    def test_rt_collision_raises(self, tmp_path):
        reg = self._reg(tmp_path)
        reg.allocate("SOA", rt="37195:1")
        with pytest.raises(RtCollision):
            reg.allocate("SOB", rt="37195:1")

    def test_persists_across_instances(self, tmp_path):
        path = tmp_path / "vni.json"
        JsonFileRegistry(path).allocate("SOA")
        assert JsonFileRegistry(path).get("SOA") == 10000

    def test_seed_from_circuits(self, tmp_path):
        reg = self._reg(tmp_path)
        reg.seed_from_circuits(
            [_circuit("SOA", 5000, "37195:A"), _circuit("SOB", 5001, "37195:B")]
        )
        assert reg.get("SOA") == 5000 and reg.get("SOB") == 5001

    def test_seed_detects_vni_collision(self, tmp_path):
        reg = self._reg(tmp_path)
        with pytest.raises(VniInUse):
            reg.seed_from_circuits(
                [_circuit("SOA", 5000, "37195:A"), _circuit("SOB", 5000, "37195:B")]
            )
