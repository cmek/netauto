from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator, model_validator


class Vlan(BaseModel):
    vlan_id: int = Field(..., ge=1, le=4094)
    name: Optional[str] = None
    s_tag: Optional[int] = Field(None, ge=1, le=4094)


class Interface(BaseModel):
    name: str
    description: Optional[str] = None
    enabled: bool = True
    mtu: Optional[int] = 1500
    mode: Literal["access", "trunk", "routed"] = "access"
    # For switchports
    access_vlan: Optional[int] = None
    trunk_vlans: list[Vlan] = Field(default_factory=list)
    # For LAG
    lag_member_of: Optional[str] = None  # Name of the Port-Channel
    # For Azure VPNS
    arp_cache: Optional[bool] = None
    nd_cache: Optional[bool] = None
    vpn_id: Optional[int] = None


class Lag(Interface):
    members: list[Interface] = Field(default_factory=list)
    lacp_mode: Literal["active", "passive", "static"] = "active"
    min_links: int = 1
    # this is for tracking mac vrf / mlag
    system_mac: Optional[str] = None


# EVPN Models
class Vrf(BaseModel):
    name: str
    rd: str
    rt_import: list[str]
    rt_export: list[str]


class Connection(BaseModel):
    host: str
    interface: Interface | Lag


class Evpn(BaseModel):
    vlan: Vlan
    description: str
    asn: int
    # VNI for the circuit. Allocated sequentially and tracked by a process
    # *outside* this library (which reads current network state via netauto);
    # it is passed in whole and used verbatim for the VXLAN id / vpn-id and the
    # mac-vrf / vlan-aware-bundle identifier. Never derived from the VLAN.
    vni: int
    # Descriptive product label only — does not affect rendering. cloud_vc and
    # p2p_vc render identically given the same vni/vlan.
    service_type: Literal["cloud_vc", "p2p_vc"] = "p2p_vc"


class AzureEvpn(BaseModel):
    """An Azure ExpressRoute Q-in-Q EVPN circuit endpoint (global transport).

    Azure presents customer traffic as 1-3 inner C-TAGs wrapped in a single
    outer S-TAG. The customer-facing port tunnels each C-TAG into the S-TAG;
    the CNI-facing port keys everything on the S-TAG (the C-TAGs are
    encapsulated inside the VXLAN tunnel and not visible on the device).

    Dual-CNI (primary + secondary) is the orchestrator's concern — it calls the
    building block once per CNI with its own ``vni``. The VNI is allocated
    externally and used verbatim, as for non-Azure circuits.
    """

    description: str  # service key; names the mac-vrf / vlan-aware-bundle
    asn: int
    vni: int
    s_tag: int = Field(..., ge=1, le=4094)  # outer S-TAG provided by Azure
    role: Literal["customer", "cni"]
    # 1-3 inner C-TAGs — customer side only (encapsulated on the CNI side).
    c_tags: list[int] = Field(default_factory=list)
    # S-TAG conflict resolution on a CNI endpoint (Azure S-TAG already mapped on
    # the device). Arista translates the Azure S-TAG to ``internal_s_tag``;
    # OcNOS pops the S-TAG (and disables arp/nd caching).
    rewrite: bool = False
    # Arista-only: the device-internal S-TAG the Azure S-TAG is translated to
    # when ``rewrite`` is set. OcNOS ignores it (it pops instead of translating).
    internal_s_tag: Optional[int] = Field(None, ge=1, le=4094)

    @model_validator(mode="after")
    def _check_roles(self) -> "AzureEvpn":
        if self.role == "customer":
            if not 1 <= len(self.c_tags) <= 3:
                raise ValueError("customer Azure circuit requires 1-3 c_tags")
            if self.s_tag in self.c_tags:
                raise ValueError("a c_tag cannot equal the s_tag")
            if self.rewrite or self.internal_s_tag is not None:
                raise ValueError("rewrite/internal_s_tag apply to the CNI side only")
        else:  # cni — C-TAGs are encapsulated inside the S-TAG tunnel
            if self.c_tags:
                raise ValueError("CNI Azure circuit takes no c_tags (encapsulated)")
        return self


# NOTE: EvpnService/Vrf predate the renderer layer and are unused by the
# current building blocks, which standardise on Evpn + RoutingInstance. Kept for
# backwards compatibility; do not build new code on them.
class EvpnService(Evpn):
    connections: list[Connection]
    vlan_id: int
    vni: int
    vrf_name: str


# consider this name?
class RoutingInstance(BaseModel):
    instance_name: str
    instance_type: str
    rd: str
    rt_rd: str
    # direction: str


class Asn(BaseModel):
    # Optional single ASN in a single-router config context
    asn: int

    @field_validator("asn")
    @classmethod
    def validate_asn(cls, asn: int) -> int:
        if asn < 1:
            raise ValueError("ASN must be greater than 0")

        # ASN is valid as either 2-byte or 4-byte in the range 1..4294967295.
        if asn > 0xFFFFFFFF:
            raise ValueError("ASN must not exceed 4294967295")

        return asn


class Config(BaseModel):
    #    hostname: str
    asn: Optional[Asn] = None
    interfaces: list[Interface] = Field(default_factory=list)
    lags: list[Lag] = Field(default_factory=list)
    vrfs: list[RoutingInstance] = Field(default_factory=list)
    evpns: list[Evpn] = Field(default_factory=list)
    vlans: list[Vlan] = Field(default_factory=list)
