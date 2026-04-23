"""Deterministic gate logic for PR approval classification.

Handles deny-lists, allow-lists, CODEOWNERS-soft ownership,
tier assignment, and file classification. No external dependencies.
"""

import re
import ast
from collections import Counter
from fnmatch import fnmatch
from pathlib import Path

# ── Pattern data ─────────────────────────────────────────────────

# Deny patterns use word-boundary matching (\b) to avoid false positives
# from substring hits like "session" in "SessionAnalysis" or "key" in
# "localStorage key". Patterns are compiled into regexes at import time.
#
# Two pattern lists per category:
#   "paths"  — matched against file paths only
#   "any"    — matched against both file paths and the PR title
# If a category only has "any", all patterns apply everywhere.

_DENY_PATTERN_DEFS: dict[str, dict[str, list[str]]] = {
    "auth": {
        "any": [
            "auth",
            "login",
            "signup",
            "oauth",
            "saml",
            "sso",
            "oidc",
            "credential",
            "password",
            "2fa",
            "mfa",
        ],
        # "session" and "token" match too broadly in titles and non-auth
        # file paths (e.g. SessionAnalysisWarning, tokenize, tokenizer).
        # "permission" matches permission-checking helpers everywhere.
        # Restrict these to path-only with tighter patterns.
        "paths": [
            "session_auth",
            "session_token",
            "auth/session",
            "auth/token",
            "permission",
        ],
    },
    "crypto_secrets": {
        "any": [
            "crypto",
            "encrypt",
            "decrypt",
            "vault",
        ],
        # "key", "secret", "cert", "signing" are too broad for titles.
        # "key" alone matches "keyboard", "hotkey", "localStorage key".
        # Use path-only with compound patterns.
        "paths": [
            "secret",
            r"api[_-]?key",
            r"secret[_-]?key",
            r"private[_-]?key",
            r"signing[_-]?key",
            "certificate",
            r"\.env",
            r"\.pem",
        ],
    },
    "migrations": {
        "paths": [
            "migrations/",
            "migrate",
            "backfill",
            "schema_change",
        ],
    },
    "infra_cicd": {
        "any": [
            "terraform",
            "kubernetes",
            "helm",
        ],
        "paths": [
            r"k8s",
            "dockerfile",
            "docker-compose",
            r"\.github/workflows",
            "deploy",
            "iam",
            "cloudflare",
            "cdn",
            "waf",
            "routing",
        ],
    },
    "billing": {
        "any": [
            "billing",
            "payment",
            "stripe",
            "invoice",
            "subscription",
            "pricing",
        ],
    },
    "public_api": {
        "any": [
            "openapi",
            "api_schema",
            "swagger",
            "public_api",
        ],
    },
    "deps_toolchain": {
        # All path-only — these are literal filenames, not title words.
        "paths": [
            r"package\.json",
            r"requirements\.txt",
            r"pyproject\.toml",
            "pnpm-lock",
            "package-lock",
            r"yarn\.lock",
            r"uv\.lock",
            r"Cargo\.toml",
            r"go\.mod",
            "Makefile",
            "Dockerfile",
            "tsconfig",
            r"\.tool-versions",
            r"\.nvmrc",
        ],
    },
}


def _compile_pattern(p: str, *, for_paths: bool) -> re.Pattern[str]:
    r"""Compile a single deny pattern into a case-insensitive regex.

    Patterns containing path separators (/) or starting with a dot are
    treated as literal path fragments — no boundaries added.

    For other patterns, boundary matching depends on context:
    - Title matching uses \b (standard word boundaries — underscore is
      a word char, which is correct for natural-language titles).
    - Path matching uses a looser boundary that also breaks on _ and -,
      since file paths use those as separators. This ensures "secret"
      matches "secret_key_store.py" but not "nosecrets.py".
    """
    if "/" in p or p.startswith(r"\."):
        return re.compile(rf"(?i){p}")
    if for_paths:
        # Break on non-alphanumeric (including _ and -) or string edges
        return re.compile(rf"(?i)(?<![a-zA-Z0-9]){p}(?![a-zA-Z0-9])")
    return re.compile(rf"(?i)\b{p}\b")


def _compile_patterns(
    defs: dict[str, dict[str, list[str]]],
) -> dict[str, dict[str, list[re.Pattern[str]]]]:
    """Compile pattern definitions into regexes.

    "paths" patterns use path-friendly boundaries (break on _ and -).
    "any" patterns are compiled twice: once for paths, once for titles,
    and stored as a list of (path_rx, title_rx) tuples.
    """
    compiled: dict[str, dict[str, list]] = {}
    for category, groups in defs.items():
        compiled[category] = {}
        for scope, patterns in groups.items():
            if scope == "paths":
                compiled[category][scope] = [_compile_pattern(p, for_paths=True) for p in patterns]
            else:
                # "any" — store (path_regex, title_regex) pairs
                compiled[category][scope] = [
                    (_compile_pattern(p, for_paths=True), _compile_pattern(p, for_paths=False)) for p in patterns
                ]
    return compiled


DENY_PATTERNS = _compile_patterns(_DENY_PATTERN_DEFS)

ALLOW_ONLY_EXTENSIONS = {
    ".md",
    ".mdx",
    ".txt",
    ".rst",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".csv",
    ".svg",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".webp",
    ".snap",
    ".lock",
}

ALLOW_PATH_PATTERNS = [
    "docs/",
    "README",
    "CHANGELOG",
    "LICENSE",
    "CONTRIBUTING",
    ".github/CODEOWNERS",
    ".gitignore",
    ".editorconfig",
    "generated/",
    "__snapshots__/",
]

CONVENTIONAL_RE = re.compile(r"^(\w+)(?:\(([^)]*)\))?!?:\s*(.+)")


# ── Conventional commit parsing ──────────────────────────────────


def parse_conventional_commit(subject: str) -> dict:
    m = CONVENTIONAL_RE.match(subject)
    if not m:
        return {"type": None, "scope": None, "description": subject}
    return {"type": m.group(1), "scope": m.group(2), "description": m.group(3)}


# ── File classification ──────────────────────────────────────────


_TEST_FILE_RE = re.compile(
    r"(?:^|/)(?:__tests__|tests?)/|[_.](?:test|spec)\.[^/]+$|_test\.py$",
    re.IGNORECASE,
)


def classify_path(path: str) -> str:
    low = path.lower()
    if _TEST_FILE_RE.search(low):
        return "test"
    if low.endswith(".md"):
        return "docs"
    if "migration" in low:
        return "migration"
    if low.endswith((".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".lock")):
        return "config"
    if low.endswith((".ts", ".tsx", ".js", ".jsx", ".css", ".scss")):
        return "frontend"
    if low.endswith(".py"):
        return "python"
    return "other"


def classify_files(files: list[str]) -> dict:
    categories: Counter = Counter()
    top_dirs: set[str] = set()
    extensions: Counter = Counter()

    for path in files:
        parts = path.split("/")
        if len(parts) > 1:
            top_dirs.add(parts[0])
            if parts[0] == "products" and len(parts) > 2:
                top_dirs.add(f"products/{parts[1]}")
        if "." in path:
            extensions[path.rsplit(".", 1)[-1]] += 1
        categories[classify_path(path)] += 1

    return {
        "categories": dict(categories),
        "top_dirs": sorted(top_dirs),
        "extensions": dict(extensions),
    }


# ── Scope helpers ────────────────────────────────────────────────


def scope_breadth(top_dirs: list[str]) -> str:
    top = {d.split("/")[0] for d in top_dirs}
    if len(top) <= 1:
        return "single-area"
    if len(top) == 2:
        return "two-areas"
    return "cross-cutting"


def test_only(categories: dict[str, int]) -> bool:
    return categories.get("test", 0) > 0 and sum(categories.values()) == categories.get("test", 0)


# ── Deny / allow detection ───────────────────────────────────────


def detect_deny_categories(files: list[str], subject: str, ignored_files: set[str] | None = None) -> list[str]:
    hits: set[str] = set()
    ignored_files_lower = {f.lower() for f in ignored_files or set()}
    paths_lower = [f.lower() for f in files if f.lower() not in ignored_files_lower]
    subject_lower = subject.lower()

    for category, scopes in DENY_PATTERNS.items():
        found = False
        # "paths" patterns — only match against file paths
        for rx in scopes.get("paths", []):
            if found:
                break
            for p in paths_lower:
                if rx.search(p):
                    hits.add(category)
                    found = True
                    break
        if found:
            continue
        # "any" patterns — match against file paths (path_rx) and title (title_rx)
        for path_rx, title_rx in scopes.get("any", []):
            if found:
                break
            for p in paths_lower:
                if path_rx.search(p):
                    hits.add(category)
                    found = True
                    break
            if not found and title_rx.search(subject_lower):
                hits.add(category)
                found = True
    return sorted(hits)


NON_DB_FIELD_KWARGS = {
    "blank",
    "choices",
    "editable",
    "error_messages",
    "help_text",
    "limit_choices_to",
    "on_delete",
    "related_name",
    "related_query_name",
    "validators",
    "verbose_name",
}


FieldSignature = tuple[str, tuple[str, ...], tuple[tuple[str, str], ...]]


def detect_noop_migration_files(migration_file_contents: dict[str, str], base_file_contents: dict[str, str]) -> set[str]:
    """Detect migration files that only update Django state with no database SQL.

    Mirrors Django's schema editor at a static level: compare old and new field
    deconstruction while ignoring Field.non_db_attrs. Anything outside this
    narrow AlterField shape still goes through the normal migration deny-list.
    """
    base_fields = _base_model_field_signatures(base_file_contents)
    noop_files: set[str] = set()

    for path, content in migration_file_contents.items():
        if not _is_migration_python_file(path):
            continue
        if _is_noop_migration_content(content, base_fields):
            noop_files.add(path)

    return noop_files


def migration_bookkeeping_files_for(migration_files: set[str]) -> set[str]:
    return {str(Path(path).parent / "max_migration.txt") for path in migration_files}


def _is_migration_python_file(path: str) -> bool:
    low = path.lower()
    return "/migrations/" in low and low.endswith(".py") and not low.endswith("/__init__.py")


def _is_noop_migration_content(content: str, base_fields: dict[tuple[str, str], set[FieldSignature]]) -> bool:
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return False

    operations = _migration_operations(tree)
    return bool(operations) and all(_is_noop_migration_operation(op, base_fields) for op in operations)


def _migration_operations(tree: ast.Module) -> list[ast.AST]:
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != "Migration":
            continue
        for stmt in node.body:
            if isinstance(stmt, ast.Assign) and _assigns_to_name(stmt, "operations") and isinstance(stmt.value, ast.List):
                return list(stmt.value.elts)
    return []


def _assigns_to_name(stmt: ast.Assign, name: str) -> bool:
    return any(isinstance(target, ast.Name) and target.id == name for target in stmt.targets)


def _is_noop_migration_operation(node: ast.AST, base_fields: dict[tuple[str, str], set[FieldSignature]]) -> bool:
    if not isinstance(node, ast.Call) or not _is_attribute_call(node, "migrations", "AlterField"):
        return False

    model_name = _string_keyword_value(node, "model_name")
    field_name = _string_keyword_value(node, "name")
    field = _keyword_value(node, "field")
    if model_name is None or field_name is None or not isinstance(field, ast.Call):
        return False

    new_signature = _field_signature(field)
    if new_signature is None:
        return False

    old_signatures = base_fields.get((model_name.lower(), field_name))
    return old_signatures == {new_signature}


def _base_model_field_signatures(file_contents: dict[str, str]) -> dict[tuple[str, str], set[FieldSignature]]:
    fields: dict[tuple[str, str], set[FieldSignature]] = {}

    for content in file_contents.values():
        try:
            tree = ast.parse(content)
        except SyntaxError:
            continue

        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            for stmt in node.body:
                field_name, value = _field_assignment(stmt)
                if field_name is None or value is None:
                    continue
                field_call = _find_model_field_call(value)
                if field_call is None:
                    continue
                signature = _field_signature(field_call)
                if signature is None:
                    continue
                fields.setdefault((node.name.lower(), field_name), set()).add(signature)

    return fields


def _field_assignment(stmt: ast.stmt) -> tuple[str | None, ast.AST | None]:
    if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
        return stmt.targets[0].id, stmt.value
    if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
        return stmt.target.id, stmt.value
    return None, None


def _find_model_field_call(node: ast.AST) -> ast.Call | None:
    if isinstance(node, ast.Call) and _is_model_field_call(node):
        return node
    for child in ast.iter_child_nodes(node):
        found = _find_model_field_call(child)
        if found is not None:
            return found
    return None


def _field_signature(node: ast.Call) -> FieldSignature | None:
    if not _is_model_field_call(node):
        return None

    kwargs = []
    for kw in node.keywords:
        if kw.arg is None:
            return None
        if kw.arg in NON_DB_FIELD_KWARGS:
            continue
        kwargs.append((kw.arg, ast.dump(kw.value)))

    return (
        node.func.attr,
        tuple(ast.dump(arg) for arg in node.args),
        tuple(sorted(kwargs)),
    )


def _is_model_field_call(node: ast.Call) -> bool:
    return (
        isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "models"
        and (node.func.attr.endswith("Field") or node.func.attr in {"ForeignKey", "OneToOneField", "ManyToManyField"})
    )


def _keyword_value(node: ast.Call, name: str) -> ast.AST | None:
    for kw in node.keywords:
        if kw.arg == name:
            return kw.value
    return None


def _string_keyword_value(node: ast.Call, name: str) -> str | None:
    value = _keyword_value(node, name)
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return value.value
    return None


def _is_attribute_call(node: ast.Call, namespace: str, attr: str) -> bool:
    return (
        isinstance(node.func, ast.Attribute)
        and node.func.attr == attr
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == namespace
    )


def has_dependency_changes(files: list[str]) -> bool:
    dep_files = {
        "package.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "package-lock.json",
        "requirements.txt",
        "pyproject.toml",
        "uv.lock",
        "Cargo.toml",
        "go.mod",
        "go.sum",
    }
    dep_files_lower = {d.lower() for d in dep_files}
    return any(Path(f).name.lower() in dep_files_lower for f in files)


def has_ci_workflow_changes(files: list[str]) -> bool:
    return any(".github/workflows" in f or ".github/actions" in f for f in files)


def is_allow_listed_only(files: list[str]) -> bool:
    if not files:
        return False
    for f in files:
        low = f.lower()
        ext = Path(low).suffix
        if ext in ALLOW_ONLY_EXTENSIONS:
            continue
        if any(p.lower() in low for p in ALLOW_PATH_PATTERNS):
            continue
        return False
    return True


# ── CODEOWNERS-soft ──────────────────────────────────────────────


class CodeownersRule:
    def __init__(self, pattern: str, teams: list[str]):
        self.raw_pattern = pattern
        self.teams = set(teams)
        self._pattern = pattern.lstrip("/").replace("\\*\\*", "**").replace("\\*", "*")

    def matches(self, filepath: str) -> bool:
        pat = self._pattern
        if not any(c in pat for c in ("*", "?")):
            if filepath == pat or filepath == pat.rstrip("/"):
                return True
            prefix = pat if pat.endswith("/") else pat + "/"
            if filepath.startswith(prefix):
                return True
            return False
        if fnmatch(filepath, pat):
            return True
        if "**" in pat and fnmatch(filepath, pat.rstrip("/") + "/**"):
            return True
        return False


def parse_codeowners_soft(path: Path) -> list[CodeownersRule]:
    rules = []
    if not path.exists():
        return rules
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            pattern = parts[0]
            teams = [t for t in parts[1:] if t.startswith("@")]
            if teams:
                rules.append(CodeownersRule(pattern, teams))
    return rules


def resolve_owners(filepath: str, rules: list[CodeownersRule]) -> set[str]:
    matched_teams: set[str] = set()
    for rule in rules:
        if rule.matches(filepath):
            matched_teams = rule.teams
    return matched_teams


def detect_ownership(files: list[str], rules: list[CodeownersRule]) -> dict:
    all_teams: set[str] = set()
    owned_files = 0
    unowned_files = 0
    team_file_counts: Counter = Counter()

    for f in files:
        teams = resolve_owners(f, rules)
        if teams:
            owned_files += 1
            all_teams.update(teams)
            for t in teams:
                team_file_counts[t] += 1
        else:
            unowned_files += 1

    return {
        "teams": sorted(all_teams),
        "team_count": len(all_teams),
        "owned_files": owned_files,
        "unowned_files": unowned_files,
        "team_file_counts": dict(team_file_counts.most_common()),
        "cross_team": len(all_teams) > 1,
    }


# ── Tier assignment ──────────────────────────────────────────────


MAX_LINES = 500
MAX_FILES = 20


def assign_tier(
    *,
    deny_categories: list[str],
    allow_listed_only: bool,
    is_test_only: bool,
    has_new_files: bool,
    lines_total: int,
    files_changed: int,
    breadth: str,
    commit_type: str | None,
) -> str:
    if deny_categories:
        return "T2-never"
    if has_new_files:
        return "T1-agent"
    if allow_listed_only:
        return "T0-deterministic"
    if is_test_only:
        return "T0-deterministic"
    return "T1-agent"


def t1_risk_subclass(
    *,
    lines_total: int,
    files_changed: int,
    breadth: str,
) -> str:
    if lines_total <= 20 and files_changed <= 3 and breadth == "single-area":
        return "T1a-trivial"
    if lines_total <= 100 and files_changed <= 5 and breadth != "cross-cutting":
        return "T1b-small"
    if lines_total <= 300 and files_changed <= 15 and breadth != "cross-cutting":
        return "T1c-medium"
    return "T1d-complex"
