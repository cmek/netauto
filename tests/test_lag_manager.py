import pytest
from netauto.models import Interface, Vlan
from netauto.drivers import MockDriver
from netauto.logic import LagManager
from netauto.exceptions import NetAutoException


class TestLagManagerArista:
    def _driver(self):
        return MockDriver(
            platform="arista_eos",
            initial_switchports=[
                Interface(
                    name="Ethernet3",
                    mode="trunk",
                    trunk_vlans=[Vlan(vlan_id=10), Vlan(vlan_id=20)],
                ),
                Interface(
                    name="Ethernet4",
                    mode="trunk",
                    trunk_vlans=[Vlan(vlan_id=20), Vlan(vlan_id=30)],
                ),
            ],
        )

    def test_create_lag_migrates_trunk_vlans(self):
        driver = self._driver()
        mgr = LagManager(driver)
        mgr.create_lag(
            "Port-Channel10",
            ["Ethernet3", "Ethernet4"],
            description="SO12345",
        )
        pushed = "\n".join(driver.pushed_commands)
        # VLANs from both members are de-duped onto the Port-Channel
        assert "switchport trunk allowed vlan 10,20,30" in pushed
        assert "channel-group 10 mode active" in pushed
        assert "interface Port-Channel10" in pushed

    def test_create_lag_plain_when_migration_disabled(self):
        driver = self._driver()
        mgr = LagManager(driver)
        mgr.create_lag(
            "Port-Channel10", ["Ethernet3", "Ethernet4"], migrate_vlans=False
        )
        pushed = "\n".join(driver.pushed_commands)
        assert "switchport" not in pushed
        assert "channel-group 10 mode active" in pushed

    def test_delete_lag_plain_split(self):
        driver = self._driver()
        mgr = LagManager(driver)
        mgr.delete_lag("Port-Channel10", ["Ethernet3", "Ethernet4"])
        pushed = "\n".join(driver.pushed_commands)
        assert "no channel-group" in pushed
        assert "no interface Port-Channel10" in pushed

    def test_dry_run_records_nothing(self):
        driver = self._driver()
        mgr = LagManager(driver)
        diff = mgr.create_lag(
            "Port-Channel10", ["Ethernet3", "Ethernet4"], dry_run=True
        )
        assert driver.pushed_commands == []
        assert "Port-Channel10" in diff

    def test_unknown_port_raises(self):
        driver = self._driver()
        mgr = LagManager(driver)
        with pytest.raises(NetAutoException):
            mgr.create_lag("Port-Channel10", ["Ethernet3", "Ethernet99"])

    def test_already_member_raises(self):
        driver = MockDriver(
            platform="arista_eos",
            initial_switchports=[
                Interface(name="Ethernet3", lag_member_of="Port-Channel1"),
            ],
        )
        mgr = LagManager(driver)
        with pytest.raises(NetAutoException):
            mgr.create_lag("Port-Channel10", ["Ethernet3"])


class TestLagManagerOcnos:
    def _driver(self):
        return MockDriver(
            platform="ipinfusion_ocnos",
            initial_switchports=[
                Interface(name="eth3", mode="trunk", trunk_vlans=[Vlan(vlan_id=10)]),
                Interface(name="eth4", mode="trunk", trunk_vlans=[Vlan(vlan_id=20)]),
            ],
        )

    def test_create_lag_bundles_and_moves_subinterfaces(self):
        driver = self._driver()
        mgr = LagManager(driver)
        mgr.create_lag("po10", ["eth3", "eth4"], description="SO12345")

        # 1 bundle payload + (create po.vlan + delete member.vlan) per member VLAN
        assert len(driver.pushed_commands) == 1 + 2 * 2
        bundle = driver.pushed_commands[0]
        assert "<if:name>po10</if:name>" in bundle
        joined = "\n".join(driver.pushed_commands)
        assert "<if:name>po10.10</if:name>" in joined
        assert "<if:name>po10.20</if:name>" in joined
        # member sub-interfaces are removed
        assert "eth3.10" in joined
        assert "eth4.20" in joined

    def test_create_lag_plain_when_migration_disabled(self):
        driver = self._driver()
        mgr = LagManager(driver)
        mgr.create_lag("po10", ["eth3", "eth4"], migrate_vlans=False)
        assert len(driver.pushed_commands) == 1
        assert "<if:name>po10</if:name>" in driver.pushed_commands[0]

    def test_delete_lag_plain_split(self):
        driver = self._driver()
        mgr = LagManager(driver)
        mgr.delete_lag("po10", ["eth3", "eth4"])
        joined = "\n".join(driver.pushed_commands)
        assert 'nc:operation="remove"' in joined
        assert "<if:name>po10</if:name>" in joined
