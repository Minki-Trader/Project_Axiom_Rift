from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path

REPO_ROOT_FOR_IMPORTS = Path(__file__).resolve().parents[4]
if str(REPO_ROOT_FOR_IMPORTS) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT_FOR_IMPORTS))

from foundation.control_plane.ledger import io_path, path_exists


UTF8_BOM = b"\xef\xbb\xbf"
HANGUL_RE = re.compile(r"[\uac00-\ud7a3]")
SUSPICIOUS_CJK_RE = re.compile(r"[\u4e00-\u9fff\uf900-\ufaff]")
MOJIBAKE_RE = re.compile(
    r"(?:[\uf900-\ufaff]|[\u0080-\u009f]|"
    r"\?(?:ㅽ|묒|섎|댁|⑦|꾩|먯|ㅼ|ㅺ|ㅻ|꾨|곗|뚯|몃|쒖|좏|섏|뺤|대|고|먮|붽|쇱|곹)|"
    r"\u91ce|\u4e80|\u904a|\u907a)"
)
REQUIRED_PATHS = [
    "AGENTS.md",
    "docs/policies/architecture_invariants.md",
    "docs/policies/exploration_mandate.md",
    "docs/policies/kpi_measurement_standard.md",
    "docs/policies/run_result_management.md",
    "docs/policies/result_judgment_policy.md",
    "docs/policies/branch_policy.md",
    "docs/registers/architecture_debt_register.md",
    "docs/registers/run_registry.csv",
    "docs/registers/idea_registry.md",
    "docs/registers/negative_result_register.md",
    "docs/registers/legacy_lesson_register.md",
    "docs/templates/run_manifest_template.json",
    "docs/templates/kpi_record_template.json",
    "docs/templates/result_summary_template.md",
    "docs/policies/agent_trigger_policy.md",
    "docs/policies/reentry_order.md",
    "docs/agent_control/codex_task_force_registry.yaml",
    ".agents/skills",
    ".codex/config.toml",
    ".codex/agents",
]
REQUIRED_AGENT_INTERFACE_KEYS = ("display_name", "short_description", "default_prompt")
OPENAI_YAML_TOP_LEVEL_SECTIONS = {"interface", "policy"}


def has_utf8_bom(data: bytes) -> bool:
    return data.startswith(UTF8_BOM)


def leading_utf8_bom_count(data: bytes) -> int:
    count = 0
    offset = 0
    while data.startswith(UTF8_BOM, offset):
        count += 1
        offset += len(UTF8_BOM)
    return count


def has_mixed_line_endings(data: bytes) -> bool:
    crlf_count = data.count(b"\r\n")
    without_crlf = data.replace(b"\r\n", b"")
    lf_count = without_crlf.count(b"\n")
    cr_count = without_crlf.count(b"\r")
    return sum(1 for count in (crlf_count, lf_count, cr_count) if count) > 1


def safe_read_text(path: Path, encoding: str) -> str:
    return io_path(path).read_text(encoding=encoding)


def iter_text_docs(repo_root: Path) -> list[Path]:
    roots = [
        repo_root / "AGENTS.md",
        repo_root / "docs",
        repo_root / ".agents",
        repo_root / "stages",
        repo_root / "foundation",
    ]
    paths: list[Path] = []
    for root in roots:
        if root.is_file():
            paths.append(root)
        elif root.exists():
            paths.extend(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in {".md", ".txt"})
    return sorted(set(paths))


def check_required_paths(repo_root: Path) -> list[str]:
    errors: list[str] = []
    for rel in REQUIRED_PATHS:
        if not path_exists(repo_root / rel):
            errors.append(f"missing required path: {rel}")
    return errors


def check_docs(repo_root: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    for path in iter_text_docs(repo_root):
        path_errors, path_warnings = check_doc_file(repo_root, path)
        errors.extend(path_errors)
        warnings.extend(path_warnings)
    return errors, warnings


def check_doc_file(repo_root: Path, path: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    rel = path.relative_to(repo_root).as_posix()
    data = io_path(path).read_bytes()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        errors.append(f"{rel}: not valid UTF-8: {exc}")
        return errors, warnings

    bom_count = leading_utf8_bom_count(data)
    if bom_count > 1:
        errors.append(f"{rel}: contains repeated UTF-8 BOM markers")
    if has_mixed_line_endings(data):
        warnings.append(f"{rel}: contains mixed line endings")
    has_hangul = bool(HANGUL_RE.search(text))
    if has_hangul and not has_utf8_bom(data):
        errors.append(f"{rel}: Korean text requires UTF-8 with BOM")
    if "\ufffd" in text:
        errors.append(f"{rel}: contains Unicode replacement character")
    if MOJIBAKE_RE.search(text):
        errors.append(f"{rel}: contains likely mojibake")
    if SUSPICIOUS_CJK_RE.search(text) and not has_hangul:
        warnings.append(f"{rel}: contains CJK text without Hangul; inspect if unexpected")
    return errors, warnings


def check_encoding_scope(repo_root: Path, scope_paths: list[str]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    for scope_path in scope_paths:
        path = (repo_root / scope_path).resolve()
        try:
            path.relative_to(repo_root)
        except ValueError:
            errors.append(f"{scope_path}: encoding scope must stay inside repo root")
            continue
        if not path_exists(path):
            errors.append(f"{scope_path}: encoding scope path does not exist")
            continue
        safe_path = io_path(path)
        candidates = [path] if safe_path.is_file() else sorted(
            p for p in safe_path.rglob("*") if p.is_file() and p.suffix.lower() in {".md", ".txt"}
        )
        for candidate in candidates:
            if candidate.suffix.lower() not in {".md", ".txt"}:
                continue
            durable_candidate = Path(str(candidate).removeprefix("\\\\?\\"))
            path_errors, path_warnings = check_doc_file(repo_root, durable_candidate)
            errors.extend(path_errors)
            warnings.extend(path_warnings)
    return errors, warnings


def check_policy_links(repo_root: Path) -> list[str]:
    errors: list[str] = []
    trigger_policy = safe_read_text(repo_root / "docs/policies/agent_trigger_policy.md", encoding="utf-8-sig")
    reentry = safe_read_text(repo_root / "docs/policies/reentry_order.md", encoding="utf-8-sig")
    agents = safe_read_text(repo_root / "AGENTS.md", encoding="utf-8-sig")
    debt = safe_read_text(repo_root / "docs/registers/architecture_debt_register.md", encoding="utf-8-sig")
    exploration = safe_read_text(repo_root / "docs/policies/exploration_mandate.md", encoding="utf-8-sig")
    kpi = safe_read_text(repo_root / "docs/policies/kpi_measurement_standard.md", encoding="utf-8-sig")
    run_management = safe_read_text(repo_root / "docs/policies/run_result_management.md", encoding="utf-8-sig")
    judgment = safe_read_text(repo_root / "docs/policies/result_judgment_policy.md", encoding="utf-8-sig")
    promotion = safe_read_text(repo_root / "docs/policies/promotion_policy.md", encoding="utf-8-sig")

    required_pairs = [
        ("agent_trigger_policy.md", trigger_policy, "architecture_invariants.md"),
        ("agent_trigger_policy.md", trigger_policy, "exploration_mandate.md"),
        ("agent_trigger_policy.md", trigger_policy, "kpi_measurement_standard.md"),
        ("agent_trigger_policy.md", trigger_policy, "run_result_management.md"),
        ("agent_trigger_policy.md", trigger_policy, "result_judgment_policy.md"),
        ("reentry_order.md", reentry, "architecture_invariants.md"),
        ("reentry_order.md", reentry, "exploration_mandate.md"),
        ("reentry_order.md", reentry, "kpi_measurement_standard.md"),
        ("reentry_order.md", reentry, "run_result_management.md"),
        ("reentry_order.md", reentry, "result_judgment_policy.md"),
        ("reentry_order.md", reentry, "obsidian-work-packet-router"),
        ("AGENTS.md", agents, "Architecture Invariants"),
        ("AGENTS.md", agents, "Exploration Mandate"),
        ("AGENTS.md", agents, "Run Evidence System"),
        ("AGENTS.md", agents, "Progressive Hardening"),
        ("AGENTS.md", agents, "Codex Work Lifecycle"),
        ("AGENTS.md", agents, "obsidian-work-packet-router"),
        ("architecture_debt_register.md", debt, "AD-001"),
        ("architecture_debt_register.md", debt, "AD-002"),
        ("architecture_debt_register.md", debt, "AD-003"),
        ("architecture_debt_register.md", debt, "AD-004"),
        ("architecture_debt_register.md", debt, "AD-005"),
        ("architecture_debt_register.md", debt, "AD-006"),
        ("architecture_debt_register.md", debt, "AD-007"),
        ("exploration_mandate.md", exploration, "promotion-ineligible"),
        ("exploration_mandate.md", exploration, "tier_c_local_research"),
        ("exploration_mandate.md", exploration, "WFO"),
        ("kpi_measurement_standard.md", kpi, "structural_scout"),
        ("kpi_measurement_standard.md", kpi, "regular_risk_execution"),
        ("kpi_measurement_standard.md", kpi, "trade_shape"),
        ("run_result_management.md", run_management, "run_registry.csv"),
        ("run_result_management.md", run_management, "run_manifest.json"),
        ("result_judgment_policy.md", judgment, "positive"),
        ("result_judgment_policy.md", judgment, "negative"),
        ("result_judgment_policy.md", judgment, "invalid"),
        ("promotion_policy.md", promotion, "promotion_candidate"),
        ("promotion_policy.md", promotion, "operating_promotion"),
        ("promotion_policy.md", promotion, "runtime_probe"),
        ("promotion_policy.md", promotion, "runtime_authority"),
    ]
    for label, text, needle in required_pairs:
        if needle not in text:
            errors.append(f"{label}: missing required reference `{needle}`")
    return errors


def check_progressive_hardening_warnings(repo_root: Path) -> list[str]:
    warnings: list[str] = []
    checks = [
        ("AGENTS.md", repo_root / "AGENTS.md"),
        ("exploration_mandate.md", repo_root / "docs/policies/exploration_mandate.md"),
        ("result_judgment_policy.md", repo_root / "docs/policies/result_judgment_policy.md"),
        ("obsidian-lane-classifier/SKILL.md", repo_root / ".agents/skills/obsidian-lane-classifier/SKILL.md"),
        ("obsidian-run-evidence-system/SKILL.md", repo_root / ".agents/skills/obsidian-run-evidence-system/SKILL.md"),
    ]
    required_terms = ("promotion_candidate", "operating_promotion", "runtime_probe", "runtime_authority")
    for label, path in checks:
        text = safe_read_text(path, encoding="utf-8-sig")
        for term in required_terms:
            if term not in text:
                warnings.append(f"{label}: progressive hardening warning: missing `{term}`")
    return warnings


def iter_skill_files(repo_root: Path) -> list[Path]:
    skills_root = repo_root / ".agents" / "skills"
    if not skills_root.exists():
        return []
    return sorted(skills_root.glob("*/SKILL.md"))


def parse_simple_openai_yaml(path: Path) -> tuple[dict[str, dict[str, str]], list[str]]:
    """Parse the repo's intentionally small openai.yaml subset.

    The validator avoids adding a PyYAML dependency. To keep the format
    predictable, repo-scoped agent metadata allows only top-level
    `interface:`/`policy:` sections and one-line scalar child keys.
    """
    parsed: dict[str, dict[str, str]] = {"interface": {}, "policy": {}}
    errors: list[str] = []
    current_section: str | None = None
    rel = path.as_posix()

    for line_number, raw_line in enumerate(safe_read_text(path, encoding="utf-8").splitlines(), start=1):
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        if raw_line.startswith("\t"):
            errors.append(f"{rel}:{line_number}: tabs are not allowed in openai.yaml")
            continue
        if not raw_line.startswith(" "):
            section_match = re.fullmatch(r"([A-Za-z0-9_]+):", raw_line.strip())
            if not section_match:
                errors.append(f"{rel}:{line_number}: only simple top-level sections are allowed")
                current_section = None
                continue
            section = section_match.group(1)
            if section not in OPENAI_YAML_TOP_LEVEL_SECTIONS:
                errors.append(f"{rel}:{line_number}: unsupported top-level section `{section}`")
            current_section = section
            continue

        if current_section is None:
            errors.append(f"{rel}:{line_number}: nested key has no supported parent section")
            continue
        match = re.fullmatch(r"  ([A-Za-z0-9_]+):\s*(.+)", raw_line)
        if not match:
            errors.append(
                f"{rel}:{line_number}: only two-space indented one-line scalar keys are allowed"
            )
            continue
        key, value = match.groups()
        value = value.strip()
        if value in {"|", ">"}:
            errors.append(f"{rel}:{line_number}: multiline scalars are not allowed")
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        parsed.setdefault(current_section, {})[key] = value.strip()

    return parsed, errors


def check_agent_settings(repo_root: Path) -> list[str]:
    errors: list[str] = []
    for skill_file in iter_skill_files(repo_root):
        skill_dir = skill_file.parent
        skill_name = frontmatter_name(skill_file) or skill_dir.name
        openai_yaml = skill_dir / "agents" / "openai.yaml"
        rel_yaml = openai_yaml.relative_to(repo_root).as_posix()
        if not openai_yaml.exists():
            errors.append(f"{skill_dir.relative_to(repo_root).as_posix()}: missing agents/openai.yaml")
            continue
        parsed, parse_errors = parse_simple_openai_yaml(openai_yaml)
        errors.extend(parse_errors)
        interface = parsed.get("interface", {})
        policy = parsed.get("policy", {})
        if not interface:
            errors.append(f"{rel_yaml}: missing interface section")
            continue
        for key in REQUIRED_AGENT_INTERFACE_KEYS:
            if not interface.get(key):
                errors.append(f"{rel_yaml}: missing or empty interface.{key}")
        if f"${skill_name}" not in interface.get("default_prompt", ""):
            errors.append(f"{rel_yaml}: interface.default_prompt must mention `${skill_name}`")
        if policy.get("allow_implicit_invocation") != "true":
            errors.append(f"{rel_yaml}: policy.allow_implicit_invocation must be true")
    return errors


def read_utf8_text_for_control_file(path: Path, rel: str, errors: list[str]) -> str | None:
    data = io_path(path).read_bytes()
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        errors.append(f"{rel}: not valid UTF-8: {exc}")
        return None
    if leading_utf8_bom_count(data) > 1:
        errors.append(f"{rel}: contains repeated UTF-8 BOM markers")
    if "\ufffd" in text:
        errors.append(f"{rel}: contains Unicode replacement character")
    if MOJIBAKE_RE.search(text):
        errors.append(f"{rel}: contains likely mojibake")
    return text


def parse_toml_control_file(path: Path, rel: str, errors: list[str]) -> dict[str, object]:
    if not path_exists(path):
        errors.append(f"{rel}: file does not exist")
        return {}
    text = read_utf8_text_for_control_file(path, rel, errors)
    if text is None:
        return {}
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        errors.append(f"{rel}: TOML parse failed: {exc}")
        return {}


def extract_task_force_roster_ids(registry_text: str) -> list[str]:
    return re.findall(r"(?m)^  - id:\s*(agent_\d{2}_[A-Za-z0-9_]+)\s*$", registry_text)


def check_codex_task_force_custom_agents(repo_root: Path) -> list[str]:
    errors: list[str] = []
    registry_path = repo_root / "docs/agent_control/codex_task_force_registry.yaml"
    registry_text = read_utf8_text_for_control_file(
        registry_path,
        "docs/agent_control/codex_task_force_registry.yaml",
        errors,
    )
    if registry_text is None:
        return errors

    roster_ids = extract_task_force_roster_ids(registry_text)
    if len(roster_ids) != 8:
        errors.append(
            "docs/agent_control/codex_task_force_registry.yaml: expected exactly 8 Task Force roster agents"
        )
    if len(set(roster_ids)) != len(roster_ids):
        errors.append("docs/agent_control/codex_task_force_registry.yaml: duplicate Task Force roster ids")

    required_registry_terms = (
        ".codex/agents",
        "micro_consult",
        "escalation_reason",
        "why_not_smaller",
        "advisory_only_no_reviewed_pass",
        "formal_review_only_for",
    )
    for term in required_registry_terms:
        if term not in registry_text:
            errors.append(f"docs/agent_control/codex_task_force_registry.yaml: missing `{term}`")

    config_path = repo_root / ".codex/config.toml"
    config = parse_toml_control_file(config_path, ".codex/config.toml", errors)
    agents_config = config.get("agents", {}) if isinstance(config.get("agents", {}), dict) else {}
    if config.get("service_tier") != "priority":
        errors.append(".codex/config.toml: service_tier must be priority for Task Force policy")
    if agents_config.get("max_depth") != 1:
        errors.append(".codex/config.toml: agents.max_depth must be 1")
    max_threads = agents_config.get("max_threads")
    if not isinstance(max_threads, int) or max_threads < max(8, len(roster_ids)):
        errors.append(".codex/config.toml: agents.max_threads must cover the 8-agent roster")

    agents_dir = repo_root / ".codex" / "agents"
    if not path_exists(agents_dir):
        errors.append("missing Codex custom agents dir: .codex/agents")
        return errors

    for agent_id in roster_ids:
        rel = f".codex/agents/{agent_id}.toml"
        agent_path = agents_dir / f"{agent_id}.toml"
        if not path_exists(agent_path):
            errors.append(f"missing Codex custom agent file: {rel}")
            continue
        agent = parse_toml_control_file(agent_path, rel, errors)
        if agent.get("name") != agent_id:
            errors.append(f"{rel}: name must match roster id `{agent_id}`")
        if not isinstance(agent.get("description"), str) or not agent.get("description", "").strip():
            errors.append(f"{rel}: missing or empty description")
        developer_instructions = agent.get("developer_instructions")
        if not isinstance(developer_instructions, str) or not developer_instructions.strip():
            errors.append(f"{rel}: missing or empty developer_instructions")
        elif agent_id not in developer_instructions:
            errors.append(f"{rel}: developer_instructions must mention `{agent_id}`")
        if agent.get("sandbox_mode") != "read-only":
            errors.append(f"{rel}: sandbox_mode must be read-only")
        if rel not in registry_text:
            errors.append(f"docs/agent_control/codex_task_force_registry.yaml: missing custom_agent_path `{rel}`")

    expected_files = {f"{agent_id}.toml" for agent_id in roster_ids}
    for agent_file in sorted(io_path(agents_dir).glob("*.toml")):
        durable_agent_file = Path(str(agent_file).removeprefix("\\\\?\\"))
        if durable_agent_file.name not in expected_files:
            errors.append(f"{durable_agent_file.relative_to(repo_root).as_posix()}: custom agent is not listed in registry")

    policy_targets = [
        ("AGENTS.md", repo_root / "AGENTS.md"),
        ("docs/policies/agent_trigger_policy.md", repo_root / "docs/policies/agent_trigger_policy.md"),
        ("docs/agent_control/work_family_registry.yaml", repo_root / "docs/agent_control/work_family_registry.yaml"),
        (
            ".agents/skills/obsidian-task-force-review/SKILL.md",
            repo_root / ".agents/skills/obsidian-task-force-review/SKILL.md",
        ),
    ]
    required_policy_terms = ("micro_consult", "escalation_reason", "why_not_smaller", "advisory_only_no_reviewed_pass")
    for label, path in policy_targets:
        text = read_utf8_text_for_control_file(path, label, errors)
        if text is None:
            continue
        for term in required_policy_terms:
            if term not in text:
                errors.append(f"{label}: missing Task Force policy term `{term}`")
    return errors


def check_skill_frontmatter(repo_root: Path) -> list[str]:
    errors: list[str] = []
    skills_root = repo_root / ".agents" / "skills"
    if not skills_root.exists():
        errors.append("missing repo-scoped skills root: .agents/skills")
        return errors

    for skill_file in iter_skill_files(repo_root):
        rel = skill_file.relative_to(repo_root).as_posix()
        text = safe_read_text(skill_file, encoding="utf-8-sig")
        lines = text.splitlines()
        if not lines or lines[0].strip().lstrip("\ufeff") != "---":
            errors.append(f"{rel}: missing YAML frontmatter opener")
            continue
        try:
            end_index = lines[1:].index("---") + 1
        except ValueError:
            errors.append(f"{rel}: missing YAML frontmatter closer")
            continue
        frontmatter = "\n".join(lines[1:end_index])
        if not re.search(r"^name:\s*\S+", frontmatter, flags=re.MULTILINE):
            errors.append(f"{rel}: missing frontmatter name")
        if not re.search(r"^description:\s*\S+", frontmatter, flags=re.MULTILINE):
            errors.append(f"{rel}: missing frontmatter description")
        if "TODO" in frontmatter:
            errors.append(f"{rel}: frontmatter still contains TODO")
    return errors


def frontmatter_name(skill_file: Path) -> str | None:
    text = safe_read_text(skill_file, encoding="utf-8-sig")
    lines = text.splitlines()
    if not lines or lines[0].strip().lstrip("\ufeff") != "---":
        return None
    try:
        end_index = lines[1:].index("---") + 1
    except ValueError:
        return None
    frontmatter = "\n".join(lines[1:end_index])
    match = re.search(r"^name:\s*(\S+)", frontmatter, flags=re.MULTILINE)
    if not match:
        return None
    return match.group(1).strip()


def extract_skill_routes(trigger_policy: str) -> set[str]:
    routes: set[str] = set()
    in_skills_section = False
    for raw_line in trigger_policy.splitlines():
        if raw_line.startswith("## "):
            in_skills_section = raw_line.startswith("## 스킬(") or raw_line.strip() == "## 스킬"
            continue
        if not in_skills_section:
            continue
        match = re.match(r"^- `([^`]+)`:", raw_line)
        if match:
            routes.add(match.group(1))
    return routes


def check_skill_routing_completeness(repo_root: Path) -> list[str]:
    errors: list[str] = []
    skills_root = repo_root / ".agents" / "skills"
    trigger_policy_path = repo_root / "docs/policies/agent_trigger_policy.md"
    if not skills_root.exists() or not trigger_policy_path.exists():
        return errors

    trigger_policy = safe_read_text(trigger_policy_path, encoding="utf-8-sig")
    routed_skills = extract_skill_routes(trigger_policy)
    if not routed_skills:
        errors.append("agent_trigger_policy.md: missing structured `## 스킬` routing list")

    skill_names: set[str] = set()
    for skill_file in iter_skill_files(repo_root):
        skill_dir = skill_file.parent
        rel_dir = skill_dir.relative_to(repo_root).as_posix()
        skill_name = frontmatter_name(skill_file) or skill_dir.name
        skill_names.add(skill_name)

        if skill_name not in routed_skills:
            errors.append(f"{rel_dir}: skill `{skill_name}` is not listed in agent_trigger_policy.md `## 스킬`")

        openai_yaml = skill_dir / "agents" / "openai.yaml"
        if not openai_yaml.exists():
            errors.append(f"{rel_dir}: missing agents/openai.yaml; every repo skill must expose routing metadata")

    for routed_skill in sorted(routed_skills - skill_names):
        errors.append(f"agent_trigger_policy.md: routed skill `{routed_skill}` has no matching SKILL.md")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Obsidian agent settings, skill routing, architecture guard links, and Korean encoding.")
    parser.add_argument("--repo-root", default=".", help="Repository root to validate.")
    parser.add_argument(
        "--encoding-scope",
        action="append",
        default=[],
        help="Repo-relative file or directory to validate for Korean UTF-8/BOM only. Repeat for multiple scopes.",
    )
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    errors: list[str] = []
    warnings: list[str] = []

    if args.encoding_scope:
        errors, warnings = check_encoding_scope(repo_root, args.encoding_scope)
        for warning in warnings:
            print(f"WARNING: {warning}")
        if errors:
            for error in errors:
                print(f"ERROR: {error}")
            return 1
        print("OK: scoped Korean encoding checks passed.")
        return 0

    errors.extend(check_required_paths(repo_root))
    doc_errors, doc_warnings = check_docs(repo_root)
    errors.extend(doc_errors)
    warnings.extend(doc_warnings)
    if not errors:
        errors.extend(check_policy_links(repo_root))
        warnings.extend(check_progressive_hardening_warnings(repo_root))
    errors.extend(check_agent_settings(repo_root))
    errors.extend(check_codex_task_force_custom_agents(repo_root))
    errors.extend(check_skill_frontmatter(repo_root))
    errors.extend(check_skill_routing_completeness(repo_root))

    for warning in warnings:
        print(f"WARNING: {warning}")
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    print("OK: agent settings, skill routing, architecture guard links, and Korean encoding checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
