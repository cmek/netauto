from abc import ABC, abstractmethod
from typing import List
from netauto.models import Interface, Vlan, Lag, EvpnService


class DeviceRenderer(ABC):
    @abstractmethod
    def render_interface(self, interface: Interface) -> List[str]:
        """Render interface configuration commands for the given platform."""
        pass

    @abstractmethod
    def render_interface_delete(self, interface: Interface) -> List[str]:
        """Render interface configuration commands for the given platform."""
        pass

    @abstractmethod
    def render_lag(self, lag: Lag) -> List[str]:
        """Render LAG configuration commands for the given platform."""
        pass

    @abstractmethod
    def render_lag_delete(self, lag: Lag) -> List[str]:
        """Render LAG configuration commands for the given platform."""
        pass

    @abstractmethod
    def render_lag_add_members(self, lag: Lag) -> List[str]:
        """Render config that adds lag.members to an existing LAG, without
        touching the LAG interface itself."""
        pass

    @abstractmethod
    def render_lag_remove_members(self, lag: Lag) -> List[str]:
        """Render config that detaches lag.members from a LAG, leaving the LAG
        interface and its other members intact."""
        pass

    @abstractmethod
    def render_vlan(self, vlan: Vlan) -> List[str]:
        """Render LAG configuration commands for the given platform."""
        pass

    @abstractmethod
    def render_vlan_delete(self, vlan: Vlan) -> List[str]:
        """Render LAG configuration commands for the given platform."""
        pass

    @abstractmethod
    def render_evpn(self, svc: EvpnService) -> List[str]:
        """Render EVPN service configuration commands for the given platform."""
        pass

    @abstractmethod
    def render_evpn_delete(self, svc: EvpnService) -> List[str]:
        """Render EVPN service configuration commands for the given platform."""
        pass
