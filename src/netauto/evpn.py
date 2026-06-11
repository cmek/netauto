import logging
from typing import List, Optional

from .models import (
    Asn,
    AzureEvpn,
    CircuitDiff,
    EnsureResult,
    Evpn,
    EvpnCircuit,
    Interface,
    ReconcilePlan,
    RoutingInstance,
)
from .drivers import DeviceDriver
from .exceptions import InterfaceNotFound, NetAutoException, VniInUse
from .logic import _as_interface_map
from .parsers import AristaConfigParser, OcnosConfigXMLParser

logger = logging.getLogger(__name__)


class EvpnManager:
    """Building blocks for single-device EVPN circuit create/delete.

    Mirrors :class:`~netauto.logic.LagManager`: it configures **one endpoint
    interface on one device** per call (read device state, validate, render,
    push). Stitching the two ends of a circuit together across devices is the
    orchestrator's job (Prefect) — this library only provides the per-device
    primitive.

    Scope: global transport (EVPN/VXLAN) ``cloud_vc`` / ``p2p_vc`` circuits and
    Azure Q-in-Q (``create_azure_circuit``). Local switching is not implemented.
    The VNI is allocated by an external process and passed in whole on the model;
    it is used verbatim (never derived from the VLAN). ``get_circuits`` /
    ``verify_circuit`` read configured state back into the models for inspection.
    """

    def __init__(self, driver: DeviceDriver):
        self.driver = driver

    def _normalise(self, rendered) -> List[str]:
        """Renderers return a CLI line list (Arista) or one XML string (OcNOS)."""
        return rendered if isinstance(rendered, list) else [rendered]

    def _require_interface(self, interface_name: str) -> Interface:
        """Confirm the endpoint exists. Routed (L3) ports show up in the
        interface inventory but not in get_switchports(), so check both."""
        inventory = _as_interface_map(self.driver.get_interfaces())
        switchports = _as_interface_map(self.driver.get_switchports())
        interface = inventory.get(interface_name) or switchports.get(interface_name)
        if interface is None:
            raise InterfaceNotFound(
                f"Interface {interface_name} does not exist on device."
            )
        return interface

    def _require_vni_free(self, vni: int) -> None:
        """The VNI must not already be mapped on this device.

        VNIs are allocated by an external process; this is a safety check that
        the value handed to us isn't already in use on the device.
        """
        # get_vnis() is a dict (Arista: vni -> {vlan_id}) or a list (OcNOS).
        existing = self.driver.get_vnis()
        if vni in existing:
            detail = ""
            if isinstance(existing, dict):
                mapped = existing[vni] or {}
                detail = f" (mapped to VLAN {mapped.get('vlan_id', 'unknown')})"
            raise VniInUse(f"VNI {vni} is already in use{detail}")

    def create_circuit(
        self,
        interface_name: str,
        evpn: Evpn,
        routing_instance: Optional[RoutingInstance] = None,
        asn: Optional[Asn] = None,
        create_vrf: bool = True,
        dry_run: bool = False,
    ) -> str:
        """Provision one EVPN circuit endpoint on ``interface_name``.

        Optionally creates the mac-vrf / vlan-aware-bundle first
        (``create_vrf``); pass ``create_vrf=False`` when the service VRF already
        exists on the device. Returns the combined config diff (or the intended
        change for ``dry_run``).

        The VRF and the circuit are pushed as two separate device transactions,
        VRF first: on OcNOS the mac-vrf must exist before the circuit references
        it, and on Arista a fresh config session avoids CLI sub-mode leaking
        between the two blocks (a bare ``vlan <id>`` after a ``vlan-aware-bundle``
        block is otherwise swallowed as a bundle member).
        """
        self._require_interface(interface_name)
        self._require_vni_free(evpn.vni)

        interface = Interface(name=interface_name)
        diffs: List[str] = []

        if create_vrf:
            if routing_instance is None:
                raise NetAutoException(
                    "routing_instance is required when create_vrf=True"
                )
            # The vlan-aware-bundle / mac-vrf is named by the service key on both
            # the VRF push and the EVPN push; they must reference the same bundle.
            if routing_instance.instance_name != evpn.description:
                raise NetAutoException(
                    "routing_instance.instance_name "
                    f"({routing_instance.instance_name!r}) must match "
                    f"evpn.description ({evpn.description!r}) so the VRF and the "
                    "EVPN circuit reference the same service instance."
                )
            diffs.append(
                self.driver.push_config(
                    self._normalise(
                        self.driver.renderer.render_routing_instance(
                            asn or Asn(asn=evpn.asn), routing_instance
                        )
                    ),
                    dry_run=dry_run,
                )
            )

        logger.info(
            "creating %s EVPN circuit on %s (vni %s)",
            evpn.service_type,
            interface_name,
            evpn.vni,
        )
        diffs.append(
            self.driver.push_config(
                self._normalise(self.driver.renderer.render_evpn(interface, evpn)),
                dry_run=dry_run,
            )
        )
        return "\n".join(d for d in diffs if d)

    def delete_circuit(
        self,
        interface_name: str,
        evpn: Evpn,
        routing_instance: Optional[RoutingInstance] = None,
        asn: Optional[Asn] = None,
        delete_vrf: bool = False,
        dry_run: bool = False,
    ) -> str:
        """Tear down one EVPN circuit endpoint on ``interface_name``.

        Removes the circuit (sub-interface / access binding / VXLAN mapping).
        Pass ``delete_vrf=True`` (with ``routing_instance``) to also remove the
        service mac-vrf — only safe once no other endpoint uses it.

        Pushed as two separate transactions (circuit first, then the VRF), for
        the same per-platform reasons as ``create_circuit``.
        """
        interface = Interface(name=interface_name)

        logger.info(
            "deleting %s EVPN circuit on %s (vni %s)",
            evpn.service_type,
            interface_name,
            evpn.vni,
        )
        diffs: List[str] = [
            self.driver.push_config(
                self._normalise(
                    self.driver.renderer.render_evpn_delete(interface, evpn)
                ),
                dry_run=dry_run,
            )
        ]

        if delete_vrf:
            if routing_instance is None:
                raise NetAutoException(
                    "routing_instance is required when delete_vrf=True"
                )
            diffs.append(
                self.driver.push_config(
                    self._normalise(
                        self.driver.renderer.render_routing_instance_delete(
                            asn or Asn(asn=evpn.asn), routing_instance
                        )
                    ),
                    dry_run=dry_run,
                )
            )

        return "\n".join(d for d in diffs if d)

    def create_azure_circuit(
        self,
        interface_name: str,
        azure: AzureEvpn,
        routing_instance: Optional[RoutingInstance] = None,
        asn: Optional[Asn] = None,
        create_vrf: bool = True,
        dry_run: bool = False,
    ) -> str:
        """Provision one Azure Q-in-Q EVPN circuit endpoint on ``interface_name``.

        Same per-device contract and two-transaction (VRF then circuit) flow as
        :meth:`create_circuit`. Configure the customer side (``role="customer"``,
        1-3 ``c_tags``) and each CNI side (``role="cni"``) with separate calls;
        the orchestrator drives the mandatory dual CNI (one call + VNI per CNI).
        """
        self._require_interface(interface_name)
        self._require_vni_free(azure.vni)

        interface = Interface(name=interface_name)
        diffs: List[str] = []

        if create_vrf:
            if routing_instance is None:
                raise NetAutoException(
                    "routing_instance is required when create_vrf=True"
                )
            if routing_instance.instance_name != azure.description:
                raise NetAutoException(
                    "routing_instance.instance_name "
                    f"({routing_instance.instance_name!r}) must match "
                    f"azure.description ({azure.description!r})."
                )
            diffs.append(
                self.driver.push_config(
                    self._normalise(
                        self.driver.renderer.render_routing_instance(
                            asn or Asn(asn=azure.asn), routing_instance
                        )
                    ),
                    dry_run=dry_run,
                )
            )

        logger.info(
            "creating Azure %s EVPN circuit on %s (vni %s, s_tag %s, c_tags %s)",
            azure.role,
            interface_name,
            azure.vni,
            azure.s_tag,
            azure.c_tags,
        )
        diffs.append(
            self.driver.push_config(
                self._normalise(
                    self.driver.renderer.render_azure_evpn(interface, azure)
                ),
                dry_run=dry_run,
            )
        )
        return "\n".join(d for d in diffs if d)

    def delete_azure_circuit(
        self,
        interface_name: str,
        azure: AzureEvpn,
        routing_instance: Optional[RoutingInstance] = None,
        asn: Optional[Asn] = None,
        delete_vrf: bool = False,
        dry_run: bool = False,
    ) -> str:
        """Tear down one Azure Q-in-Q EVPN circuit endpoint."""
        interface = Interface(name=interface_name)

        logger.info(
            "deleting Azure %s EVPN circuit on %s (vni %s)",
            azure.role,
            interface_name,
            azure.vni,
        )
        diffs: List[str] = [
            self.driver.push_config(
                self._normalise(
                    self.driver.renderer.render_azure_evpn_delete(interface, azure)
                ),
                dry_run=dry_run,
            )
        ]

        if delete_vrf:
            if routing_instance is None:
                raise NetAutoException(
                    "routing_instance is required when delete_vrf=True"
                )
            diffs.append(
                self.driver.push_config(
                    self._normalise(
                        self.driver.renderer.render_routing_instance_delete(
                            asn or Asn(asn=azure.asn), routing_instance
                        )
                    ),
                    dry_run=dry_run,
                )
            )

        return "\n".join(d for d in diffs if d)

    # ----------------------------------------------------------------- #
    # Inspection / read-back (configured state)
    # ----------------------------------------------------------------- #
    def get_circuits(self) -> List[EvpnCircuit]:
        """Read the EVPN circuits configured on this device back into models.

        Reconstructs each circuit (plain ``Evpn`` or Azure ``AzureEvpn``) with
        its access interface and ``RoutingInstance`` from ``driver.get_config()``
        (running-config for Arista, NETCONF get-config XML for OcNOS). Configured
        state only — see the docs for the (deferred) operational-health layer.
        """
        config = self.driver.get_config()
        if not config or not str(config).strip():
            return []  # no config => no circuits
        if self.driver.platform == "arista_eos":
            return AristaConfigParser(config).parse_evpn_circuits()
        if self.driver.platform == "ipinfusion_ocnos":
            return OcnosConfigXMLParser(config).parse_evpn_circuits()
        raise NetAutoException(
            f"get_circuits not supported for platform {self.driver.platform}"
        )

    def verify_circuit(
        self,
        interface_name: str,
        evpn: Evpn | AzureEvpn,
        routing_instance: Optional[RoutingInstance] = None,
    ) -> CircuitDiff:
        """Compare an intended circuit against what is live on the device.

        Reads the device back (:meth:`get_circuits`), finds the circuit with the
        intended VNI, and reports field-level differences — the core debugging
        primitive for "did my push land / has config drifted". More trustworthy
        than the push diff (OcNOS dry-run over-reports removals).
        """
        candidates = [c for c in self.get_circuits() if c.evpn.vni == evpn.vni]
        if not candidates:
            return CircuitDiff(
                present=False,
                matches=False,
                differences=[f"no circuit found with vni {evpn.vni}"],
            )
        # Prefer one on the intended interface when the binding is known.
        circuit = next(
            (c for c in candidates if c.interface == interface_name), candidates[0]
        )
        differences = self._diff_circuit(interface_name, evpn, routing_instance, circuit)
        return CircuitDiff(
            present=True, matches=not differences, differences=differences
        )

    # ----------------------------------------------------------------- #
    # Declarative ensure (idempotent: read -> diff -> converge)
    # ----------------------------------------------------------------- #
    def ensure_circuit(
        self,
        interface_name: str,
        evpn: Evpn,
        routing_instance: Optional[RoutingInstance] = None,
        dry_run: bool = False,
    ) -> EnsureResult:
        """Idempotently converge the device to the intended circuit.

        Reads the device back: **absent** -> create; **drifted** -> re-apply
        (overwrite); **already correct** -> no-op. Safe to re-run; a partial
        failure self-heals on the next call. Returns what action was taken.
        """
        return self._ensure(
            interface_name, evpn, routing_instance, dry_run,
            lambda: self.create_circuit(
                interface_name, evpn, routing_instance=routing_instance,
                create_vrf=routing_instance is not None, dry_run=dry_run,
            ),
        )

    def ensure_azure_circuit(
        self,
        interface_name: str,
        azure: AzureEvpn,
        routing_instance: Optional[RoutingInstance] = None,
        dry_run: bool = False,
    ) -> EnsureResult:
        """Idempotent ``ensure`` for an Azure Q-in-Q circuit (see ensure_circuit)."""
        return self._ensure(
            interface_name, azure, routing_instance, dry_run,
            lambda: self.create_azure_circuit(
                interface_name, azure, routing_instance=routing_instance,
                create_vrf=routing_instance is not None, dry_run=dry_run,
            ),
        )

    def _ensure(self, interface_name, intended, routing_instance, dry_run, apply):
        diff = self.verify_circuit(interface_name, intended, routing_instance)
        if not diff.present:
            return EnsureResult(action="created", config_diff=apply())
        if diff.matches:
            return EnsureResult(action="unchanged")
        # drifted -> re-apply to converge (create renders the full intended state)
        return EnsureResult(
            action="updated", differences=diff.differences, config_diff=apply()
        )

    @staticmethod
    def _diff_circuit(
        interface_name: str,
        intended: Evpn | AzureEvpn,
        routing_instance: Optional[RoutingInstance],
        actual: EvpnCircuit,
    ) -> List[str]:
        diffs: List[str] = []

        def cmp(label, want, got):
            if want != got:
                diffs.append(f"{label}: intended {want!r}, actual {got!r}")

        if actual.interface is not None:
            cmp("interface", interface_name, actual.interface)
        cmp("description", intended.description, actual.evpn.description)
        cmp("asn", intended.asn, actual.evpn.asn)

        if type(intended) is not type(actual.evpn):
            diffs.append(
                f"service type: intended {type(intended).__name__}, "
                f"actual {type(actual.evpn).__name__}"
            )
        elif isinstance(intended, AzureEvpn):
            a = actual.evpn
            cmp("role", intended.role, a.role)
            cmp("s_tag", intended.s_tag, a.s_tag)
            cmp("c_tags", sorted(intended.c_tags), sorted(a.c_tags))
            cmp("rewrite", intended.rewrite, a.rewrite)
            cmp("internal_s_tag", intended.internal_s_tag, a.internal_s_tag)
        else:
            cmp("vlan", intended.vlan.vlan_id, actual.evpn.vlan.vlan_id)

        if routing_instance is not None and actual.routing_instance is not None:
            cmp("rd", routing_instance.rd, actual.routing_instance.rd)
            cmp("rt", routing_instance.rt_rd, actual.routing_instance.rt_rd)

        return diffs


def plan_reconcile(
    intended: List[EvpnCircuit], actual: List[EvpnCircuit]
) -> ReconcilePlan:
    """Diff an intended circuit inventory against live read-back, keyed by VNI.

    Pure and report-only — the orchestrator decides whether to apply. The VNI is
    the fabric-wide service identifier, so it is the natural match key:
    ``to_create`` (intended, absent), ``to_update`` (present but drifted),
    ``to_delete`` (on device, not intended — orphans/extras), ``in_sync``.
    """
    intended_by_vni = {c.evpn.vni: c for c in intended}
    actual_by_vni = {c.evpn.vni: c for c in actual}

    plan = ReconcilePlan()
    for vni, want in intended_by_vni.items():
        have = actual_by_vni.get(vni)
        if have is None:
            plan.to_create.append(vni)
            continue
        diffs = EvpnManager._diff_circuit(
            want.interface or have.interface or "",
            want.evpn,
            want.routing_instance,
            have,
        )
        if diffs:
            plan.to_update[vni] = diffs
        else:
            plan.in_sync.append(vni)

    plan.to_delete = sorted(set(actual_by_vni) - set(intended_by_vni))
    plan.to_create.sort()
    plan.in_sync.sort()
    return plan
