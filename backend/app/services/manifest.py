"""Validates and resolves an AgentVersion manifest against docs/agent-manifest.md.

"Resolving" means: every skills[] and mcp.tools[] reference must point at a
real, already-registered row before the manifest is accepted - "the
platform never stores a manifest it can't fully resolve" (agent-manifest.md).
This module does the resolving; app/services/agents.py does the writing.

Known, documented gap (see docs/roadmap.md's Phase 2 notes and
docs/phase-notes/phase-2.md): agent-manifest.md says `evaluation.policy`
"must resolve to an existing EvaluationPolicy" - that registry is Phase 3
scope and doesn't exist yet, so this module only checks the key is present
with a non-empty string value, not that it resolves to anything real. This
relaxation is temporary and named, not silent.
"""
import hashlib
import json
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent, AgentVersion
from app.models.mcp import MCPServer, MCPTool
from app.models.skill import Skill, SkillVersion
from app.services.errors import ConflictError, ValidationError

_REQUIRED_TOP_LEVEL_KEYS = ("agent", "model", "skills", "mcp", "evaluation")


@dataclass(frozen=True)
class ResolvedManifest:
    version_label: str
    content_hash: str
    source_ref: str | None
    skill_version_ids: list[uuid.UUID]


def _content_hash(manifest: dict) -> str:
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


async def resolve_manifest(db: AsyncSession, agent: Agent, manifest: dict) -> ResolvedManifest:
    missing = [k for k in _REQUIRED_TOP_LEVEL_KEYS if k not in manifest]
    if missing:
        raise ValidationError(f"manifest is missing required key(s): {', '.join(missing)}")

    agent_section = manifest["agent"]
    version_label = agent_section.get("version")
    if not version_label or not isinstance(version_label, str):
        raise ValidationError("manifest.agent.version is required and must be a non-empty string")

    manifest_agent_name = agent_section.get("name")
    if manifest_agent_name and manifest_agent_name != agent.name:
        raise ValidationError(
            f"manifest.agent.name ({manifest_agent_name!r}) does not match the target agent ({agent.name!r})"
        )

    framework = agent_section.get("framework")
    if not framework or not isinstance(framework, str):
        raise ValidationError("manifest.agent.framework is required and must be a non-empty string")

    if not isinstance(manifest.get("model"), dict) or not manifest["model"].get("provider") or not manifest["model"].get("name"):
        raise ValidationError("manifest.model.provider and manifest.model.name are required")

    evaluation = manifest.get("evaluation")
    if not isinstance(evaluation, dict) or not evaluation.get("policy"):
        raise ValidationError("manifest.evaluation.policy is required (not yet validated against a registry - Phase 3)")

    existing = (
        await db.execute(
            select(AgentVersion.id).where(
                AgentVersion.agent_id == agent.id, AgentVersion.version_label == version_label
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ConflictError(f"agent {agent.name!r} already has a version labeled {version_label!r}")

    skill_version_ids = await _resolve_skills(db, manifest.get("skills", []), framework)
    await _resolve_mcp_tools(db, manifest.get("mcp", {}))

    source_ref = None
    source = manifest.get("source")
    if isinstance(source, dict):
        source_ref = source.get("git_ref")

    return ResolvedManifest(
        version_label=version_label,
        content_hash=_content_hash(manifest),
        source_ref=source_ref,
        skill_version_ids=skill_version_ids,
    )


async def _resolve_skills(db: AsyncSession, skill_refs: list, framework: str) -> list[uuid.UUID]:
    if not isinstance(skill_refs, list):
        raise ValidationError("manifest.skills must be a list")

    resolved: list[uuid.UUID] = []
    for ref in skill_refs:
        if not isinstance(ref, str) or "@" not in ref:
            raise ValidationError(f"invalid skill reference {ref!r}; expected 'name@version'")
        name, version = ref.rsplit("@", 1)

        skill = (await db.execute(select(Skill).where(Skill.name == name))).scalar_one_or_none()
        if skill is None:
            raise ValidationError(f"manifest references unknown skill {name!r}")

        skill_version = (
            await db.execute(
                select(SkillVersion).where(SkillVersion.skill_id == skill.id, SkillVersion.version == version)
            )
        ).scalar_one_or_none()
        if skill_version is None:
            raise ValidationError(f"manifest references unknown skill version {ref!r}")

        if skill_version.compatible_frameworks and framework not in skill_version.compatible_frameworks:
            raise ValidationError(
                f"skill version {ref!r} is not compatible with framework {framework!r} "
                f"(compatible: {skill_version.compatible_frameworks})"
            )

        resolved.append(skill_version.id)
    return resolved


async def _resolve_mcp_tools(db: AsyncSession, mcp_section: dict) -> None:
    """Declared intent only (docs/agent-manifest.md) - this checks every
    named tool actually exists on a declared server. It does NOT create
    AgentCapabilityGrants; granting is always a separate, explicit action
    (app/services/capability_grants.py), regardless of what a manifest
    declares. See docs/mcp-governance.md.
    """
    if not mcp_section:
        return
    server_names = mcp_section.get("servers", [])
    tool_names = mcp_section.get("tools", [])
    if not isinstance(server_names, list) or not isinstance(tool_names, list):
        raise ValidationError("manifest.mcp.servers and manifest.mcp.tools must be lists")
    if tool_names and not server_names:
        raise ValidationError("manifest.mcp.tools is non-empty but manifest.mcp.servers is empty")

    servers = (await db.execute(select(MCPServer).where(MCPServer.name.in_(server_names)))).scalars().all()
    found_server_names = {s.name for s in servers}
    unknown_servers = set(server_names) - found_server_names
    if unknown_servers:
        raise ValidationError(f"manifest references unknown MCP server(s): {sorted(unknown_servers)}")

    server_ids = [s.id for s in servers]
    for tool_name in tool_names:
        tool = (
            await db.execute(
                select(MCPTool).where(MCPTool.name == tool_name, MCPTool.mcp_server_id.in_(server_ids))
            )
        ).scalar_one_or_none()
        if tool is None:
            raise ValidationError(
                f"manifest references unknown MCP tool {tool_name!r} on declared server(s) {server_names}"
            )
