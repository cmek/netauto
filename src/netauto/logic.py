import logging
from typing import Dict, List, Optional
from .models import Interface, Lag, Vlan
from .drivers import DeviceDriver
from .exceptions import NetAutoException

logger = logging.getLogger(__name__)


def _as_interface_map(interfaces) -> Dict[str, Interface]:
    """Drivers return either a dict (Mock) or a list (real) of interfaces.

    Normalise to a name -> Interface mapping so callers don't have to care.
    """
    if isinstance(interfaces, dict):
        return interfaces
    return {intf.name: intf for intf in interfaces}


class InterfaceManager:
    def __init__(self, driver: DeviceDriver, name: str):
        self.driver = driver
        self.name = name
        self.renderer = driver.renderer
        interfaces = _as_interface_map(driver.get_interfaces())
        self.interface = interfaces.get(name, None)
        if self.interface is None:
            raise NetAutoException(f"Interface {name} not found")

    @property
    def description(self):
        return self.interface.description

    @description.setter
    def description(self, description):
        self.interface.description = description

    @property
    def mtu(self):
        return self.interface.mtu

    @mtu.setter
    def mtu(self, mtu):
        self.interface.mtu = mtu

    def apply(self, dry_run: bool = False):
        """Render and push the current interface configuration."""
        rendered = self.renderer.render_interface(self.interface)
        commands = rendered if isinstance(rendered, list) else [rendered]
        logger.info(f"interface commands: {commands}")
        return self.driver.push_config(commands, dry_run=dry_run)


class LagManager:
    """Building blocks for single-switch LAG create/delete on Arista and OcNOS.

    Two layers are available:
      * ``driver.push_lag(Lag, delete=...)`` — the low-level primitive, when the
        caller already has a fully-formed ``Lag`` model.
      * ``LagManager.create_lag(name, ports)`` / ``delete_lag(name, ports)`` —
        port-list helpers that read device state, build the ``Lag`` and push it.

    No MLAG support — these are single-switch aggregates only.
    """

    def __init__(self, driver: DeviceDriver):
        self.driver = driver

    def _collect_vlans(
        self, switchports: Dict[str, Interface], member_ports: List[str]
    ) -> tuple[str, List[Vlan], Optional[int]]:
        """Derive the LAG's switchport mode + VLANs from its member ports.

        Trunk wins over access if members are mixed. Trunk VLANs are de-duped
        while preserving order.
        """
        mode = "access"
        trunk_vlans: List[Vlan] = []
        access_vlan: Optional[int] = None
        seen: set[int] = set()

        for port in member_ports:
            sp = switchports.get(port)
            if sp is None:
                continue
            if sp.mode == "trunk":
                mode = "trunk"
                for vlan in sp.trunk_vlans:
                    if vlan.vlan_id not in seen:
                        seen.add(vlan.vlan_id)
                        trunk_vlans.append(vlan)
            elif sp.mode == "access" and sp.access_vlan and mode != "trunk":
                access_vlan = sp.access_vlan

        return mode, trunk_vlans, access_vlan

    def create_lag(
        self,
        lag_name: str,
        member_ports: List[str],
        lacp_mode: str = "active",
        description: Optional[str] = None,
        migrate_vlans: bool = True,
        dry_run: bool = False,
    ) -> str:
        """Bundle ``member_ports`` into ``lag_name``.

        When ``migrate_vlans`` is set, VLAN configuration found on the member
        ports is moved onto the LAG (Arista: switchport config on the
        Port-Channel; OcNOS: dot1q sub-interfaces are recreated on the ``po``
        and removed from the members).

        Returns the configuration diff (or the intended change in dry-run).
        """
        # Existence is checked against the full interface inventory: a routed
        # (L3) port exists on the device but won't appear in get_switchports(),
        # which only reports L2 switchports.
        inventory = _as_interface_map(self.driver.get_interfaces())
        switchports = _as_interface_map(self.driver.get_switchports())

        for port in member_ports:
            if port not in inventory and port not in switchports:
                raise NetAutoException(f"Port {port} does not exist on device.")
            member_of = (
                getattr(inventory.get(port), "lag_member_of", None)
                or getattr(switchports.get(port), "lag_member_of", None)
            )
            if member_of:
                raise NetAutoException(
                    f"Port {port} is already a member of {member_of}"
                )

        members = [Interface(name=p) for p in member_ports]
        lag = Lag(
            name=lag_name,
            description=description,
            lacp_mode=lacp_mode,
            members=members,
            mtu=None,  # don't impose a default MTU; device keeps its own
        )

        mode, trunk_vlans, access_vlan = ("access", [], None)
        if migrate_vlans:
            mode, trunk_vlans, access_vlan = self._collect_vlans(
                switchports, member_ports
            )

        # Arista models L2 VLANs as switchport config on the Port-Channel, so we
        # carry them on the Lag model and let the renderer emit them inline.
        if self.driver.platform != "ipinfusion_ocnos":
            if migrate_vlans and mode == "trunk" and trunk_vlans:
                lag.mode = "trunk"
                lag.trunk_vlans = trunk_vlans
            elif migrate_vlans and access_vlan:
                lag.mode = "access"
                lag.access_vlan = access_vlan
            logger.info("creating LAG %s with members %s", lag_name, member_ports)
            return self.driver.push_lag(lag, dry_run=dry_run)

        # OcNOS-SP models L2 VLANs as dot1q sub-interfaces. Build one atomic
        # payload list: the bundle, then move each member's sub-interfaces onto
        # the po. create_parent_agg=True instantiates the aggregator so the
        # members' aggregate-id reference resolves.
        commands: List[str] = [
            self.driver.renderer.render_lag(lag, create_parent_agg=True)
        ]
        if migrate_vlans:
            for port in member_ports:
                sp = switchports.get(port)
                for vlan in (sp.trunk_vlans if sp else []):
                    commands.append(self.driver.renderer.render_vlan(lag, vlan))
                    commands.append(
                        self.driver.renderer.render_vlan_delete(
                            Interface(name=port), vlan
                        )
                    )
        logger.info("creating LAG %s with members %s", lag_name, member_ports)
        return self.driver.push_config(commands, dry_run=dry_run)

    def delete_lag(
        self, lag_name: str, member_ports: List[str], dry_run: bool = False
    ) -> str:
        """Tear ``lag_name`` apart, returning its members to standalone ports.

        Plain split: VLANs that were migrated onto the LAG are not restored to
        the member ports.
        """
        members = [Interface(name=p) for p in member_ports]
        lag = Lag(name=lag_name, members=members)
        logger.info("deleting LAG %s (members %s)", lag_name, member_ports)
        return self.driver.push_lag(lag, delete=True, dry_run=dry_run)

    def _push_rendered(self, rendered, dry_run: bool) -> str:
        """Normalise a renderer result (CLI list or single XML string) and push."""
        commands = rendered if isinstance(rendered, list) else [rendered]
        return self.driver.push_config(commands, dry_run=dry_run)

    def add_members(
        self,
        lag_name: str,
        member_ports: List[str],
        lacp_mode: str = "active",
        dry_run: bool = False,
    ) -> str:
        """Add ports to an existing LAG without disturbing its other members.

        The LAG must already exist. Ports already belonging to a *different* LAG
        are refused; re-adding a port already in this LAG is a no-op.
        """
        inventory = _as_interface_map(self.driver.get_interfaces())
        switchports = _as_interface_map(self.driver.get_switchports())

        if lag_name not in inventory:
            raise NetAutoException(
                f"LAG {lag_name} does not exist; use create_lag first."
            )

        for port in member_ports:
            if port not in inventory and port not in switchports:
                raise NetAutoException(f"Port {port} does not exist on device.")
            member_of = (
                getattr(inventory.get(port), "lag_member_of", None)
                or getattr(switchports.get(port), "lag_member_of", None)
            )
            if member_of and member_of != lag_name:
                raise NetAutoException(
                    f"Port {port} is already a member of {member_of}"
                )

        lag = Lag(
            name=lag_name,
            members=[Interface(name=p) for p in member_ports],
            lacp_mode=lacp_mode,
            mtu=None,
        )
        logger.info("adding members %s to LAG %s", member_ports, lag_name)
        return self._push_rendered(
            self.driver.renderer.render_lag_add_members(lag), dry_run
        )

    def remove_members(
        self, lag_name: str, member_ports: List[str], dry_run: bool = False
    ) -> str:
        """Detach ports from a LAG, leaving the LAG and its other members intact.

        Each port must currently belong to ``lag_name`` — this guards against
        accidentally detaching a port from a different LAG (`no channel-group`
        would otherwise pull it out of whatever channel it is in).
        """
        inventory = _as_interface_map(self.driver.get_interfaces())

        for port in member_ports:
            member_of = getattr(inventory.get(port), "lag_member_of", None)
            if member_of != lag_name:
                raise NetAutoException(
                    f"Port {port} is not a member of {lag_name} "
                    f"(currently: {member_of})"
                )

        lag = Lag(
            name=lag_name,
            members=[Interface(name=p) for p in member_ports],
            mtu=None,
        )
        logger.info("removing members %s from LAG %s", member_ports, lag_name)
        return self._push_rendered(
            self.driver.renderer.render_lag_remove_members(lag), dry_run
        )
