from argparse import Namespace
import argparse
import json
import re
from pathlib import Path
from typing import Any, Pattern
from netauto.models import Evpn, Interface, Lag, RoutingInstance, Vlan


class AristaConfigFileParser:
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

        self.config: str = self._extract_running_config(raw)

    def _extract_running_config(self, raw: str) -> str:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return raw

        if not isinstance(payload, dict):
            return raw

        result = payload.get("result")
        if not isinstance(result, list) or not result:
            return raw

        first = result[0]
        if not isinstance(first, dict):
            return raw

        output = first.get("output")
        if isinstance(output, str) and output.strip():
            return output

        return raw

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

    def parse_interfaces(self, interface_entry: list[str]) -> list[Interface]:
        header: Pattern[str] = re.compile(r"^interface\s+(\S+)$", re.M)
        description: Pattern[str] = re.compile(r"^\s+description\s+(.+)$", re.M)
        shutdown: Pattern[str] = re.compile(r"^\s+shutdown\s*$", re.M)
        no_shutdown: Pattern[str] = re.compile(r"^\s+no shutdown\s*$", re.M)
        mtu: Pattern[str] = re.compile(r"^\s+mtu\s+(\d+)\s*$", re.M)
        no_switchport: Pattern[str] = re.compile(r"^\s+no switchport\s*$", re.M)
        sw_mode_trunk: Pattern[str] = re.compile(r"^\s+switchport mode trunk\s*$", re.M)
        access_vlan: Pattern[str] = re.compile(r"^\s+switchport access vlan\s+(\d+)\s*$", re.M)
        trunk_allowed: Pattern[str] = re.compile(
            r"^\s+switchport trunk allowed vlan\s+(.+)$", re.M
        )
        channel_group: Pattern[str] = re.compile(
            r"^\s+channel-group\s+(\d+)(?:\s+mode\s+\S+)?\s*$", re.M
        )

        interfaces: list[Interface] = []
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
                    trunk_vlans.append(Vlan(vlan_id=vlan_id)) # pyright: ignore[reportCallIssue]

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
        access_vlan: Pattern[str] = re.compile(r"^\s+switchport access vlan\s+(\d+)\s*$", re.M)
        trunk_allowed: Pattern[str] = re.compile(
            r"^\s+switchport trunk allowed vlan\s+(.+)$", re.M
        )
        min_links: Pattern[str] = re.compile(r"^\s+port-channel min-links\s+(\d+)\s*$", re.M)

        member_header: Pattern[str] = re.compile(r"^interface\s+(\S+)$", re.M)
        member_group: Pattern[str] = re.compile(
            r"^\s+channel-group\s+(\d+)(?:\s+mode\s+(active|passive|on))?\s*$", re.M
        )

        members_by_lag: dict[str, list[Interface]] = {}
        lacp_mode_by_lag: dict[str, str] = {}

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
                    trunk_vlans.append(Vlan(vlan_id=vlan_id)) # pyright: ignore[reportCallIssue]

            mode = "access"
            if no_switchport.search(intf):
                mode = "routed"
            elif sw_mode_trunk.search(intf) or trunk_vlans:
                mode = "trunk"

            min_links_match = min_links.search(intf)
            min_links_value = int(min_links_match.group(1)) if min_links_match else 1

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
                    lacp_mode=lacp_mode_by_lag.get(lag_name, "active"),  # ty:ignore[invalid-argument-type] # pyright: ignore[reportArgumentType]
                    min_links=min_links_value,
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
                    vlan=Vlan(vlan_id=vlan_id, name=vlan_name), # pyright: ignore[reportCallIssue]
                    description=description,
                    asn=asn,
                    vni=vni,
                )
            )

        return evpns

    def parse_arista_config(self) -> dict[str, Any]:
        config_parts = [entry.strip("\n") for entry in re.split(r"^!", self.config, flags=re.M)]

        interface_data = [
            entry for entry in config_parts if entry.startswith("interface ")
        ]
        vlan_data = [
            entry for entry in config_parts if entry.startswith("vlan ")
        ]

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


def main() -> int:
    parser = argparse.ArgumentParser(description="parser for Arista JSON-wrapped config files")
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("./configs/arista/"),
        help="Path to a config file or directory of *.config.txt files",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("models/arista/"),
        help="Optional path to write JSON output",
    )
    args: Namespace = parser.parse_args()

    input_path: Path = args.input
    output_path: Path = args.output
    files = input_path.glob("*.config.txt")
    if not files:
        raise SystemExit(f"No config files found at: {args.input}")

    for config_file in files:
        print(f"Results for: {config_file.name}")
        parser = AristaConfigFileParser(config_file)
        config_data = parser.parse_arista_config()
        print(f"  parsed interfaces: {len(config_data['interfaces'])}")
        print(f"  parsed lags: {len(config_data['lags'])}")
        print(f"  parsed vlans: {len(config_data['vlans'])}")
        print(f"  parsed network_instances: {len(config_data['network_instances'])}")
        print(f"  parsed evpns: {len(config_data['evpns'])}")

        folder_name = config_file.name.removesuffix(".config.txt")
        output_dir = output_path / folder_name
        output_dir.mkdir(parents=True, exist_ok=True)

        for key, values in config_data.items():
            output_file = output_dir / f"{key}.json"
            with output_file.open("w", encoding="utf-8") as handle:
                data = [entry.model_dump() for entry in values]
                json.dump(data, handle, indent=4)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
