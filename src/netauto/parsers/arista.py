import re
import json
from pathlib import Path
from typing import Any, Pattern
from netauto.models import Evpn, Interface, Lag, RoutingInstance, Vlan


class AristaConfigParser:
    def __init__(self, config: Path | str):
        raw: str
        if isinstance(config, Path):
            raw = config.read_text(encoding="utf-8", errors="ignore")
        elif isinstance(config, str):
            raw = config
        else:
            raise ValueError("Invalid content type submitted for config")

        if not raw.strip():
            raise ValueError("Empty config data given")

        self.config: str = self._extract_config(raw)

    def _extract_config(self, raw: str) -> str:
        raw = raw.strip()
        # cli config not just json
        if not raw.startswith("{"):
            return raw

        # try to load json
        try:
            parsed_data = json.loads(raw)
        except json.JSONDecodeError:
            raise ValueError("Failed to parse input data")

        outputs: list[str] = []

        # turn the json into a string
        if isinstance(parsed_data, dict):
            result = parsed_data.get("result")
            if isinstance(result, list):
                for entry in result:
                    if isinstance(entry, dict):
                        output = entry.get("output")
                        if isinstance(output, str):
                            outputs.append(output)
                    elif isinstance(entry, str):
                        outputs.append(entry)

        return "\n".join(outputs).strip()

    def _parse_id_list(self, text: str) -> list[int]:
        ids: list[int] = []
        for part in text.split(","):
            token = part.strip()
            if not token or token.lower() == "none":
                continue
            if "-" in token:
                left, right = token.split("-", 1)
                try:
                    start = int(left)
                    end = int(right)
                except ValueError:
                    continue
                if start <= end:
                    ids.extend(range(start, end + 1))
                continue
            try:
                ids.append(int(token))
            except ValueError:
                continue
        return sorted(set(ids))

    def _collect_vlans(self, interface_entry: list[str]) -> dict[str, list[int]]:
        header: Pattern[str] = re.compile(r"^interface\s+(.+?)\.(\d+)$", re.M)
        dot1q_vlans: Pattern[str] = re.compile(
            r"^\s+encapsulation\s+dot1q\s+vlan\s+(\d+)\s*$", re.M
        )
        vlan_id_re: Pattern[str] = re.compile(r"^\s+vlan\s+id\s+(\d+)\s*$", re.M)

        vlans: dict[str, list[int]] = {}
        for intf in interface_entry:
            header_match = header.search(intf)
            if header_match is None:
                continue

            parent_name = header_match.group(1)
            vlan_ids: list[int] = []

            encap_match = dot1q_vlans.search(intf)
            if encap_match is not None:
                vlan_ids = self._parse_id_list(encap_match.group(1))
            else:
                vlan_id_match = vlan_id_re.search(intf)
                if vlan_id_match is not None:
                    vlan_ids = self._parse_id_list(vlan_id_match.group(1))
                else:
                    continue

            vlans.setdefault(parent_name, []).extend(vlan_ids)

        for parent_name, vlans_entry in vlans.items():
            vlans[parent_name] = sorted(set(vlans_entry))

        return vlans

    def parse_interfaces(self, interface_entry: list[str]) -> list[Interface]:
        header: Pattern[str] = re.compile(r"^interface\s+(\S+)$", re.M)
        description: Pattern[str] = re.compile(r"^\s+description\s+(.+)$", re.M)
        shutdown: Pattern[str] = re.compile(r"^\s+shutdown\s*$", re.M)
        no_shutdown: Pattern[str] = re.compile(r"^\s+no shutdown\s*$", re.M)
        mtu: Pattern[str] = re.compile(r"^\s+mtu\s+(\d+)\s*$", re.M)
        no_switchport: Pattern[str] = re.compile(r"^\s+no switchport\s*$", re.M)
        sw_mode_trunk: Pattern[str] = re.compile(r"^\s+switchport mode trunk\s*$", re.M)
        access_vlan: Pattern[str] = re.compile(
            r"^\s+switchport access vlan\s+(\d+)\s*$", re.M
        )
        trunk_allowed: Pattern[str] = re.compile(
            r"^\s+switchport trunk allowed vlan\s+(.+)$", re.M
        )
        channel_group: Pattern[str] = re.compile(
            r"^\s+channel-group\s+(\d+)(?:\s+mode\s+\S+)?\s*$", re.M
        )

        interfaces: list[Interface] = []
        subinterface_vlans = self._collect_vlans(interface_entry)

        for intf in interface_entry:
            header_match = header.search(intf)
            if header_match is None:
                continue

            name = header_match.group(1)
            desc_match = description.search(intf)
            description_value = desc_match.group(1).strip() if desc_match else None

            enabled = True
            if shutdown.search(intf):
                enabled = False
            if no_shutdown.search(intf):
                enabled = True

            mtu_match = mtu.search(intf)
            mtu_value = int(mtu_match.group(1)) if mtu_match else None

            access_match = access_vlan.search(intf)
            access_value = int(access_match.group(1)) if access_match else None

            trunk_vlans: list[Vlan] = []
            trunk_match = trunk_allowed.search(intf)
            if trunk_match:
                for vlan_id in self._parse_id_list(trunk_match.group(1)):
                    trunk_vlans.append(Vlan(vlan_id=vlan_id))  # pyright: ignore[reportCallIssue]

            for vlan_id in subinterface_vlans.get(name, []):
                if not any(existing.vlan_id == vlan_id for existing in trunk_vlans):
                    trunk_vlans.append(Vlan(vlan_id=vlan_id))  # pyright: ignore[reportCallIssue]

            cg_match = channel_group.search(intf)
            lag_member_of = f"Port-Channel{cg_match.group(1)}" if cg_match else None

            mode = "access"
            if no_switchport.search(intf):
                mode = "routed"
            elif sw_mode_trunk.search(intf) or trunk_vlans:
                mode = "trunk"

            interfaces.append(
                Interface(
                    name=name,
                    description=description_value,
                    enabled=enabled,
                    mtu=mtu_value,
                    mode=mode,
                    access_vlan=access_value,
                    trunk_vlans=trunk_vlans,
                    lag_member_of=lag_member_of,
                )
            )

        return interfaces

    def parse_vlans(self, vlan_entry: list[str]) -> list[Vlan]:
        header: Pattern[str] = re.compile(r"^vlan\s+(.+)$", re.M)
        name: Pattern[str] = re.compile(r"^\s+name\s+(.+)$", re.M)

        vlans: list[Vlan] = []
        for vlan_block in vlan_entry:
            header_match = header.search(vlan_block)
            if header_match is None:
                continue

            ids = self._parse_id_list(header_match.group(1))
            if not ids:
                continue

            name_match = name.search(vlan_block)
            vlan_name = name_match.group(1).strip() if name_match else None
            for vlan_id in ids:
                vlans.append(Vlan(vlan_id=vlan_id, name=vlan_name, s_tag=None))

        return vlans

    def parse_lags(self, interface_entry: list[str]) -> list[Lag]:
        header: Pattern[str] = re.compile(r"^interface\s+(Port-Channel\d+)$", re.M)
        description: Pattern[str] = re.compile(r"^\s+description\s+(.+)$", re.M)
        shutdown: Pattern[str] = re.compile(r"^\s+shutdown\s*$", re.M)
        no_shutdown: Pattern[str] = re.compile(r"^\s+no shutdown\s*$", re.M)
        mtu: Pattern[str] = re.compile(r"^\s+mtu\s+(\d+)\s*$", re.M)
        no_switchport: Pattern[str] = re.compile(r"^\s+no switchport\s*$", re.M)
        sw_mode_trunk: Pattern[str] = re.compile(r"^\s+switchport mode trunk\s*$", re.M)
        access_vlan: Pattern[str] = re.compile(
            r"^\s+switchport access vlan\s+(\d+)\s*$", re.M
        )
        trunk_allowed: Pattern[str] = re.compile(
            r"^\s+switchport trunk allowed vlan\s+(.+)$", re.M
        )
        min_links: Pattern[str] = re.compile(
            r"^\s+port-channel min-links\s+(\d+)\s*$", re.M
        )
        lag_system_mac: Pattern[str] = re.compile(
            r"^\s+lacp system-id\s+([0-9A-Fa-f.]+)\s*$", re.M
        )

        member_header: Pattern[str] = re.compile(r"^interface\s+(\S+)$", re.M)
        member_group: Pattern[str] = re.compile(
            r"^\s+channel-group\s+(\d+)(?:\s+mode\s+(active|passive|on))?\s*$", re.M
        )
        member_trunk_allowed: Pattern[str] = re.compile(
            r"^\s+switchport trunk allowed vlan\s+(.+)$", re.M
        )
        member_access_vlan: Pattern[str] = re.compile(
            r"^\s+switchport access vlan\s+(\d+)\s*$", re.M
        )

        members_by_lag: dict[str, list[Interface]] = {}
        lacp_mode_by_lag: dict[str, str] = {}
        member_vlans_by_lag: dict[str, list[int]] = {}

        for intf in interface_entry:
            h = member_header.search(intf)
            if h is None:
                continue
            member_name = h.group(1)
            if member_name.startswith("Port-Channel"):
                continue
            m = member_group.search(intf)
            if m is None:
                continue

            lag_name = f"Port-Channel{m.group(1)}"
            members_by_lag.setdefault(lag_name, []).append(Interface(name=member_name))

            mode = m.group(2)
            if mode == "on":
                lacp_mode_by_lag[lag_name] = "static"
            elif mode in {"active", "passive"}:
                lacp_mode_by_lag[lag_name] = mode

            member_trunk = member_trunk_allowed.search(intf)
            member_access = member_access_vlan.search(intf)

            if member_trunk:
                member_vlans_by_lag.setdefault(lag_name, [])
                for vlan_id in self._parse_id_list(member_trunk.group(1)):
                    if vlan_id not in member_vlans_by_lag[lag_name]:
                        member_vlans_by_lag[lag_name].append(vlan_id)
            elif member_access is not None:
                vlan_id = int(member_access.group(1))
                member_vlans_by_lag.setdefault(lag_name, [])
                if vlan_id not in member_vlans_by_lag[lag_name]:
                    member_vlans_by_lag[lag_name].append(vlan_id)

        subinterface_vlans = self._collect_vlans(interface_entry)
        lags: list[Lag] = []
        for intf in interface_entry:
            h = header.search(intf)
            if h is None:
                continue
            lag_name = h.group(1)

            d = description.search(intf)
            description_value = d.group(1).strip() if d else None

            enabled = True
            if shutdown.search(intf):
                enabled = False
            if no_shutdown.search(intf):
                enabled = True

            mtu_match = mtu.search(intf)
            mtu_value = int(mtu_match.group(1)) if mtu_match else None

            access_match = access_vlan.search(intf)
            access_value = int(access_match.group(1)) if access_match else None

            trunk_vlans: list[Vlan] = []
            trunk_match = trunk_allowed.search(intf)

            if trunk_match:
                for vlan_id in self._parse_id_list(trunk_match.group(1)):
                    trunk_vlans.append(Vlan(vlan_id=vlan_id))  # pyright: ignore[reportCallIssue]
    
            for vlan_id in subinterface_vlans.get(lag_name, []):
                if not any(existing.vlan_id == vlan_id for existing in trunk_vlans):
                    trunk_vlans.append(Vlan(vlan_id=vlan_id))  # pyright: ignore[reportCallIssue]

            for vlan_id in member_vlans_by_lag.get(lag_name, []):
                if not any(existing.vlan_id == vlan_id for existing in trunk_vlans):
                    trunk_vlans.append(Vlan(vlan_id=vlan_id))  # pyright: ignore[reportCallIssue]

            mode = "access"
            if no_switchport.search(intf):
                mode = "routed"
            elif sw_mode_trunk.search(intf) or trunk_vlans:
                mode = "trunk"

            min_links_match = min_links.search(intf)
            min_links_value = int(min_links_match.group(1)) if min_links_match else 1

            system_mac_match = lag_system_mac.search(intf)
            system_mac_value = system_mac_match.group(1) if system_mac_match else None

            lags.append(
                Lag(
                    name=lag_name,
                    description=description_value,
                    enabled=enabled,
                    mtu=mtu_value,
                    mode=mode,
                    access_vlan=access_value,
                    trunk_vlans=trunk_vlans,
                    members=members_by_lag.get(lag_name, []),
                    lacp_mode=lacp_mode_by_lag.get(
                        lag_name, "active"
                    ),  # ty:ignore[invalid-argument-type] # pyright: ignore[reportArgumentType]
                    min_links=min_links_value,
                    system_mac=system_mac_value,
                )
            )

        return lags

    def _find_bgp_block(self, config_parts: list[str]) -> str | None:
        for entry in config_parts:
            if entry.startswith("router bgp "):
                return entry
        return None

    def _parse_bgp_instances_and_vlan_map(
        self, bgp_block: str
    ) -> tuple[list[RoutingInstance], dict[int, tuple[str, str]]]:
        section_start: Pattern[str] = re.compile(
            r"^\s{3}(vlan-aware-bundle|vlan)\s+(.+)$", re.M
        )
        rd_re: Pattern[str] = re.compile(r"^\s{6}rd\s+(\S+)\s*$", re.M)
        rt_re: Pattern[str] = re.compile(r"^\s{6}route-target both\s+(\S+)\s*$", re.M)
        section_vlan_re: Pattern[str] = re.compile(r"^\s{6}vlan\s+(.+)$", re.M)

        starts = list(section_start.finditer(bgp_block))
        if not starts:
            return [], {}

        instances: list[RoutingInstance] = []
        rd_by_vlan: dict[int, tuple[str, str]] = {}

        for idx, match in enumerate(starts):
            section_type = match.group(1)
            section_name = match.group(2).strip()
            start = match.end()
            end = starts[idx + 1].start() if idx + 1 < len(starts) else len(bgp_block)
            section_body = bgp_block[start:end]

            rd_match = rd_re.search(section_body)
            rt_match = rt_re.search(section_body)
            if rd_match is None or rt_match is None:
                continue

            rd_value = rd_match.group(1)
            rt_value = rt_match.group(1)

            if section_type == "vlan":
                vlan_ids = self._parse_id_list(section_name)
                for vlan_id in vlan_ids:
                    instance_name = f"vlan-{vlan_id}"
                    instances.append(
                        RoutingInstance(
                            instance_name=instance_name,
                            instance_type="vlan",
                            rd=rd_value,
                            rt_rd=rt_value,
                        )
                    )
                    rd_by_vlan[vlan_id] = (rd_value, instance_name)
            else:
                instance_name = section_name
                instances.append(
                    RoutingInstance(
                        instance_name=instance_name,
                        instance_type="vlan-aware-bundle",
                        rd=rd_value,
                        rt_rd=rt_value,
                    )
                )
                for line_match in section_vlan_re.finditer(section_body):
                    for vlan_id in self._parse_id_list(line_match.group(1)):
                        rd_by_vlan[vlan_id] = (rd_value, instance_name)

        return instances, rd_by_vlan

    def parse_network_instances(self, config_parts: list[str]) -> list[RoutingInstance]:
        bgp_block = self._find_bgp_block(config_parts)
        if not bgp_block:
            return []
        instances, _ = self._parse_bgp_instances_and_vlan_map(bgp_block)
        return instances

    def parse_evpns(
        self, interface_entry: list[str], vlans: list[Vlan], config_parts: list[str]
    ) -> list[Evpn]:
        bgp_block = self._find_bgp_block(config_parts)
        if not bgp_block:
            return []

        _, rd_by_vlan = self._parse_bgp_instances_and_vlan_map(bgp_block)
        if not rd_by_vlan:
            return []

        vxlan_block = ""
        for intf in interface_entry:
            if intf.startswith("interface Vxlan1"):
                vxlan_block = intf
                break
        if not vxlan_block:
            return []

        vxlan_map_re: Pattern[str] = re.compile(
            r"^\s+vxlan vlan\s+(\d+)\s+vni\s+(\d+)\s*$", re.M
        )
        vlan_name_map = {v.vlan_id: v.name for v in vlans if v.name}

        evpns: list[Evpn] = []
        seen: set[tuple[int, int]] = set()
        for line in vxlan_map_re.finditer(vxlan_block):
            vlan_id = int(line.group(1))
            vni = int(line.group(2))
            if (vlan_id, vni) in seen:
                continue
            seen.add((vlan_id, vni))

            rd_info = rd_by_vlan.get(vlan_id)
            if rd_info is None:
                continue
            rd_value, instance_name = rd_info
            asn_text = rd_value.split(":", 1)[0]
            try:
                asn = int(asn_text)
            except ValueError:
                continue

            description = instance_name
            vlan_name = vlan_name_map.get(vlan_id)
            evpns.append(
                Evpn(
                    vlan=Vlan(vlan_id=vlan_id, name=vlan_name),  # pyright: ignore[reportCallIssue]
                    description=description,
                    asn=asn,
                    vni=vni,
                )
            )

        return evpns

    def parse_arista_config(self) -> dict[str, Any]:
        config_parts = [
            entry.strip("\n") for entry in re.split(r"^!", self.config, flags=re.M)
        ]

        interface_data = [
            entry for entry in config_parts if entry.startswith("interface ")
        ]
        vlan_data = [entry for entry in config_parts if entry.startswith("vlan ")]

        interfaces = self.parse_interfaces(interface_data)
        lags = self.parse_lags(interface_data)
        vlans = self.parse_vlans(vlan_data)
        network_instances = self.parse_network_instances(config_parts)
        evpns = self.parse_evpns(interface_data, vlans, config_parts)

        return {
            "interfaces": interfaces,
            "lags": lags,
            "vlans": vlans,
            "network_instances": network_instances,
            "evpns": evpns,
        }
