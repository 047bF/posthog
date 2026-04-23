"""Static detection for Django migrations that emit no database SQL."""

import ast
from pathlib import Path

# Mirrors django.db.models.Field.non_db_attrs for the Django version used by
# this repo. These field kwargs are removed before Django decides whether an
# AlterField requires database work.
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


def detect_noop_migration_files(
    migration_file_contents: dict[str, str], base_file_contents: dict[str, str]
) -> set[str]:
    """Detect migration files that only update Django state with no database SQL.

    Mirrors Django's schema editor at a static level: compare old and new field
    deconstruction while ignoring Field.non_db_attrs. Anything outside this
    narrow AlterField shape should still go through the migration deny-list.
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
            if (
                isinstance(stmt, ast.Assign)
                and _assigns_to_name(stmt, "operations")
                and isinstance(stmt.value, ast.List)
            ):
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
