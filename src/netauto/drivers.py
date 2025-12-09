from abc import ABC, abstractmethod
from typing import List, Dict, Any
from .models import Interface, Vlan
import logging

import pyeapi
from scrapli_netconf.driver import NetconfDriver as ScrapliNetconfDriver
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)


class DeviceDriver(ABC):
    @property
    @abstractmethod
    def platform(self) -> str:
        """Return the platform identifier (e.g., 'arista_eos', 'ipinfusion_ocnos')."""
        pass

    @property
    @abstractmethod
    def lag_prefix(self) -> str:
        """Returns the prefix used for LAG interfaces (e.g. "Port-Channel" or "po")."""
        pass

    @abstractmethod
    def connect(self):
        pass

    @abstractmethod
    def disconnect(self):
        pass

    @abstractmethod
    def get_interfaces(self) -> Dict[str, Interface]:
        """Returns a dictionary of interface name to Interface model."""
        pass

    @abstractmethod
    def get_vlans(self) -> Dict[int, Vlan]:
        """Returns a dictionary of vlan_id to Vlan model."""
        pass

    @abstractmethod
    def get_vnis(self) -> Dict[int, Dict[str, Any]]:
        """Returns a dictionary of VNI to VNI information (vlan_id, etc.)."""
        pass

    @abstractmethod
    def push_config(self, commands: List[str], dry_run: bool = False) -> str:
        """Pushes a list of configuration commands to the device.

        Args:
            commands (List[str]): List of configuration commands to push.
            dry_run (bool): If True, do not commit changes, just simulate.

        Returns:
            str: The configuration diff after applying the commands. Or the intended changes in dry-run mode.
        """
        pass


class MockDriver(DeviceDriver):
    def __init__(
        self,
        initial_interfaces: List[Interface] = None,
        initial_vlans: List[Vlan] = None,
        initial_vnis: Dict[int, Dict[str, Any]] = None,
        platform: str = "arista_eos",
    ):
        self.interfaces = {i.name: i for i in (initial_interfaces or [])}
        self.vlans = {v.vlan_id: v for v in (initial_vlans or [])}
        self.vnis = initial_vnis or {}  # Dict[vni -> {vlan_id, ...}]
        self.pushed_commands = []
        self._platform = platform

    @property
    def platform(self) -> str:
        return self._platform

    @property
    def lag_prefix(self) -> str:
        return "Port-Channel"

    def connect(self):
        print("MockDriver: Connected")

    def disconnect(self):
        print("MockDriver: Disconnected")

    def get_interfaces(self) -> Dict[str, Interface]:
        return self.interfaces

    def get_vlans(self) -> Dict[int, Vlan]:
        return self.vlans

    def get_vnis(self) -> Dict[int, Dict[str, Any]]:
        return self.vnis

    def push_config(self, commands: List[str]):
        print(f"MockDriver: Pushing {len(commands)} commands")
        for cmd in commands:
            print(f"  + {cmd}")
        self.pushed_commands.extend(commands)


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
            print(data)
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


class OcnosDriver(DeviceDriver):
    def __init__(self, host: str, user: str, password: str):
        self.conn = ScrapliNetconfDriver(
            host=host,
            auth_username=user,
            auth_password=password,
            auth_strict_key=False,
            transport="paramiko",
        )

    @property
    def platform(self) -> str:
        return "ipinfusion_ocnos"

    @property
    def lag_prefix(self) -> str:
        return "po"

    def connect(self):
        self.conn.open()

    def disconnect(self):
        self.conn.close()

    def _extract_interfaces(self, interfaces_data) -> Dict[str, Interface]:
        """
        extracts interfaces from the xml response
        """
        root = ET.fromstring(interfaces_data)
        # Namespace map
        ns = {
            "ocnos": "http://www.ipinfusion.com/yang/ocnos/ipi-interface",
            "nc": "urn:ietf:params:xml:ns:netconf:base:1.0",
        }

        interfaces = {}

        ## work around bug (or a feature??) of OCNOS where some of the interfaces
        # are not returned under the <interfaces> tag but instead they appear
        # to be added at the same level. Because of that placement they are under
        # different namespaces so we need to look twice (or use something
        # like [local-name()='interface'] in xpath
        # but instead we'll just cycle through both namespaces to catch all instances...
        for namespace in ns.keys():
            for intf in root.findall(f".//{namespace}:interface", ns):
                name = intf.find(f"{namespace}:name", ns).text
                if name is None:
                    logger.info(f"couldn't find name for interface {intf}, skipping")
                    continue

                # Determine mode and VLANs
                mode = "routed"
                trunk_vlans = []
                access_vlan = None

                eth_opts = intf.find(f"{namespace}:ether-options", ns)
                agg_opts = intf.find(f"{namespace}:aggregated-ether-options", ns)

                # Check for L2/Switchport info (simplified logic as YANG structure varies)
                # In real OcNOS, this might be under a different subtree or augmented model
                # For now, we'll default to routed unless we see specific L2 indicators
                # This is a placeholder for actual YANG parsing logic

                interfaces[name] = Interface(
                    name=name,
                    mode=mode,
                    trunk_vlans=trunk_vlans,
                    access_vlan=access_vlan,
                )
        return interfaces

    def get_config(self) -> str:
        """
        Retrieves the whole config. This is mostly useful for testing
        """
        try:
            return self.conn.get_config()
        except Exception as e:
            logger.error(f"Failed to get configuration: {e}")
            return ""

    def get_interfaces(self) -> Dict[str, Interface]:
        """
        Retrieves interfaces from OcNOS using Netconf.
        """
        # Filter to get interface configuration/state
        # Note: Actual filter depends on OcNOS YANG model. Using a broad filter or subtree for now.
        # Assuming IETF interfaces or OcNOS specific model.
        # For this implementation, we'll assume a standard structure similar to what we build.

        # Using a simple subtree filter for interfaces
        filter_ = """
        <interfaces xmlns="http://www.ipinfusion.com/yang/ocnos/ipi-interface">
        </interfaces>
        """
        try:
            response = self.conn.get(filter_=filter_)
            if not response.result:
                return {}

            interfaces = self._extract_interfaces(response.result)
            return interfaces
        except Exception as e:
            logger.error(f"Failed to get interfaces: {e}")
            return {}

    def get_vlans(self) -> Dict[int, Vlan]:
        filter_ = """
        <vlan-database xmlns="http://www.ipinfusion.com/yang/ocnos/ipi-vlan">
        </vlan-database>
        """
        try:
            response = self.conn.get(filter_=filter_)
            if not response.result:
                return {}

            root = ET.fromstring(response.result)
            ns = {"ocnos": "http://www.ipinfusion.com/yang/ocnos/ipi-vlan"}

            vlans = {}
            for vlan in root.findall(".//ocnos:vlan", ns):
                vlan_id_elem = vlan.find("ocnos:id", ns)
                if vlan_id_elem is not None:
                    vlan_id = int(vlan_id_elem.text)
                    name_elem = vlan.find("ocnos:name", ns)
                    name = name_elem.text if name_elem is not None else f"VLAN{vlan_id}"
                    vlans[vlan_id] = Vlan(vlan_id=vlan_id, name=name)
            return vlans
        except Exception as e:
            logger.error(f"Failed to get VLANs: {e}")
            return {}

    def get_vnis(self) -> Dict[int, Dict[str, Any]]:
        filter_ = """
        <vxlan xmlns="http://www.ipinfusion.com/yang/ocnos/ipi-vxlan">
        </vxlan>
        """
        try:
            response = self.conn.get(filter_=filter_)
            if not response.result:
                return {}

            root = ET.fromstring(response.result)
            ns = {"ocnos": "http://www.ipinfusion.com/yang/ocnos/ipi-vxlan"}

            vnis = {}
            for vxlan in root.findall(
                ".//ocnos:vxlan", ns
            ):  # Assuming list of vxlan mappings
                # Note: Structure might be different, e.g. single vxlan container with list
                # Adjusting for potential list item
                vni_elem = vxlan.find("ocnos:vni", ns)
                vlan_elem = vxlan.find("ocnos:vlan", ns)

                if vni_elem is not None and vlan_elem is not None:
                    vni = int(vni_elem.text)
                    vlan_id = int(vlan_elem.text)
                    vnis[vni] = {"vlan_id": vlan_id}
            return vnis
        except Exception as e:
            logger.error(f"Failed to get VNIs: {e}")
            return {}

    def push_config(self, commands: List[str]):
        """
        Pushes configuration to OcNOS.
        For Netconf, 'commands' is expected to be a list containing a single XML string
        (since our renderer now returns [xml_string]).
        """
        for cmd in commands:
            # cmd is the XML payload
            try:
                response = self.conn.lock(target="candidate")
                logger.info(f"locking response: {response.result}")
                response = self.conn.edit_config(config=cmd, target="candidate")
                logger.info(f"edit_config response: {response.result}")
                response = self.conn.commit()

                # XXX check for responses so far and run discard() and unlock

                logger.info(f"commit response: {response.result}")
                self.conn.unlock(target="candidate")
            except Exception as e:
                logger.error(f"Failed to push config: {e}")
                raise
