import os
import logging
from netauto.drivers import AristaDriver, OcnosDriver
from netauto.logic import LagManager, InterfaceManager
from netauto.evpn import EvpnManager
from netauto.models import EvpnService, Vrf, Vlan
from netauto.exceptions import NetAutoException

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def main():
    # Configuration
    arista_host = os.getenv("ARISTA_HOST", "172.20.30.4")
    ocnos_host = os.getenv("OCNOS_HOST", "172.20.30.6")
    username = os.getenv("DEVICE_USER", "admin")
    password = os.getenv("DEVICE_PASSWORD", "admin@123")

    logger.info("Starting Live Device Demo")
    logger.info(f"Arista Host: {arista_host}")
    logger.info(f"OcNOS Host: {ocnos_host}")

    # --- Arista Demo ---
#    try:
#        logger.info("Connecting to Arista...")
#        arista = AristaDriver(host=arista_host, user=username, password=password)
#        arista.connect()
#        logger.info("Connected to Arista!")
#
#        # Read state
#        interfaces = arista.get_interfaces()
#        logger.info(f"Retrieved {len(interfaces)} interfaces from Arista")
#
#        vlans = arista.get_vlans()
#        logger.info(f"Retrieved {len(vlans)} VLANs from Arista")
#
#        # Demo: Create a test VLAN
#        logger.info("Creating Test VLAN 999 on Arista...")
#        # Note: We don't have a VlanManager, but we can use EvpnManager or just push config
#        # Let's use a simple config push for this demo part or use the managers if applicable
#        # The project structure implies using Managers.
#
#        # Let's try to deploy an EVPN service as a test
#        evpn_mgr = EvpnManager(arista)
#        vrf = Vrf(
#            name="DEMO_VRF",
#            rd="10.1.1.1:999",
#            rt_import=["65001:999"],
#            rt_export=["65001:999"],
#        )
#        service = EvpnService(vlan_id=999, vni=99999, vrf_name="DEMO_VRF", s_tag=100)
#
#        logger.info("Generating EVPN configuration...")
#        commands = evpn_mgr.deploy_service(service, vrf)
#        for cmd in commands:
#            logger.info(f"  CMD: {cmd}")
#
#        # Uncomment to actually apply
#        # logger.info("Applying configuration...")
#        # evpn_mgr.apply(commands)
#
#        arista.disconnect()
#        logger.info("Disconnected from Arista")
#
#    except Exception as e:
#        logger.error(f"Arista Demo Failed: {e}")
#
    # --- OcNOS Demo ---
    try:
        logger.info("Connecting to OcNOS...")
        ocnos = OcnosDriver(host=ocnos_host, user=username, password=password)
        ocnos.connect()
        logger.info("Connected to OcNOS!")

        # Read state
        interfaces = ocnos.get_interfaces()
        logger.info(f"Retrieved {len(interfaces)} interfaces from OcNOS")

        # Demo: Create a LAG
        logger.info("Generating LAG configuration for OcNOS...")
        lag_mgr = LagManager(ocnos)
        lag_cmds = lag_mgr.create_lag("po10", ["eth3", "eth4"])
        for cmd in lag_cmds:
            logger.info(f"  CMD: {cmd}")

        lag_mgr.apply(lag_cmds)

        # set the right description on the lag interface
#        iface = InterfaceManager(ocnos, "po10")
#        iface.description = "test123"
#        iface.apply()

        ocnos.disconnect()
        logger.info("Disconnected from OcNOS")

    except Exception as e:
        logger.error(f"OcNOS Demo Failed: {e}")


if __name__ == "__main__":
    main()
