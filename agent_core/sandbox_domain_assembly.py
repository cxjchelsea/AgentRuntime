"""GA-02 D3: minimal immutable *sandbox* binding of verified package bytes.

Not a production DomainBinding, trusted C1 catalog, executable adapter or grant.
The Application supplies an already verified D2-A package snapshot; this module
only pins and checks inert asset bytes for a test-only domain composition.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from agent_core.domain_descriptor import (
    AssetReferenceV1,
    PackageDescriptorError,
    descriptor_to_domain_manifest,
    parse_package_descriptor,
)
from agent_core.domain_package_loader import (
    VerifiedAssetV1,
    VerifiedPackageSnapshotV1,
)
from agent_core.iteration import AgentRunBinding
from runtime.contracts import RuntimeInput

ROLE = "SANDBOX_NON_AUTHORITATIVE_DOMAIN_BINDING"


class SandboxAssemblyError(ValueError):
    """A package cannot be used even for a sandbox binding."""


@dataclass(frozen=True, slots=True)
class SandboxBoundAsset:
    kind: str
    namespace: str
    id: str
    version: str
    sha256: str
    content_bytes: bytes


@dataclass(frozen=True, slots=True)
class SandboxDomainBinding:
    domain_id: str
    domain_version: str
    generation_id: str
    manifest_digest: str
    binding_fingerprint: str
    assets: tuple[SandboxBoundAsset, ...]
    action_ids: tuple[str, ...]
    role: str = ROLE

    def for_run(self, initial: RuntimeInput, *, run_id: str) -> AgentRunBinding:
        """Pin run provenance; grants no execution or Host authority."""
        if type(initial) is not RuntimeInput or not self.action_ids:
            raise SandboxAssemblyError("invalid sandbox run input or empty actions")
        return AgentRunBinding.from_input(
            initial,
            run_id=run_id,
            domain_id=self.domain_id,
            domain_version=self.domain_version,
            binding_fingerprint=self.binding_fingerprint,
        )


def assemble_sandbox_domain(snapshot: VerifiedPackageSnapshotV1) -> SandboxDomainBinding:
    """Pin a D2-A snapshot into a non-runnable, version-exact asset projection.

    D2-A must independently check the local package source before this call.
    A forged Python snapshot is NOT a trust credential; re-check local byte
    consistency to fail closed, not to claim authenticity of its issuer.
    """
    if type(snapshot) is not VerifiedPackageSnapshotV1:
        raise SandboxAssemblyError("expected D2-A snapshot")
    descriptor = snapshot.descriptor
    try:
        descriptor_to_domain_manifest(descriptor)
        if parse_package_descriptor(snapshot.descriptor_bytes) != descriptor:
            raise SandboxAssemblyError("descriptor wire does not match snapshot")
    except (PackageDescriptorError, TypeError, ValueError) as exc:
        raise SandboxAssemblyError("invalid package descriptor") from exc
    if (
        not descriptor.enabled
        or type(snapshot.descriptor_bytes) is not bytes
        or type(snapshot.assets) is not tuple
        or type(snapshot.generation_id) is not str
        or not snapshot.generation_id
        or snapshot.expected_manifest_digest != descriptor.manifest_digest
    ):
        raise SandboxAssemblyError("invalid package snapshot metadata")
    if len(snapshot.assets) != len(descriptor.asset_refs):
        raise SandboxAssemblyError("incomplete package assets")
    if (
        any(type(a) is not VerifiedAssetV1 for a in snapshot.assets)
        or tuple(a.ref for a in snapshot.assets) != descriptor.asset_refs
    ):
        raise SandboxAssemblyError("asset order or reference mismatch")

    projected: list[SandboxBoundAsset] = []
    for asset in snapshot.assets:
        if type(asset) is not VerifiedAssetV1 or type(asset.ref) is not AssetReferenceV1:
            raise SandboxAssemblyError("invalid asset structure")
        ref = asset.ref
        content = asset.content_bytes
        if type(content) is not bytes or hashlib.sha256(content).hexdigest() != ref.sha256:
            raise SandboxAssemblyError("asset digest mismatch")
        projected.append(
            SandboxBoundAsset(
                ref.kind, ref.namespace, ref.id, ref.version, ref.sha256, bytes(content)
            )
        )

    actions = tuple(asset.id for asset in projected if asset.kind == "action")
    if not actions or len(actions) != len(set(actions)):
        raise SandboxAssemblyError("sandbox requires unique action identifiers")

    # Include exact asset keys and generation; no mutable Registry or live path.
    identity = {
        "domain_id": descriptor.domain_id,
        "domain_version": descriptor.domain_version,
        "generation_id": snapshot.generation_id,
        "manifest_digest": descriptor.manifest_digest,
        "assets": [
            {
                "kind": a.kind,
                "namespace": a.namespace,
                "id": a.id,
                "version": a.version,
                "sha256": a.sha256,
            }
            for a in projected
        ],
    }
    payload = json.dumps(
        identity, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    fingerprint = hashlib.sha256(b"GA02-D3-SANDBOX-BINDING-1\0" + payload).hexdigest()
    return SandboxDomainBinding(
        descriptor.domain_id,
        descriptor.domain_version,
        snapshot.generation_id,
        descriptor.manifest_digest,
        fingerprint,
        tuple(projected),
        actions,
    )
