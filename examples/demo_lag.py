from netauto.models import Interface, Vlan
from netauto.drivers import MockDriver
from netauto.logic import LagManager

def main():
    # 1. Setup Initial State (Brownfield Scenario)
    # Ethernet1 has VLANs 10, 20
    # Ethernet2 has VLANs 20, 30
    initial_interfaces = [
        Interface(name="Ethernet1", mode="trunk", trunk_vlans=[10, 20]),
        Interface(name="Ethernet2", mode="trunk", trunk_vlans=[20, 30]),
        Interface(name="Ethernet3", mode="access", access_vlan=40),
    ]
    
    driver = MockDriver(initial_interfaces=initial_interfaces)
    manager = LagManager(driver)

    print("--- Initial State ---")
    for name, intf in driver.get_interfaces().items():
        print(f"{name}: Mode={intf.mode}, VLANs={intf.trunk_vlans or intf.access_vlan}")

    print("\n--- Migrating Ethernet1 and Ethernet2 to Port-Channel10 ---")
    try:
        commands = manager.create_lag(
            lag_name="Port-Channel10",
            member_ports=["Ethernet1", "Ethernet2"]
        )
        
        manager.apply(commands)
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
