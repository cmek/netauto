import pytest
from lxml import etree
from netauto.models import Interface, Vlan, Lag
from netauto.drivers import MockDriver, OcnosDriver


class _FakeReply:
    """Minimal stand-in for an ncclient GetReply (only .data_ele is used)."""

    def __init__(self, root: etree._Element):
        self.data_ele = root


class TestOcnosDriver:
    """Tests for the ocnos driver"""

    def test_ocnos_extract_interfaces(self):
        """Test interface extraction logic from ocnos netconf response."""
        # Bypass __init__ so we don't open a real NETCONF connection.
        driver = OcnosDriver.__new__(OcnosDriver)

        with open("tests/ocnos_interfaces.xml") as f:
            data = f.read()

        root = etree.fromstring(data.encode())
        interfaces = driver._extract_interfaces(_FakeReply(root))

        by_name = {i.name: i for i in interfaces}
        assert "eth0" in by_name
        assert "po10" in by_name
        # po10 is an aggregate with eth3 as a member
        assert isinstance(by_name["po10"], Lag)
        assert by_name["po10"].members == ["eth3"]
        assert by_name["eth3"].lag_member_of == "po10"

    def test_ocnos_extract_vnis(self):
        """Parse configured VNIs from a vxlan get-reply.

        Regression guard: get_vnis() previously used findtext() with a
        local-name() predicate, which lxml ElementPath rejects ("invalid
        predicate"), so it always errored and returned []. The VNI-in-use guard
        in EvpnManager relies on this, so it must actually parse.
        """
        with open("tests/ocnos_vxlan.xml") as f:
            root = etree.fromstring(f.read().encode())

        vnis = OcnosDriver._extract_vnis(_FakeReply(root))
        assert vnis == [10010, 10020]

    def test_ocnos_extract_vnis_empty(self):
        """No vxlan tenants -> empty list (not an error)."""
        root = etree.fromstring(
            b'<data xmlns="urn:ietf:params:xml:ns:netconf:base:1.0"/>'
        )
        assert OcnosDriver._extract_vnis(_FakeReply(root)) == []


class TestMockDriver:
    """Test suite for MockDriver functionality."""

    def test_mock_driver_initialization(self):
        """Test MockDriver initialization."""
        driver = MockDriver()
        assert len(driver.interfaces) == 0
        assert len(driver.vlans) == 0
        assert len(driver.pushed_commands) == 0

    def test_mock_driver_with_initial_interfaces(self):
        """Test MockDriver with initial interfaces."""
        interfaces = [
            Interface(
                name="Ethernet1",
                mode="trunk",
                trunk_vlans=[Vlan(vlan_id=10), Vlan(vlan_id=20)],
            ),
            Interface(name="Ethernet2", mode="access", access_vlan=100),
        ]
        driver = MockDriver(initial_interfaces=interfaces)

        assert len(driver.interfaces) == 2
        assert "Ethernet1" in driver.interfaces
        assert "Ethernet2" in driver.interfaces
        assert [v.vlan_id for v in driver.interfaces["Ethernet1"].trunk_vlans] == [10, 20]

    def test_mock_driver_with_initial_vlans(self):
        """Test MockDriver with initial VLANs."""
        vlans = [
            Vlan(vlan_id=10, name="VLAN10"),
            Vlan(vlan_id=20, name="VLAN20"),
        ]
        driver = MockDriver(initial_vlans=vlans)

        assert len(driver.vlans) == 2
        assert 10 in driver.vlans
        assert 20 in driver.vlans
        assert driver.vlans[10].name == "VLAN10"

    def test_get_interfaces(self):
        """Test get_interfaces method."""
        interfaces = [Interface(name="Ethernet1")]
        driver = MockDriver(initial_interfaces=interfaces)

        result = driver.get_interfaces()
        assert result == driver.interfaces
        assert "Ethernet1" in result

    def test_get_vlans(self):
        """Test get_vlans method."""
        vlans = [Vlan(vlan_id=100, name="Test")]
        driver = MockDriver(initial_vlans=vlans)

        result = driver.get_vlans()
        assert result == driver.vlans
        assert 100 in result

    def test_get_switchports(self):
        """Test get_switchports returns per-port switchport state."""
        ports = [
            Interface(
                name="Ethernet1",
                mode="trunk",
                trunk_vlans=[Vlan(vlan_id=10), Vlan(vlan_id=20)],
            ),
            Interface(name="Ethernet2", mode="access", access_vlan=100),
        ]
        driver = MockDriver(initial_switchports=ports)

        result = driver.get_switchports()
        assert "Ethernet1" in result
        assert result["Ethernet2"].access_vlan == 100

    def test_push_config(self):
        """Test push_config method."""
        driver = MockDriver()
        commands = ["interface Ethernet1", "no shutdown", "exit"]

        driver.push_config(commands)

        assert len(driver.pushed_commands) == 3
        assert driver.pushed_commands == commands

    def test_push_config_dry_run_records_nothing(self):
        """A dry run should not accumulate commands."""
        driver = MockDriver()
        driver.push_config(["interface Ethernet1"], dry_run=True)
        assert driver.pushed_commands == []

    def test_push_config_multiple_times(self):
        """Test pushing config multiple times accumulates commands."""
        driver = MockDriver()

        driver.push_config(["command1", "command2"])
        driver.push_config(["command3", "command4"])

        assert len(driver.pushed_commands) == 4
        assert driver.pushed_commands == [
            "command1",
            "command2",
            "command3",
            "command4",
        ]

    def test_connect_disconnect(self):
        """Test connect and disconnect methods."""
        driver = MockDriver()

        # These should not raise exceptions
        driver.connect()
        driver.disconnect()

    def test_mock_driver_state_isolation(self):
        """Test that multiple MockDriver instances have isolated state."""
        driver1 = MockDriver(initial_interfaces=[Interface(name="Eth1")])
        driver2 = MockDriver(initial_interfaces=[Interface(name="Eth2")])

        assert "Eth1" in driver1.interfaces
        assert "Eth1" not in driver2.interfaces
        assert "Eth2" in driver2.interfaces
        assert "Eth2" not in driver1.interfaces
