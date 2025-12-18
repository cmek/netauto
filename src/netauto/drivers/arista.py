from .base import DeviceDriver
import pyeapi
from netauto.models import Interface, Vlan, Lag, Evpn
from netauto.render import AristaDeviceRenderer
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
        self.renderer = AristaDeviceRenderer()

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

    def get_interfaces(self) -> List[Interface | Lag]:
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

        interfaces = []
        for name, intf_data in data.get("interfaces", {}).items():
            print(intf_data)
            mode = "routed"
            trunk_vlans = []
            access_vlan = None

            if name.startswith(self.lag_prefix):
                # It's a LAG
                members = []
                lacp_mode = "active"  # default
                for member_name, member_data in intf_data.get("members", {}).items():
                    members.append(Interface(name=member_name))
                lag = Lag(
                    name=name,
                    mode="routed",
                    members=members,
                    lacp_mode=lacp_mode,
                    min_links=1,
                )
                interfaces.append(lag)
                continue
            else:
                interfaces.append(
                    Interface(
                        name=name,
                        mode=mode,
                        trunk_vlans=trunk_vlans,
                        access_vlan=access_vlan,
                    )
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

    def push_evpn(self, interface, evpn: Evpn, delete: bool = False, dry_run: bool = False):
        commands = (
            self.renderer.render_evpn_delete(interface, evpn)
            if delete
            else self.renderer.render_evpn(interface, evpn)
        )
        return self.push_config(commands, dry_run=dry_run)

    def get_system_macs(self) -> List[str]:
        """Retrieve system MAC addresses from Arista EOS.
        XXX not implemented yet
        """
        system_macs = []
        return system_macs

    def push_lag(self, lag: Lag, delete: bool = False, dry_run: bool = False):
        commands = (
            self.renderer.render_lag_delete(lag)
            if delete
            else self.renderer.render_lag(lag)
        )
        return self.push_config(commands, dry_run=dry_run)

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
