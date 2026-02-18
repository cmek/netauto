from lxml.html.builder import P
from argparse import Namespace
import argparse
import json
import re
from pathlib import Path
from typing import Any, Pattern
from netauto.models import Evpn, Interface, Lag, RoutingInstance, Vlan


INTERFACE_RE = re.compile(r"^interface\s+(?P<name>\S+)$")
MAC_VRF_RE = re.compile(r"^mac\s+vrf\s+(?P<name>\S+)$")

class OcnsConfigFileParser:
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
        header: Pattern[str] = re.compile(r"^interface\s+(\S+)(?:\s+(switchport))?$", re.M)
        switch_port: Pattern[str] = re.compile(r"^\s*switchport\s*$", re.M)
        description: Pattern[str] = re.compile(r"^\s*description\s+(.+)$", re.M)
        shutdown: Pattern[str] = re.compile(r"^\s*shutdown\s*$", re.M)
        no_shutdown: Pattern[str] = re.compile(r"^\s*no shutdown\s*$", re.M)
        mtu: Pattern[str] = re.compile(r"^\s*mtu\s+(\d+)\s*$", re.M)
        channel_group: Pattern[str] = re.compile(r"^\s*channel-group\s+(\d+)\b", re.M)
        access_vlan: Pattern[str] = re.compile(r"^\s*switchport\s+access\s+vlan\s+(\d+)\s*$", re.M)

        interfaces: list[Interface] = []

        for intf in interface_entry:
            header_match = header.search(intf)
            if header_match is None:
                continue

            intf_name = header_match.group(1)
            has_switchport = bool(header_match.group(2)) or bool(switch_port.search(intf))

            description_match = description.search(intf)
            intf_description = description_match.group(1).strip() if description_match else None

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
            intf_access_vlan = int(access_vlan_match.group(1)) if access_vlan_match else None

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

    def parse_vlans(self, vlan_entry: list[str]) -> list[Vlan]:
        header: Pattern[str] = re.compile(r"^vlan\s+(\d+)$", re.M)
        name: Pattern[str] = re.compile(r"^\s*name\s+(.+)$", re.M)
        s_tag: Pattern[str] = re.compile(r"^\s*(?:s-tag|service-vlan)\s+(\d+)\s*$", re.M)

        vlans: list[Vlan] = []

        for vlan_block in vlan_entry:
            header_match = header.search(vlan_block)
            if header_match is None:
                continue

            vlan_id = int(header_match.group(1))

            name_match = name.search(vlan_block)
            vlan_name = name_match.group(1).strip() if name_match else None

            s_tag_match = s_tag.search(vlan_block)
            vlan_s_tag = int(s_tag_match.group(1)) if s_tag_match else None

            vlans.append(
                Vlan(
                    vlan_id=vlan_id,
                    name=vlan_name,
                    s_tag=vlan_s_tag,
                )
            )

        return vlans

    def parse_network_instances(self, network_instance_entry: list[str]) -> list[RoutingInstance]:
        header: Pattern[str] = re.compile(r"^mac\s+vrf\s+(\S+)$", re.M)
        rd: Pattern[str] = re.compile(r"^\s*rd\s+(\S+)\s*$", re.M)
        rt_both: Pattern[str] = re.compile(r"^\s*route-target\s+both\s+(\S+)\s*$", re.M)
        rt_import: Pattern[str] = re.compile(r"^\s*route-target\s+import\s+(\S+)\s*$", re.M)
        rt_export: Pattern[str] = re.compile(r"^\s*route-target\s+export\s+(\S+)\s*$", re.M)

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
        header: Pattern[str] = re.compile(r"^interface\s+(\S+)(?:\s+(switchport))?$", re.M)
        description: Pattern[str] = re.compile(r"^\s*description\s+(.+)$", re.M)
        shutdown: Pattern[str] = re.compile(r"^\s*shutdown\s*$", re.M)
        no_shutdown: Pattern[str] = re.compile(r"^\s*no shutdown\s*$", re.M)
        mtu: Pattern[str] = re.compile(r"^\s*mtu\s+(\d+)\s*$", re.M)
        switch_port: Pattern[str] = re.compile(r"^\s*switchport\s*$", re.M)
        access_vlan: Pattern[str] = re.compile(r"^\s*switchport\s+access\s+vlan\s+(\d+)\s*$", re.M)
        trunk_allowed: Pattern[str] = re.compile(r"^\s*switchport\s+trunk\s+allowed\s+vlan(?:\s+add)?\s+(.+)$", re.M)
        channel_group: Pattern[str] = re.compile(
            r"^\s*channel-group\s+(\d+)(?:\s+mode\s+(active|passive|on))?\b", re.M
        )
        min_links: Pattern[str] = re.compile(r"^\s*lacp\s+min-links\s+(\d+)\s*$", re.M)

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

            has_switchport = bool(header_match.group(2)) or bool(switch_port.search(intf))
            description_match = description.search(intf)
            lag_description = description_match.group(1).strip() if description_match else None

            is_enabled = True
            if shutdown.search(intf):
                is_enabled = False
            if no_shutdown.search(intf):
                is_enabled = True

            mtu_match = mtu.search(intf)
            lag_mtu = int(mtu_match.group(1)) if mtu_match else None

            access_vlan_match = access_vlan.search(intf)
            lag_access_vlan = int(access_vlan_match.group(1)) if access_vlan_match else None

            trunk_vlans: list[Vlan] = []
            trunk_allowed_match = trunk_allowed.search(intf)
            if trunk_allowed_match:
                for vlan_id in self._parse_vlan_list(trunk_allowed_match.group(1)):
                    trunk_vlans.append(Vlan(vlan_id=vlan_id))

            mode = "routed"
            if has_switchport:
                mode = "trunk" if trunk_vlans else "access"

            min_links_match = min_links.search(intf)
            lag_min_links = int(min_links_match.group(1)) if min_links_match else 1

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
                    lacp_mode=lacp_by_lag.get(lag_name, "active"),
                    min_links=lag_min_links,
                )
            )

        return lags

    def parse_evpns(
        self, interface_entry: list[str], network_instances: list[RoutingInstance]
    ) -> list[Evpn]:
        header: Pattern[str] = re.compile(r"^interface\s+(\S+)(?:\s+(switchport))?$", re.M)
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
                    vlan=Vlan(vlan_id=vlan_id, name=service_name),
                    description=service_name,
                    asn=asn,
                    vni=vni,
                )
            )

        return evpns

    def parse_ocnos_config(self) -> dict[str, Any]:
        config_parts = [entry.strip("\n") for entry in re.split(r"^!", self.config, flags=re.M)]

        interface_data = [
            entry for entry in config_parts if entry.startswith("interface ")
        ]
        vlan_data = [
            entry for entry in config_parts if entry.startswith("vlan ")
        ]
        network_instance_data = [
            entry for entry in config_parts if entry.startswith("mac vrf ")
        ]

        interfaces: list[Interface] = self.parse_interfaces(interface_data)
        lags: list[Lag] = self.parse_lags(interface_data)
        vlans: list[Vlan] = self.parse_vlans(vlan_data)
        network_instances: list[RoutingInstance] = self.parse_network_instances(network_instance_data)
        evpns: list[Evpn] = self.parse_evpns(interface_data, network_instances)

        return {
            "interfaces": interfaces,
            "lags": lags,
            "vlans": vlans,
            "network_instances": network_instances, 
            "evpns": evpns,
        }

def main() -> int:
    parser = argparse.ArgumentParser(description="parser for OcNOS config text files")
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("./configs/ocns/"),
        help="Path to a config file or directory of *.config.txt files",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("models/ocns/"),
        help="Optional path to write JSON output",
    )
    args: Namespace = parser.parse_args()
    
    input_path: Path = args.input
    output_path: Path = args.output
    print(output_path.absolute())
    files = input_path.glob("*.config.txt")
    if not files:
        raise SystemExit(f"No config files found at: {args.input}")

    # parsed_payload = []
    for config_file in files:
        print(f"Results for: {config_file.name}")
        parser = OcnsConfigFileParser(config_file)
        config_data = parser.parse_ocnos_config()
        print(f"  parsed interfaces: {len(config_data['interfaces'])}")
        print(f"  parsed lags: {len(config_data['lags'])}")
        print(f"  parsed vlans: {len(config_data['vlans'])}")
        print(f"  parsed network_instances: {len(config_data['network_instances'])}")
        print(f"  parsed evpns: {len(config_data['evpns'])}")

        folder_name = config_file.name.removesuffix(".config.txt")
        output_dir = output_path / folder_name
        output_dir.mkdir(parents=True, exist_ok=True)

        for k, v in config_data.items():
            output_file = output_dir / f"{k}.json"
            with output_file.open("w") as f:
                data = [ entry.model_dump() for entry in v]
                json.dump(data, f, indent=4)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
