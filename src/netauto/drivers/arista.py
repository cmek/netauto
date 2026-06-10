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

    def connect(self, transport: str = "http"):
        try:
            self.node = pyeapi.connect(
                transport=transport,
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

    def get_config(self, config_type: str = "running", format: str = "text") -> str:
        # we'll use the command output rather than node.running_config or startup_config properties
        # becuse we don't need all the defaults included in the output

        response = self.node.enable(f"show {config_type}-config", encoding=format)

        if format == "json":
            return response[0].get("result", {})
        elif format == "text":
            return response[0].get("result", {}).get("output", "")
        else:
            raise Exception(
                f"Unsupported format {format}, allowed values are json or text"
            )

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

        raw = data.get("interfaces", {})

        # Each physical port reports its aggregation via the interfaceMembership
        # string ("Member of Port-ChannelN"); the Port-Channel's memberInterfaces
        # only lists operationally-bundled members, so it's unreliable when the
        # members are admin-down. Parse the per-port field instead so we can flag
        # ports that already belong to a LAG (prevents hijacking them).
        def _parse_membership(value: str | None) -> str | None:
            prefix = "Member of "
            if value and value.startswith(prefix):
                return value[len(prefix):].strip()
            return None

        member_to_lag: Dict[str, str] = {}
        for name, intf_data in raw.items():
            parent = _parse_membership(intf_data.get("interfaceMembership"))
            if parent:
                member_to_lag[name] = parent

        interfaces = []
        for name, intf_data in raw.items():
            if name.startswith(self.lag_prefix):
                members = [
                    Interface(name=member_name, lag_member_of=name)
                    for member_name, parent in member_to_lag.items()
                    if parent == name
                ]
                interfaces.append(
                    Lag(
                        name=name,
                        mode="routed",
                        members=members,
                        lacp_mode="active",
                        min_links=1,
                    )
                )
            else:
                interfaces.append(
                    Interface(
                        name=name,
                        mode="routed",
                        lag_member_of=member_to_lag.get(name),
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

    @staticmethod
    def _parse_vlan_ranges(spec: str) -> List[int]:
        """Expand an EOS allowed-vlan spec like '10,20,30-32' into [10,20,30,31,32].

        Returns an empty list for the catch-all default ('ALL'/'1-4094') so we
        don't migrate the entire VLAN space when bundling a default trunk.
        """
        if not spec:
            return []
        spec = spec.strip().lower()
        if spec in {"all", "1-4094", "none", ""}:
            return []
        vlans: List[int] = []
        for part in spec.split(","):
            part = part.strip()
            if "-" in part:
                lo, hi = part.split("-", 1)
                vlans.extend(range(int(lo), int(hi) + 1))
            elif part.isdigit():
                vlans.append(int(part))
        return vlans

    def get_switchports(self) -> Dict[str, Interface]:
        """Per-port switchport state via 'show interfaces switchport'."""
        try:
            response = self.node.enable("show interfaces switchport")
            data = response[0].get("result", {})
        except Exception as e:
            logger.error(f"Failed to retrieve switchports: {e}")
            return {}

        switchports: Dict[str, Interface] = {}
        for name, entry in data.get("switchports", {}).items():
            info = entry.get("switchportInfo", {})
            raw_mode = info.get("mode", "")
            if raw_mode.startswith("trunk"):
                mode = "trunk"
            elif raw_mode.startswith("access"):
                mode = "access"
            else:
                mode = "routed"

            access_vlan = None
            if mode == "access":
                access_vlan = info.get("accessVlanId")

            trunk_vlans = []
            if mode == "trunk":
                trunk_vlans = [
                    Vlan(vlan_id=v)
                    for v in self._parse_vlan_ranges(
                        str(info.get("trunkAllowedVlans", ""))
                    )
                ]

            switchports[name] = Interface(
                name=name,
                mode=mode,
                access_vlan=access_vlan,
                trunk_vlans=trunk_vlans,
            )

        return switchports

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

    def push_evpn(
        self, interface, evpn: Evpn, delete: bool = False, dry_run: bool = False
    ):
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
