from .base import DeviceDriver
import pyeapi
from ..models import Interface, Vlan
from typing import List, Dict, Any
import logging


logger = logging.getLogger(__name__)


class AristaDriver(DeviceDriver):
    def __init__(
        self, host: str, user: str, password: str, enable_password: str | None = None
    ):
        self.host = host
        self.user = user
        self.password = password
        self.enable_password = enable_password
        self.node = None

    @property
    def platform(self) -> str:
        return "arista_eos"

    @property
    def lag_prefix(self) -> str:
        return "Port-Channel"

    def connect(self):
        try:
            self.node = pyeapi.connect(
                transport="http",
                host=self.host,
                username=self.user,
                password=self.password,
                return_node=True,
            )
            if self.enable_password is not None:
                self.node.enable_authentication(self.enable_password)
        except Exception as e:
            logger.error(f"Failed to connect to Arista eAPI: {e}")
            raise

    def disconnect(self):
        # eAPI is stateless, nothing to close
        pass

    def get_interfaces(self) -> Dict[str, Interface]:
        """
        Retrieves interfaces from Arista EOS using 'show interfaces | json'.
        """
        # Get base interface info
        try:
            response = self.node.enable("show interfaces")
            data = response[0].get("result", {})
        except Exception as e:
            logger.error(f"Failed to retrieve interfaces: {e}")
            return {}

        # switchports = data_sw.get("switchports", {})

        interfaces = {}
        for name, intf_data in data.get("interfaces", {}).items():
            print(name)
            mode = "routed"
            trunk_vlans = []
            access_vlan = None

            # Check if it has switchport info
            #            if name in switchports:
            #                sw_data = switchports[name]
            #                sw_info = sw_data.get("switchportInfo", {})
            #
            #                if sw_info.get("mode") == "trunk":
            #                    mode = "trunk"
            #                    vlans_str = sw_info.get("trunkAllowedVlans", "")
            #                    if vlans_str and vlans_str != "ALL":
            #                        try:
            #                            trunk_vlans = [
            #                                int(v) for v in vlans_str.split(",") if v.isdigit()
            #                            ]
            #                        except ValueError:
            #                            pass
            #                elif sw_info.get("mode") == "access":
            #                    mode = "access"
            #                    access_vlan = sw_info.get("accessVlanId")

            interfaces[name] = Interface(
                name=name, mode=mode, trunk_vlans=trunk_vlans, access_vlan=access_vlan
            )

        return interfaces

    def get_vlans(self) -> Dict[int, Vlan]:
        try:
            response = self.node.enable({"cmd": "show vlan"})
            data = response[0]
        except Exception as e:
            logger.error(f"Failed to retrieve VLANs: {e}")
            return {}

        vlans = {}
        for vlan_id_str, vlan_data in data.get("vlans", {}).items():
            vlan_id = int(vlan_id_str)
            name = vlan_data.get("name", f"VLAN{vlan_id}")
            vlans[vlan_id] = Vlan(vlan_id=vlan_id, name=name)

        return vlans

    def get_vnis(self) -> Dict[int, Dict[str, Any]]:
        try:
            response = self.node.enable({"cmd": "show vxlan vni"})
            data = response[0]
        except Exception as e:
            logger.error(f"Failed to retrieve VNIs: {e}")
            return {}

        vnis = {}
        # Structure depends on EOS version, typically:
        # {'vxlanVnis': {'10010': {'vlan': 10, ...}}}
        for vni_str, vni_data in data.get("vxlanVnis", {}).items():
            vni = int(vni_str)
            vlan_id = vni_data.get("vlanId")
            if vlan_id:
                vnis[vni] = {"vlan_id": vlan_id}

        return vnis

    def push_config(self, commands: List[str], dry_run: bool = False):
        self.node.configure_session()
        logger.info(f"started config session {self.node._session_name} on {self.host}")
        try:
            self.node.config(commands)
            logger.info(
                f"sending config commands to session {self.node._session_name} on {self.host}:\n{commands}"
            )
            diff = self.node.diff()
            logger.info(
                f"config diff for session {self.node._session_name} on {self.host}:\n{diff}"
            )
        except Exception as e:
            logger.error(
                f"Failed to push config commands: {e}. Aborting session {self.node._session_name}"
            )
            self.node.abort()
            raise

        if dry_run:
            logger.info(
                f"dry run enabled, aborting config session {self.node._session_name} on {self.host}"
            )
            self.node.abort()
        else:
            logger.info(
                f"committing config session {self.node._session_name} on {self.host}"
            )
            self.node.commit()
            # save the running-config
            self.node.enable("copy running-config startup-config")

        return diff
