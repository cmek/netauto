from abc import ABC, abstractmethod
from typing import List, Dict, Any
from .models import Interface, Vlan
import logging

from scrapli_netconf.driver import NetconfDriver as ScrapliNetconfDriver
import jsonrpclib
import xml.etree.ElementTree as ET

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
    def push_config(self, commands: List[str]):
        """Pushes a list of configuration commands to the device."""
        pass

class MockDriver(DeviceDriver):
    def __init__(self, initial_interfaces: List[Interface] = None, initial_vlans: List[Vlan] = None, 
                 initial_vnis: Dict[int, Dict[str, Any]] = None, platform: str = "arista_eos"):
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
    def __init__(self, host: str, user: str, password: str):
        self.host = host
        self.user = user
        self.password = password
        self.url = f"http://{user}:{password}@{host}/command-api"
        self.server = jsonrpclib.Server(self.url)

    @property
    def platform(self) -> str:
        return "arista_eos"

    @property
    def lag_prefix(self) -> str:
        return "Port-Channel"

    def connect(self):
        # eAPI is stateless, but we can verify connectivity
        # We'll do a simple ping command or version check
        try:
            self.server.runCmds(1, ["show version"])
        except Exception as e:
            logging.error(f"Failed to connect to Arista eAPI: {e}")
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
            response = self.server.runCmds(1, ["show interfaces", "show interfaces switchport"])
            data = response[0]
            data_sw = response[1]
        except Exception as e:
            logging.error(f"Failed to retrieve interfaces: {e}")
            return {}
        
        switchports = data_sw.get('switchports', {})
        
        interfaces = {}
        for name, intf_data in data.get('interfaces', {}).items():
            mode = "routed"
            trunk_vlans = []
            access_vlan = None
            
            # Check if it has switchport info
            if name in switchports:
                sw_data = switchports[name]
                sw_info = sw_data.get('switchportInfo', {})
                
                if sw_info.get('mode') == 'trunk':
                    mode = "trunk"
                    vlans_str = sw_info.get('trunkAllowedVlans', '')
                    if vlans_str and vlans_str != "ALL":
                        try:
                            trunk_vlans = [int(v) for v in vlans_str.split(',') if v.isdigit()]
                        except ValueError:
                            pass
                elif sw_info.get('mode') == 'access':
                    mode = "access"
                    access_vlan = sw_info.get('accessVlanId')
            
            interfaces[name] = Interface(
                name=name,
                mode=mode,
                trunk_vlans=trunk_vlans,
                access_vlan=access_vlan
            )
            
        return interfaces

    def get_vlans(self) -> Dict[int, Vlan]:
        try:
            response = self.server.runCmds(1, ["show vlan"])
            data = response[0]
        except Exception as e:
            logging.error(f"Failed to retrieve VLANs: {e}")
            return {}
        
        vlans = {}
        for vlan_id_str, vlan_data in data.get('vlans', {}).items():
            vlan_id = int(vlan_id_str)
            name = vlan_data.get('name', f"VLAN{vlan_id}")
            vlans[vlan_id] = Vlan(vlan_id=vlan_id, name=name)
            
        return vlans

    def get_vnis(self) -> Dict[int, Dict[str, Any]]:
        try:
            response = self.server.runCmds(1, ["show vxlan vni"])
            data = response[0]
        except Exception as e:
            logging.error(f"Failed to retrieve VNIs: {e}")
            return {}
        
        vnis = {}
        # Structure depends on EOS version, typically:
        # {'vxlanVnis': {'10010': {'vlan': 10, ...}}}
        for vni_str, vni_data in data.get('vxlanVnis', {}).items():
            vni = int(vni_str)
            vlan_id = vni_data.get('vlanId')
            if vlan_id:
                vnis[vni] = {'vlan_id': vlan_id}
                
        return vnis

    def push_config(self, commands: List[str]):
        try:
            self.server.runCmds(1, ["configure"] + commands)
        except Exception as e:
            logging.error(f"Failed to push config: {e}")
            raise

class OcnosDriver(DeviceDriver):
    def __init__(self, host: str, user: str, password: str):
        self.conn = ScrapliNetconfDriver(host=host, auth_username=user, auth_password=password, auth_strict_key=False, transport="paramiko")

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
            
            root = ET.fromstring(response.result)
            # Namespace map
            ns = {'ocnos': 'http://www.ipinfusion.com/yang/ocnos/ipi-interface'}
            
            interfaces = {}
            for intf in root.findall('.//ocnos:interface', ns):
                name = intf.find('ocnos:name', ns).text
                
                # Determine mode and VLANs
                mode = "routed"
                trunk_vlans = []
                access_vlan = None
                
                eth_opts = intf.find('ocnos:ether-options', ns)
                agg_opts = intf.find('ocnos:aggregated-ether-options', ns)
                
                # Check for L2/Switchport info (simplified logic as YANG structure varies)
                # In real OcNOS, this might be under a different subtree or augmented model
                # For now, we'll default to routed unless we see specific L2 indicators
                # This is a placeholder for actual YANG parsing logic
                
                interfaces[name] = Interface(
                    name=name,
                    mode=mode,
                    trunk_vlans=trunk_vlans,
                    access_vlan=access_vlan
                )
            return interfaces
        except Exception as e:
            logging.error(f"Failed to get interfaces: {e}")
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
            ns = {'ocnos': 'http://www.ipinfusion.com/yang/ocnos/ipi-vlan'}
            
            vlans = {}
            for vlan in root.findall('.//ocnos:vlan', ns):
                vlan_id_elem = vlan.find('ocnos:id', ns)
                if vlan_id_elem is not None:
                    vlan_id = int(vlan_id_elem.text)
                    name_elem = vlan.find('ocnos:name', ns)
                    name = name_elem.text if name_elem is not None else f"VLAN{vlan_id}"
                    vlans[vlan_id] = Vlan(vlan_id=vlan_id, name=name)
            return vlans
        except Exception as e:
            logging.error(f"Failed to get VLANs: {e}")
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
            ns = {'ocnos': 'http://www.ipinfusion.com/yang/ocnos/ipi-vxlan'}
            
            vnis = {}
            for vxlan in root.findall('.//ocnos:vxlan', ns): # Assuming list of vxlan mappings
                # Note: Structure might be different, e.g. single vxlan container with list
                # Adjusting for potential list item
                vni_elem = vxlan.find('ocnos:vni', ns)
                vlan_elem = vxlan.find('ocnos:vlan', ns)
                
                if vni_elem is not None and vlan_elem is not None:
                    vni = int(vni_elem.text)
                    vlan_id = int(vlan_elem.text)
                    vnis[vni] = {'vlan_id': vlan_id}
            return vnis
        except Exception as e:
            logging.error(f"Failed to get VNIs: {e}")
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
                logging.info(f"locking response: {response.result}")
                response = self.conn.edit_config(config=cmd, target="candidate")
                logging.info(f"edit_config response: {response.result}")
                response = self.conn.commit()

                #XXX check for responses so far and run discard() and unlock

                logging.info(f"commit response: {response.result}")
                self.conn.unlock(target="candidate")
            except Exception as e:
                logging.error(f"Failed to push config: {e}")
                raise
