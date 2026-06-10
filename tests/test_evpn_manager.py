import pytest

from netauto.drivers import MockDriver
from netauto.evpn import EvpnManager
from netauto.exceptions import NetAutoException
from netauto.models import Asn, Evpn, Interface, RoutingInstance, Vlan


def _arista_driver(vnis=None):
    return MockDriver(
        platform="arista_eos",
        initial_interfaces=[Interface(name="Ethernet6")],
        initial_switchports=[Interface(name="Ethernet6", mode="trunk")],
        initial_vnis=vnis or {},
    )


def _ocnos_driver(vnis=None):
    return MockDriver(
        platform="ipinfusion_ocnos",
        initial_interfaces=[Interface(name="eth4")],
        initial_switchports=[Interface(name="eth4", mode="trunk")],
        initial_vnis=vnis or {},
    )


def _evpn(service_type="p2p_vc", vni=5000, vlan_id=100, service_key="SO555"):
    return Evpn(
        vlan=Vlan(vlan_id=vlan_id, name=service_key),
        asn=65001,
        vni=vni,
        description=service_key,
        service_type=service_type,
    )


def _ri(service_key="SO555"):
    return RoutingInstance(
        instance_name=service_key,
        instance_type="mac-vrf",
        rd=f"65001:{service_key[2:]}",
        rt_rd=f"37195:{service_key[2:]}",
    )


class TestEvpnManagerArista:
    def test_create_circuit_pushes_vrf_and_evpn(self):
        driver = _arista_driver()
        mgr = EvpnManager(driver)
        mgr.create_circuit("Ethernet6", _evpn(), routing_instance=_ri())
        pushed = "\n".join(driver.pushed_commands)
        # VRF (vlan-aware-bundle with rd/rt) + the circuit
        assert "vlan-aware-bundle SO555" in pushed
        assert "rd 65001:555" in pushed
        assert "vxlan vlan 100 vni 5000" in pushed  # p2p -> plain vni

    def test_cloud_vc_uses_vni_verbatim(self):
        driver = _arista_driver()
        EvpnManager(driver).create_circuit(
            "Ethernet6", _evpn(service_type="cloud_vc"), routing_instance=_ri()
        )
        # VNI is passed in whole; service_type does not alter it
        assert "vxlan vlan 100 vni 5000" in "\n".join(driver.pushed_commands)

    def test_create_without_vrf_skips_routing_instance(self):
        driver = _arista_driver()
        EvpnManager(driver).create_circuit(
            "Ethernet6", _evpn(), create_vrf=False
        )
        pushed = "\n".join(driver.pushed_commands)
        assert "rd 65001:555" not in pushed
        assert "vxlan vlan 100 vni 5000" in pushed

    def test_vni_in_use_raises(self):
        driver = _arista_driver(vnis={5000: {"vlan_id": 100}})
        with pytest.raises(NetAutoException):
            EvpnManager(driver).create_circuit(
                "Ethernet6", _evpn(), routing_instance=_ri()
            )

    def test_unknown_interface_raises(self):
        driver = _arista_driver()
        with pytest.raises(NetAutoException):
            EvpnManager(driver).create_circuit(
                "Ethernet99", _evpn(), routing_instance=_ri()
            )

    def test_mismatched_bundle_name_raises(self):
        driver = _arista_driver()
        with pytest.raises(NetAutoException):
            EvpnManager(driver).create_circuit(
                "Ethernet6", _evpn(service_key="SO555"), routing_instance=_ri("SO999")
            )

    def test_create_vrf_requires_routing_instance(self):
        driver = _arista_driver()
        with pytest.raises(NetAutoException):
            EvpnManager(driver).create_circuit("Ethernet6", _evpn())

    def test_dry_run_records_nothing(self):
        driver = _arista_driver()
        diff = EvpnManager(driver).create_circuit(
            "Ethernet6", _evpn(), routing_instance=_ri(), dry_run=True
        )
        assert driver.pushed_commands == []
        assert "vxlan vlan 100 vni 5000" in diff

    def test_delete_circuit(self):
        driver = _arista_driver()
        EvpnManager(driver).delete_circuit(
            "Ethernet6", _evpn(), routing_instance=_ri(), delete_vrf=True
        )
        pushed = "\n".join(driver.pushed_commands)
        assert "no vxlan vlan 100 vni 5000" in pushed
        assert "no vlan-aware-bundle SO555" in pushed


class TestEvpnManagerOcnos:
    def test_create_circuit_pushes_vrf_and_evpn(self):
        driver = _ocnos_driver()
        EvpnManager(driver).create_circuit("eth4", _evpn(), routing_instance=_ri())
        pushed = "\n".join(driver.pushed_commands)
        assert "<netinst:instance-name>SO555</netinst:instance-name>" in pushed
        assert "<vxlan:vxlan-identifier>5000</vxlan:vxlan-identifier>" in pushed

    def test_cloud_vc_uses_vni_verbatim(self):
        driver = _ocnos_driver()
        EvpnManager(driver).create_circuit(
            "eth4", _evpn(service_type="cloud_vc"), routing_instance=_ri()
        )
        assert "<vxlan:vxlan-identifier>5000</vxlan:vxlan-identifier>" in "\n".join(
            driver.pushed_commands
        )

    def test_dry_run_records_nothing(self):
        driver = _ocnos_driver()
        EvpnManager(driver).create_circuit(
            "eth4", _evpn(), routing_instance=_ri(), dry_run=True
        )
        assert driver.pushed_commands == []

    def test_vni_in_use_list_form_raises(self):
        # OcNOS get_vnis() returns a list[int], not a dict; the guard handles both
        driver = _ocnos_driver()
        driver.get_vnis = lambda: [5000]
        with pytest.raises(NetAutoException):
            EvpnManager(driver).create_circuit(
                "eth4", _evpn(), routing_instance=_ri()
            )
