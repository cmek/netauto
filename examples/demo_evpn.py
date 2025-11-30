from netauto.models import EvpnService, Vrf
from netauto.drivers import MockDriver
from netauto.evpn import EvpnManager


def main():
    # 1. Setup Mock Driver (No initial state needed for this stateless config gen POC)
    driver = MockDriver()
    manager = EvpnManager(driver)

    # 2. Define Service Parameters
    vrf = Vrf(
        name="PROD_A",
        rd="10.1.1.11:10010",
        rt_import=["65001:10010"],
        rt_export=["65001:10010"],
    )

    service = EvpnService(vlan_id=10, vni=10010, vrf_name="PROD_A")

    print(
        f"--- Deploying EVPN Service VNI {service.vni} for VLAN {service.vlan_id} ---"
    )

    # 3. Generate and Apply Config
    commands = manager.deploy_service(service, vrf)
    manager.apply(commands)


if __name__ == "__main__":
    main()
