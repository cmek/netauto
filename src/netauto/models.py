from typing import List, Optional, Literal
from pydantic import BaseModel, Field


class Vlan(BaseModel):
    vlan_id: int = Field(..., ge=1, le=4094)
    name: str | None = None
    s_tag: Optional[int] = Field(None, ge=1, le=4094)


class Interface(BaseModel):
    name: str
    description: Optional[str] = None
    enabled: bool = True
    mtu: Optional[int] = 1500
    mode: Literal["access", "trunk", "routed"] = "access"
    # For switchports
    access_vlan: Optional[int] = None
    trunk_vlans: List[Vlan] = Field(default_factory=list)
    # For LAG
    lag_member_of: Optional[str] = None  # Name of the Port-Channel


class Lag(Interface):
    members: List[Interface] = Field(default_factory=list)
    lacp_mode: Literal["active", "passive", "static"] = "active"
    min_links: int = 1


# EVPN Models
class Vrf(BaseModel):
    name: str
    rd: str
    rt_import: List[str]
    rt_export: List[str]


class Bgp(BaseModel):
    as_number: int
    router_id: str
    neighbors: List[str] = Field(default_factory=list)


class EvpnService(BaseModel):
    vlan_id: int
    vni: int
    vrf_name: str
    s_tag: Optional[int] = Field(None, ge=1, le=4094)
