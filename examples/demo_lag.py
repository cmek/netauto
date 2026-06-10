"""Offline LAG demo using the MockDriver (no device required).

Shows the port-list building blocks (create_lag / delete_lag) and VLAN
migration onto the Port-Channel for a brownfield trunk scenario.
"""

from netauto.models import Interface, Vlan
from netauto.drivers import MockDriver
from netauto.logic import LagManager


def main():
    # Brownfield scenario: Ethernet1 trunks VLANs 10,20; Ethernet2 trunks 20,30.
    switchports = [
        Interface(
            name="Ethernet1",
            mode="trunk",
            trunk_vlans=[Vlan(vlan_id=10), Vlan(vlan_id=20)],
        ),
        Interface(
            name="Ethernet2",
            mode="trunk",
            trunk_vlans=[Vlan(vlan_id=20), Vlan(vlan_id=30)],
        ),
        Interface(name="Ethernet3", mode="access", access_vlan=40),
    ]

    driver = MockDriver(platform="arista_eos", initial_switchports=switchports)
    manager = LagManager(driver)

    print("--- Initial switchport state ---")
    for name, intf in driver.get_switchports().items():
        vlans = [v.vlan_id for v in intf.trunk_vlans] or intf.access_vlan
        print(f"{name}: mode={intf.mode}, vlans={vlans}")

    print("\n--- create_lag Port-Channel10 <- Ethernet1, Ethernet2 ---")
    diff = manager.create_lag(
        lag_name="Port-Channel10",
        member_ports=["Ethernet1", "Ethernet2"],
        description="SO12345",
    )
    print(diff)

    print("\n--- delete_lag Port-Channel10 (plain split) ---")
    diff = manager.delete_lag(
        lag_name="Port-Channel10", member_ports=["Ethernet1", "Ethernet2"]
    )
    print(diff)


if __name__ == "__main__":
    main()
