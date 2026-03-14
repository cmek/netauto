import re
from lxml import etree
from lxml.etree import Element
from netauto.models import Config, Asn, Evpn, Interface, Lag, RoutingInstance, Vlan
from pathlib import Path
from typing import Any, Pattern

INTERFACE_RE = re.compile(r"^interface\s+(?P<name>\S+)$")
MAC_VRF_RE = re.compile(r"^mac\s+vrf\s+(?P<name>\S+)$")
# S0_NUMBER_RE = re.compile(r"SO\d+", re.IGNORECASE)


class OcnosConfigParser:
    def __init__(self, config: Path | str):
        config_text: str | None = None
        if isinstance(config, Path):
            config_text = config.read_text(encoding="utf-8", errors="ignore")
        elif isinstance(config, str):
            config_text = config
        else:
            raise ValueError("Invalid content type submitted for config")

        if not config_text:
            raise ValueError("Empty config data given")

        self.config: str = config_text

    def _parse_vlan_list(self, vlan_text: str) -> list[int]:
        """Parse ranges/lists like '10,20,30-32' into explicit ints."""
        vlans: list[int] = []
        for part in vlan_text.split(","):
            token = part.strip()
            if not token:
                continue
            if "-" in token:
                start_text, end_text = token.split("-", 1)
                try:
                    start = int(start_text)
                    end = int(end_text)
                except ValueError:
                    continue
                if start <= end:
                    vlans.extend(range(start, end + 1))
                continue

            try:
                vlans.append(int(token))
            except ValueError:
                continue

        return sorted(set(vlans))

    def parse_interfaces(self, interface_entry: list[str]) -> list[Interface]:
        header: Pattern[str] = re.compile(
            r"^interface\s+(\S+)(?:\s+(switchport))?$", re.M
        )
        switch_port: Pattern[str] = re.compile(r"^\s*switchport\s*$", re.M)
        description: Pattern[str] = re.compile(r"^\s*description\s+(.+)$", re.M)
        shutdown: Pattern[str] = re.compile(r"^\s*shutdown\s*$", re.M)
        no_shutdown: Pattern[str] = re.compile(r"^\s*no shutdown\s*$", re.M)
        mtu: Pattern[str] = re.compile(r"^\s*mtu\s+(\d+)\s*$", re.M)
        channel_group: Pattern[str] = re.compile(r"^\s*channel-group\s+(\d+)\b", re.M)
        access_vlan: Pattern[str] = re.compile(
            r"^\s*switchport\s+access\s+vlan\s+(\d+)\s*$", re.M
        )

        interfaces: list[Interface] = []

        for intf in interface_entry:
            header_match = header.search(intf)
            if header_match is None:
                continue

            intf_name = header_match.group(1)
            if not intf_name or not isinstance(intf_name, str):
                raise ValueError(f"Invalid interface name: {intf_name}")

            has_switchport = bool(header_match.group(2)) or bool(
                switch_port.search(intf)
            )

            description_match = description.search(intf)

            intf_description = (
                description_match.group(1).strip() if description_match else None
            )

            if (
                "." in intf_name
            ):  # and intf_description and S0_NUMBER_RE.search(intf_description):
                # vlan interface
                continue

            is_enabled = True
            if shutdown.search(intf):
                is_enabled = False
            if no_shutdown.search(intf):
                is_enabled = True

            mtu_match = mtu.search(intf)
            intf_mtu = int(mtu_match.group(1)) if mtu_match else None

            channel_group_match = channel_group.search(intf)
            lag_member_of = (
                f"po{channel_group_match.group(1)}" if channel_group_match else None
            )

            access_vlan_match = access_vlan.search(intf)
            intf_access_vlan = (
                int(access_vlan_match.group(1)) if access_vlan_match else None
            )

            mode = "routed"
            if has_switchport:
                mode = "access"

            interfaces.append(
                Interface(
                    name=intf_name,
                    description=intf_description,
                    enabled=is_enabled,
                    mtu=intf_mtu,
                    mode=mode,
                    access_vlan=intf_access_vlan,
                    lag_member_of=lag_member_of,
                )
            )

        return interfaces

    def parse_vlans(
        self, vlan_entry: list[str], interface_entry: list[str] | None = None
    ) -> list[Vlan]:
        header: Pattern[str] = re.compile(r"^vlan\s+(\d+)$", re.M)
        name: Pattern[str] = re.compile(r"^\s*name\s+(.+)$", re.M)
        s_tag: Pattern[str] = re.compile(
            r"^\s*(?:s-tag|service-vlan)\s+(\d+)\s*$", re.M
        )
        interface_header: Pattern[str] = re.compile(
            r"^interface\s+(\S+)(?:\s+(switchport))?$", re.M
        )
        description: Pattern[str] = re.compile(r"^\s*description\s+(.+)$", re.M)

        vlans: list[Vlan] = []
        seen_vlans: set[tuple[int, str | None, int | None]] = set()

        for vlan_block in vlan_entry:
            header_match = header.search(vlan_block)

            if header_match is None:
                continue

            vlan_id = int(header_match.group(1))

            name_match = name.search(vlan_block)
            vlan_name = name_match.group(1).strip() if name_match else None

            s_tag_match = s_tag.search(vlan_block)
            vlan_s_tag = int(s_tag_match.group(1)) if s_tag_match else None
            vlan_key = (vlan_id, vlan_name, vlan_s_tag)

            if vlan_key in seen_vlans:
                continue
            seen_vlans.add(vlan_key)

            vlans.append(
                Vlan(
                    vlan_id=vlan_id,
                    name=vlan_name,
                    s_tag=vlan_s_tag,
                )
            )

        if interface_entry is not None:
            for intf in interface_entry:
                header_match = interface_header.search(intf)

                if header_match is None:
                    continue

                intf_name = header_match.group(1)

                if "." not in intf_name:
                    continue

                desc_match = description.search(intf)

                if desc_match is None:
                    continue

                intf_description = desc_match.group(1).strip()

                # if not S0_NUMBER_RE.search(intf_description):
                #     continue

                _, vlan_part = intf_name.split(".", 1)

                if not vlan_part.isdigit():
                    continue

                vlan_id = int(vlan_part)
                vlan_key = (vlan_id, intf_description, None)

                if vlan_key in seen_vlans:
                    continue

                seen_vlans.add(vlan_key)

                vlans.append(
                    Vlan(
                        vlan_id=vlan_id,
                        name=intf_description,
                        s_tag=None,
                    )
                )

        return vlans

    def parse_network_instances(
        self, network_instance_entry: list[str]
    ) -> list[RoutingInstance]:
        header: Pattern[str] = re.compile(r"^mac\s+vrf\s+(\S+)$", re.M)
        rd: Pattern[str] = re.compile(r"^\s*rd\s+(\S+)\s*$", re.M)
        rt_both: Pattern[str] = re.compile(r"^\s*route-target\s+both\s+(\S+)\s*$", re.M)
        rt_import: Pattern[str] = re.compile(
            r"^\s*route-target\s+import\s+(\S+)\s*$", re.M
        )
        rt_export: Pattern[str] = re.compile(
            r"^\s*route-target\s+export\s+(\S+)\s*$", re.M
        )

        network_instances: list[RoutingInstance] = []

        for instance_block in network_instance_entry:
            header_match = header.search(instance_block)
            if header_match is None:
                continue

            instance_name = header_match.group(1)

            rd_match = rd.search(instance_block)
            rd_value = rd_match.group(1) if rd_match else None

            rt_match = rt_both.search(instance_block)
            if rt_match is None:
                rt_match = rt_import.search(instance_block)
            if rt_match is None:
                rt_match = rt_export.search(instance_block)

            rt_value = rt_match.group(1) if rt_match else None

            if rd_value is None or rt_value is None:
                continue

            network_instances.append(
                RoutingInstance(
                    instance_name=instance_name,
                    instance_type="mac-vrf",
                    rd=rd_value,
                    rt_rd=rt_value,
                )
            )

        return network_instances

    def parse_lags(self, interface_entry: list[str]) -> list[Lag]:
        header: Pattern[str] = re.compile(
            r"^interface\s+(\S+)(?:\s+(switchport))?$", re.M
        )
        description: Pattern[str] = re.compile(r"^\s*description\s+(.+)$", re.M)
        shutdown: Pattern[str] = re.compile(r"^\s*shutdown\s*$", re.M)
        no_shutdown: Pattern[str] = re.compile(r"^\s*no shutdown\s*$", re.M)
        mtu: Pattern[str] = re.compile(r"^\s*mtu\s+(\d+)\s*$", re.M)
        switch_port: Pattern[str] = re.compile(r"^\s*switchport\s*$", re.M)
        access_vlan: Pattern[str] = re.compile(
            r"^\s*switchport\s+access\s+vlan\s+(\d+)\s*$", re.M
        )
        trunk_allowed: Pattern[str] = re.compile(
            r"^\s*switchport\s+trunk\s+allowed\s+vlan(?:\s+add)?\s+(.+)$", re.M
        )
        channel_group: Pattern[str] = re.compile(
            r"^\s*channel-group\s+(\d+)(?:\s+mode\s+(active|passive|on))?\b", re.M
        )
        min_links: Pattern[str] = re.compile(r"^\s*lacp\s+min-links\s+(\d+)\s*$", re.M)
        lag_system_mac: Pattern[str] = re.compile(
            r"^\s*evpn\s+multi-homed\s+system-mac\s+([0-9A-Fa-f.]+)\s*$", re.M
        )

        lags: list[Lag] = []
        members_by_lag: dict[str, list[Interface]] = {}
        lacp_by_lag: dict[str, str] = {}

        for intf in interface_entry:
            header_match = header.search(intf)
            if header_match is None:
                continue

            intf_name = header_match.group(1)
            if "." in intf_name:
                continue

            channel_group_match = channel_group.search(intf)
            if channel_group_match is None:
                continue

            lag_name = f"po{channel_group_match.group(1)}"
            members_by_lag.setdefault(lag_name, []).append(Interface(name=intf_name))

            mode = channel_group_match.group(2)
            if mode == "on":
                lacp_by_lag[lag_name] = "static"
            elif mode in {"active", "passive"}:
                lacp_by_lag[lag_name] = mode

        for intf in interface_entry:
            header_match = header.search(intf)
            if header_match is None:
                continue

            lag_name = header_match.group(1)
            if not re.fullmatch(r"po\d+", lag_name):
                continue

            has_switchport = bool(header_match.group(2)) or bool(
                switch_port.search(intf)
            )
            description_match = description.search(intf)
            lag_description = (
                description_match.group(1).strip() if description_match else None
            )

            is_enabled = True
            if shutdown.search(intf):
                is_enabled = False
            if no_shutdown.search(intf):
                is_enabled = True

            mtu_match = mtu.search(intf)
            lag_mtu = int(mtu_match.group(1)) if mtu_match else None

            access_vlan_match = access_vlan.search(intf)
            lag_access_vlan = (
                int(access_vlan_match.group(1)) if access_vlan_match else None
            )

            trunk_vlans: list[Vlan] = []
            trunk_allowed_match = trunk_allowed.search(intf)
            if trunk_allowed_match:
                for vlan_id in self._parse_vlan_list(trunk_allowed_match.group(1)):
                    trunk_vlans.append(Vlan(vlan_id=vlan_id, s_tag=None))

            mode = "routed"
            if has_switchport:
                mode = "trunk" if trunk_vlans else "access"

            min_links_match = min_links.search(intf)
            lag_min_links = int(min_links_match.group(1)) if min_links_match else 1

            lag_system_mac_match = lag_system_mac.search(intf)
            lag_system_mac_value = (
                lag_system_mac_match.group(1) if lag_system_mac_match else None
            )

            lags.append(
                Lag(
                    name=lag_name,
                    description=lag_description,
                    enabled=is_enabled,
                    mtu=lag_mtu,
                    mode=mode,
                    access_vlan=lag_access_vlan,
                    trunk_vlans=trunk_vlans,
                    members=members_by_lag.get(lag_name, []),
                    lacp_mode=lacp_by_lag.get(lag_name, "active"),  # pyright: ignore[reportArgumentType]  # ty:ignore[invalid-argument-type]
                    min_links=lag_min_links,
                    system_mac=lag_system_mac_value,
                )
            )

        return lags

    def parse_evpns(
        self, interface_entry: list[str], network_instances: list[RoutingInstance]
    ) -> list[Evpn]:
        header: Pattern[str] = re.compile(
            r"^interface\s+(\S+)(?:\s+(switchport))?$", re.M
        )
        description: Pattern[str] = re.compile(r"^\s*description\s+(.+)$", re.M)
        encapsulation: Pattern[str] = re.compile(
            r"^\s*encapsulation\s+dot1(?:q|ad)\s+(\d+)\s*$", re.M
        )
        vpn_id: Pattern[str] = re.compile(r"^\s*map\s+vpn-id\s+(\d+)\s*$", re.M)

        rd_by_instance: dict[str, str] = {
            instance.instance_name: instance.rd for instance in network_instances
        }

        evpns: list[Evpn] = []
        seen: set[tuple[str, int, int]] = set()

        for intf in interface_entry:
            header_match = header.search(intf)
            if header_match is None:
                continue

            intf_name = header_match.group(1)
            if "." not in intf_name:
                continue

            description_match = description.search(intf)
            if description_match is None:
                continue
            service_name = description_match.group(1).strip()

            vlan_match = encapsulation.search(intf)
            vpn_id_match = vpn_id.search(intf)
            if vlan_match is None or vpn_id_match is None:
                continue

            vlan_id = int(vlan_match.group(1))
            vni = int(vpn_id_match.group(1))

            rd_value = rd_by_instance.get(service_name)
            if rd_value is None:
                continue

            asn_text = rd_value.split(":", 1)[0]
            try:
                asn = int(asn_text)
            except ValueError:
                continue

            key = (service_name, vlan_id, vni)
            if key in seen:
                continue
            seen.add(key)

            evpns.append(
                Evpn(
                    vlan=Vlan(vlan_id=vlan_id, name=service_name, s_tag=None),
                    description=service_name,
                    asn=asn,
                    vni=vni,
                )
            )

        return evpns

    def parse_asn(self) -> Asn | None:
        match = re.search(r"^router bgp\s+(\d+)", self.config, flags=re.M)
        if match is None:
            print("failed to detect any asn")
            return None

        try:
            return Asn(asn=int(match.group(1)))
        except ValueError:
            return None

    def parse_config(self) -> dict[str, Any]:
        config_parts = [
            entry.strip("\n") for entry in re.split(r"^!", self.config, flags=re.M)
        ]

        interface_data = [
            entry for entry in config_parts if entry.startswith("interface ")
        ]
        vlan_data = [entry for entry in config_parts if entry.startswith("vlan ")]
        network_instance_data = [
            entry for entry in config_parts if entry.startswith("mac vrf ")
        ]

        interfaces: list[Interface] = self.parse_interfaces(interface_data)
        lags: list[Lag] = self.parse_lags(interface_data)
        vlans: list[Vlan] = self.parse_vlans(vlan_data, interface_entry=interface_data)
        network_instances: list[RoutingInstance] = self.parse_network_instances(
            network_instance_data
        )
        evpns: list[Evpn] = self.parse_evpns(interface_data, network_instances)
        asn = self.parse_asn()
        return Config(
            interfaces=interfaces,
            lags=lags,
            vlans=vlans,
            vrfs=network_instances,
            evpns=evpns,
            asn=asn,
        )


class OcnosConfigXMLParser:
    ns: dict[str, str] = {
        "oc": "http://www.ipinfusion.com/yang/ocnos/ipi-interface",
        "agg": "http://www.ipinfusion.com/yang/ocnos/ipi-if-aggregate",
        "ext": "http://www.ipinfusion.com/yang/ocnos/ipi-if-extended",
        "evpn": "http://www.ipinfusion.com/yang/ocnos/ipi-ethernet-vpn",
        "ni": "http://www.ipinfusion.com/yang/ocnos/ipi-network-instance",
        "vrf": "http://www.ipinfusion.com/yang/ocnos/ipi-vrf",
        "bgp": "http://www.ipinfusion.com/yang/ocnos/ipi-bgp-vrf",
        "bgp_core": "http://www.ipinfusion.com/yang/ocnos/ipi-bgp",
        "vx": "http://www.ipinfusion.com/yang/ocnos/ipi-vxlan",
    }

    def __init__(self, config: Element | Path | str):
        self.config: Element = self._parse_input_data(config)

    def _parse_input_data(self, input_config: Element | Path | str) -> Element:
        match input_config:
            case Element():
                return input_config
            case Path():
                if not input_config.exists():
                    raise ValueError(
                        f"Config path does not exist: {input_config.absolute()}"
                    )
                config_text = input_config.read_text(encoding="utf-8", errors="ignore")
            case str():
                config_text = input_config
            case _:
                raise ValueError("Invalid content type submitted for config")

        if not config_text or not config_text.strip():
            raise ValueError("Empty config data given")

        try:
            return etree.fromstring(config_text.encode("utf-8"))
        except etree.XMLSyntaxError as exc:
            raise ValueError(f"Invalid XML config data: {exc}") from exc

    def parse_interfaces(self) -> list[Interface]:
        interfaces: list[Interface] = []
        interfaces_by_name: dict[str, Interface] = {}
        trunk_vlans_by_parent: dict[str, list[Vlan]] = {}

        for intf in self.config.iterfind(
            ".//oc:interfaces/oc:interface", namespaces=self.ns
        ):
            # Name is the only actually mandatory attrib
            intf_name = intf.findtext("oc:name", namespaces=self.ns)
            if not intf_name:
                intf_name = intf.findtext("oc:config/oc:name", namespaces=self.ns)
            if not intf_name:
                raise ValueError("Unable to determine name from interface data")

            # vlan interface
            if "." in intf_name:
                parent_name = intf_name.split(".", 1)[0]
                vlan_ids = {
                    vlan_text.text
                    for vlan_text in intf.xpath(
                        ".//ext:subinterface-encapsulation//ext:config/ext:outer-vlan-id | .//ext:subinterface-encapsulation//ext:config/ext:inner-vlan-id",
                        namespaces=self.ns,
                    )
                    if vlan_text.text is not None
                }

                if vlan_ids:
                    trunk_vlans = trunk_vlans_by_parent.setdefault(parent_name, [])
                    existing = {v.vlan_id for v in trunk_vlans}
                    for vlan_id in vlan_ids:
                        if vlan_id not in existing:
                            trunk_vlans.append(Vlan(vlan_id=vlan_id, s_tag=None))
                            existing.add(vlan_id)

                    parent_interface = interfaces_by_name.get(parent_name)
                    if parent_interface is not None:
                        parent_interface.trunk_vlans = trunk_vlans
                        if (
                            parent_interface.mode != "routed"
                            and parent_interface.trunk_vlans
                        ):
                            parent_interface.mode = "trunk"
                    continue

            mtu_text = intf.findtext("oc:config/oc:mtu", namespaces=self.ns)
            intf_mtu = int(mtu_text) if mtu_text and mtu_text.isdigit() else None
            intf_description = intf.findtext(
                "oc:config/oc:description", namespaces=self.ns
            )

            # It seems theres only a flag rather than something striclt enabled
            is_enabled = intf.find("oc:config/oc:shutdown", namespaces=self.ns) is None
            has_switchport = (
                intf.find("oc:config/oc:enable-switchport", namespaces=self.ns)
                is not None
            )

            mode = "access" if has_switchport else "routed"
            trunk_vlans = trunk_vlans_by_parent.get(intf_name, [])

            if has_switchport and trunk_vlans:
                mode = "trunk"

            vlan_text = intf.findtext(
                ".//ext:subinterface-encapsulation//ext:config/ext:outer-vlan-id",
                namespaces=self.ns,
            )
            intf_access_vlan = (
                int(vlan_text) if vlan_text and vlan_text.isdigit() else None
            )

            aggregate_id_text = intf.findtext(
                "agg:member-aggregation/agg:config/agg:aggregate-id",
                namespaces=self.ns,
            )
            lag_member_of = (
                f"po{aggregate_id_text}"
                if aggregate_id_text and aggregate_id_text.isdigit()
                else None
            )

            interface = Interface(
                name=intf_name,
                description=intf_description,
                enabled=is_enabled,
                mtu=intf_mtu,
                mode=mode,
                access_vlan=intf_access_vlan,
                trunk_vlans=trunk_vlans,
                lag_member_of=lag_member_of,
            )

            interfaces_by_name[intf_name] = interface
            interfaces.append(interface)

        return interfaces

    def parse_vlans(self) -> list[Vlan]:
        vlans: list[Vlan] = []
        seen_vlan_names: set[str] = set()

        for intf in self.config.iterfind(
            ".//oc:interfaces/oc:interface", namespaces=self.ns
        ):
            intf_name = intf.findtext("oc:name", namespaces=self.ns)

            if not intf_name:
                # fallback for name just incase
                intf_name = intf.findtext("oc:config/oc:name", namespaces=self.ns)

            if not intf_name or "." not in intf_name:
                continue

            intf_description = intf.findtext(
                "oc:config/oc:description", namespaces=self.ns
            )

            # if not intf_description or not S0_NUMBER_RE.search(intf_description):
            #     continue

            _, vlan_part = intf_name.split(".", 1)
            vlan_name = vlan_part.strip()

            if not vlan_name.isdigit():
                continue

            vlan_id = int(vlan_name)

            if f"{vlan_id}:{intf_description}" in seen_vlan_names:
                print(f"{vlan_id}:{intf_description} has been seen before")
                continue

            seen_vlan_names.add(f"{vlan_id}:{intf_description}")

            vlans.append(
                Vlan(
                    vlan_id=vlan_id,
                    name=intf_description,
                    s_tag=None,
                )
            )

        return vlans

    def parse_network_instances(self) -> list[RoutingInstance]:
        network_instances: list[RoutingInstance] = []

        for instance in self.config.iterfind(
            ".//ni:network-instances/ni:network-instance", namespaces=self.ns
        ):
            instance_name = instance.findtext("ni:instance-name", namespaces=self.ns)
            if not instance_name:
                instance_name = instance.findtext(
                    "ni:config/ni:instance-name", namespaces=self.ns
                )
            if not instance_name:
                continue

            instance_type = instance.findtext("ni:instance-type", namespaces=self.ns)
            if not instance_type:
                instance_type = instance.findtext(
                    "ni:config/ni:instance-type", namespaces=self.ns
                )
            if instance_type != "mac-vrf":
                continue

            rd_value = instance.findtext(
                "vrf:vrf/bgp:bgp-vrf/bgp:config/bgp:rd-string",
                namespaces=self.ns,
            )
            if not rd_value:
                rd_value = instance.findtext(".//bgp:rd-string", namespaces=self.ns)

            rt_value = instance.findtext(
                "vrf:vrf/bgp:bgp-vrf/bgp:route-target/bgp:config/bgp:rt-rd-string",
                namespaces=self.ns,
            )
            if not rt_value:
                rt_value = instance.findtext(
                    ".//bgp:route-target/bgp:rt-rd-string",
                    namespaces=self.ns,
                )

            if not rd_value or not rt_value:
                continue

            network_instances.append(
                RoutingInstance(
                    instance_name=instance_name,
                    instance_type=instance_type,
                    rd=rd_value,
                    rt_rd=rt_value,
                )
            )

        return network_instances

    def parse_lags(self) -> list[Lag]:
        lags: list[Lag] = []
        members_by_lag: dict[str, list[Interface]] = {}
        lacp_by_lag: dict[str, str] = {}
        system_mac_by_lag: dict[str, str] = {}
        trunk_vlans_by_parent: dict[str, list[Vlan]] = {}
        lag_interfaces_by_name: dict[str, Lag] = {}

        for evpn_intf in self.config.iterfind(
            ".//evpn:interfaces/evpn:interface", namespaces=self.ns
        ):
            evpn_name = evpn_intf.findtext("evpn:name", namespaces=self.ns)
            if not evpn_name:
                evpn_name = evpn_intf.findtext(
                    "evpn:config/evpn:name", namespaces=self.ns
                )
            if not evpn_name:
                continue

            evpn_system_mac = evpn_intf.findtext(
                "evpn:config/evpn:system-mac", namespaces=self.ns
            )
            if evpn_system_mac:
                system_mac_by_lag[evpn_name] = evpn_system_mac

        for intf in self.config.iterfind(
            ".//oc:interfaces/oc:interface", namespaces=self.ns
        ):
            intf_name = intf.findtext("oc:name", namespaces=self.ns)

            if not intf_name:
                intf_name = intf.findtext("oc:config/oc:name", namespaces=self.ns)

            if not intf_name:
                continue

            if "." in intf_name:
                parent_name = intf_name.split(".", 1)[0]
                vlan_ids = {
                    vlan_text.text
                    for vlan_text in intf.xpath(
                        ".//ext:subinterface-encapsulation//ext:config/ext:outer-vlan-id | .//ext:subinterface-encapsulation//ext:config/ext:inner-vlan-id",
                        namespaces=self.ns,
                    )
                    if vlan_text.text is not None
                }

                if vlan_ids:
                    trunk_vlans = trunk_vlans_by_parent.setdefault(parent_name, [])
                    existing = {v.vlan_id for v in trunk_vlans}
                    for vlan_id in vlan_ids:
                        if vlan_id not in existing:
                            trunk_vlans.append(Vlan(vlan_id=vlan_id, s_tag=None))
                            existing.add(vlan_id)

                    # update the parent so the data is not lost
                    parent_lag = lag_interfaces_by_name.get(parent_name)
                    if parent_lag is not None:
                        parent_lag.trunk_vlans = trunk_vlans
                        if parent_lag.mode != "routed" and parent_lag.trunk_vlans:
                            parent_lag.mode = "trunk"

                continue

            aggregate_id = intf.findtext(
                "agg:member-aggregation/agg:config/agg:aggregate-id",
                namespaces=self.ns,
            )

            if aggregate_id:
                if not aggregate_id.isdigit():
                    raise ValueError("LAG has non number id")

                #  po anmed by aggregate-id.
                lag_name = f"po{aggregate_id}"
                members_by_lag.setdefault(lag_name, []).append(
                    Interface(name=intf_name)
                )

                lacp_mode = intf.findtext(
                    "agg:member-aggregation/agg:config/agg:lacp-mode",
                    namespaces=self.ns,
                )

                if not lacp_mode:
                    raise ValueError("No LACP mode configured")

                if lacp_mode in {"active", "passive", "static"}:
                    lacp_by_lag[lag_name] = lacp_mode
                else:
                    raise ValueError(f"Unsupported LACP mode: {lacp_mode}")

                continue

            if not intf_name.startswith("po"):
                continue

            lag_name = intf_name
            lag_description = intf.findtext(
                "oc:config/oc:description", namespaces=self.ns
            )
            mtu_text = intf.findtext("oc:config/oc:mtu", namespaces=self.ns)
            lag_mtu = int(mtu_text) if mtu_text and mtu_text.isdigit() else None

            is_enabled = intf.find("oc:config/oc:shutdown", namespaces=self.ns) is None
            has_switchport = (
                intf.find("oc:config/oc:enable-switchport", namespaces=self.ns)
                is not None
            )

            vlan_text = intf.findtext(
                ".//ext:subinterface-encapsulation//ext:config/ext:outer-vlan-id",
                namespaces=self.ns,
            )
            lag_access_vlan = (
                int(vlan_text) if vlan_text and vlan_text.isdigit() else None
            )

            # set default incase it doesnt exist yet
            trunk_vlans = trunk_vlans_by_parent.setdefault(lag_name, [])
            mode = "access" if has_switchport else "routed"
            if has_switchport and trunk_vlans:
                mode = "trunk"

            lag_interfaces_by_name[lag_name] = Lag(
                name=lag_name,
                description=lag_description,
                enabled=is_enabled,
                mtu=lag_mtu,
                mode=mode,
                access_vlan=lag_access_vlan,
                trunk_vlans=trunk_vlans,
                members=members_by_lag.get(lag_name, []),
                system_mac=system_mac_by_lag.get(lag_name)
                or intf.findtext("oc:config/oc:system-mac", namespaces=self.ns),
            )

        for lag_name, lag_interface in lag_interfaces_by_name.items():
            if lag_name not in lacp_by_lag:
                continue

            lag_interface.members = members_by_lag.get(
                lag_name, []
            )  # Theres lags without members in the example conf
            lag_interface.lacp_mode = lacp_by_lag[lag_name]  # pyright: ignore[reportAttributeAccessIssue] # ty:ignore[invalid-assignment]

            lags.append(lag_interface)

        return lags

    def parse_evpns(self) -> list[Evpn]:
        # repeated call, maby cache?
        network_instances = self.parse_network_instances()
        rd_by_instance: dict[str, str] = {
            instance.instance_name: instance.rd for instance in network_instances
        }

        vni_by_instance: dict[str, int] = {}
        for tenant in self.config.iterfind(
            ".//vx:vxlan-tenants/vx:vxlan-tenant", namespaces=self.ns
        ):
            vni_text = tenant.findtext("vx:vxlan-identifier", namespaces=self.ns)
            if not vni_text:
                vni_text = tenant.findtext(
                    "vx:config/vx:vxlan-identifier", namespaces=self.ns
                )
            instance_name = tenant.findtext("vx:config/vx:vrf-name", namespaces=self.ns)

            if not instance_name or not vni_text or not vni_text.isdigit():
                continue

            vni_by_instance[instance_name] = int(vni_text)

        evpns: list[Evpn] = []
        seen: set[tuple[str, int, int]] = set()

        for intf in self.config.iterfind(
            ".//oc:interfaces/oc:interface", namespaces=self.ns
        ):
            intf_name = intf.findtext("oc:name", namespaces=self.ns)
            if not intf_name:
                intf_name = intf.findtext("oc:config/oc:name", namespaces=self.ns)
            if not intf_name or "." not in intf_name:
                continue

            service_name = intf.findtext("oc:config/oc:description", namespaces=self.ns)
            if not service_name:
                continue
            service_name = service_name.strip()

            vlan_text = intf.findtext(
                ".//ext:subinterface-encapsulation//ext:config/ext:outer-vlan-id",
                namespaces=self.ns,
            )
            if not vlan_text or not vlan_text.isdigit():
                continue
            vlan_id = int(vlan_text)

            vni = vni_by_instance.get(service_name)
            rd_value = rd_by_instance.get(service_name)
            if vni is None or rd_value is None:
                continue

            asn_text = rd_value.split(":", 1)[0]
            try:
                asn = int(asn_text)
            except ValueError:
                continue

            key = (service_name, vlan_id, vni)
            if key in seen:
                continue
            seen.add(key)

            # nothing looks like a s_tag which i guess is fine?
            # s_tag=None
            evpns.append(
                Evpn(
                    vlan=Vlan(vlan_id=vlan_id, name=service_name, s_tag=None),
                    description=service_name,
                    asn=asn,
                    vni=vni,
                )
            )

        return evpns

    def parse_asn(self) -> Asn | None:
        for bgp_instance in self.config.iterfind(
            ".//bgp_core:bgp/bgp_core:bgp-instance", namespaces=self.ns
        ):
            bgp_as = bgp_instance.findtext("bgp_core:bgp-as", namespaces=self.ns)
            if not bgp_as:
                bgp_as = bgp_instance.findtext(
                    "bgp_core:config/bgp_core:bgp-as", namespaces=self.ns
                )

            if bgp_as is None or not bgp_as.strip():
                continue

            try:
                return Asn(asn=int(bgp_as))
            except ValueError:
                continue

        return None

    def parse_config(self) -> dict[str, Any]:
        interfaces = self.parse_interfaces()
        lags = self.parse_lags()
        vlans = self.parse_vlans()
        network_instances = self.parse_network_instances()
        evpns = self.parse_evpns()
        asn = self.parse_asn()
        return Config(
            interfaces=interfaces,
            lags=lags,
            vlans=vlans,
            vrfs=network_instances,
            evpns=evpns,
            asn=asn,
        )
