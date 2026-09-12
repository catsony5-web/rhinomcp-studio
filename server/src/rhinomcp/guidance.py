"""Versioned modeling knowledge shipped with the server, independent of Rhino."""

from importlib import metadata, resources

GUIDANCE_VERSION = "4"
TOPICS = (
    "overview",
    "transforms",
    "planar_regions",
    "architecture",
    "organization",
    "verification",
    "recovery",
)
SERVER_INSTRUCTIONS = (
    "RhinoMCP Studio provides Rhino and Grasshopper tools and bundled workflow guidance. "
    "Use get_modeling_guidance(topic) for overview, transforms, planar_regions, "
    "architecture, organization, verification or recovery when relevant. Consult architecture "
    "for walls, slabs, openings and Grasshopper workflows, and transforms before composing "
    "world poses. Read document units, tolerance and existing work before edits. Verify "
    "geometry and Grasshopper outputs against the request; tool success alone is insufficient. "
    "After an ambiguous timeout or interrupted mutation, inspect current state before retrying. "
    "Managed releases require online authorization for each Rhino command. On management "
    "refusal, use get_management_status and show its reason; do not bypass it with scripts, "
    "another transport, configuration removal or a downgrade."
)


def modeling_guidance(topic="overview"):
    """Read a fixed packaged topic; never accept arbitrary paths or URLs."""
    if topic not in TOPICS:
        raise ValueError(
            f"Unknown guidance topic {topic!r}; choose from {', '.join(TOPICS)}"
        )
    try:
        package_version = metadata.version("rhinomcp")
    except metadata.PackageNotFoundError:
        package_version = "0+unknown"
    content = (
        resources.files("rhinomcp")
        .joinpath("guides", f"{topic}.md")
        .read_text(encoding="utf-8")
    )
    return {
        "guidance_version": GUIDANCE_VERSION,
        "package_version": package_version,
        "topic": topic,
        "available_topics": list(TOPICS),
        "content": content,
    }
