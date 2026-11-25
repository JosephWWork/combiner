"""Pure-Python logic for merging duplicate Fusion user parameters.

Nothing in this module imports adsk, so it can be unit-tested outside Fusion.
"""
import csv
import io
import math
import re
from dataclasses import dataclass, field

# "Width_1" -> ("Width", "1"). Applied repeatedly for chains like "Width_1_1".
SUFFIX_RE = re.compile(r'^(.+)_(\d+)$')
# An identifier inside an expression (parameter names, unit names, functions).
IDENT_RE = re.compile(r'[^\W\d]\w*')
# A bare number such as "25", "25.4" or "25,4" (no unit).
NUMBER_ONLY_RE = re.compile(r'^\s*[-+]?(\d+([.,]\d*)?|[.,]\d+)([eE][-+]?\d+)?\s*$')


@dataclass
class ParamInfo:
    name: str
    expression: str
    unit: str
    value: float  # Fusion internal units (cm, rad)
    comment: str = ''
    is_favorite: bool = False


@dataclass
class Standard:
    name: str
    expression: str
    unit: str = ''
    comment: str = ''


@dataclass
class Merge:
    duplicate: str
    target: str
    reason: str


@dataclass
class Skipped:
    duplicate: str
    target: str
    reason: str


@dataclass
class ReviewItem:
    """A possible duplicate involving a model parameter: reported, never merged."""
    duplicate: str
    target: str
    same_value: bool
    duplicate_expression: str
    target_expression: str


@dataclass
class Plan:
    merges: list = field(default_factory=list)
    skipped: list = field(default_factory=list)
    review: list = field(default_factory=list)
    # target name -> new expression taken from the standards CSV
    target_updates: dict = field(default_factory=dict)

    @property
    def mapping(self):
        return {m.duplicate: m.target for m in self.merges}


def find_duplicates(names):
    """Return {duplicate_name: root_name} for names like "X_1" whose root "X" exists.

    Suffixes are stripped repeatedly, so "Width_1_1" maps to "Width" when it
    exists, falling back to "Width_1" only if "Width" does not exist.
    """
    names = set(names)
    result = {}
    for name in names:
        candidate, root = name, None
        while True:
            m = SUFFIX_RE.match(candidate)
            if not m:
                break
            candidate = m.group(1)
            if candidate in names:
                root = candidate
        if root is not None:
            result[name] = root
    return result


def values_match(a, b):
    return a.unit == b.unit and math.isclose(a.value, b.value, rel_tol=1e-9, abs_tol=1e-12)


def normalize_expression(expression, unit):
    """Append the unit to a bare number ("25" -> "25 mm") and fix decimal commas."""
    expr = expression.strip()
    if NUMBER_ONLY_RE.match(expr):
        expr = expr.replace(',', '.')
        if unit:
            expr = f'{expr} {unit}'
    return expr


def rewrite_expression(expression, mapping):
    """Replace whole-identifier references using mapping (old name -> new name)."""
    if not mapping or not expression:
        return expression
    return IDENT_RE.sub(lambda m: mapping.get(m.group(0), m.group(0)), expression)


def build_plan(params, standards=None, model_params=None):
    """Decide what to merge.

    params:       iterable of ParamInfo (the design's user parameters)
    standards:    {name: Standard} from the CSV, or None
    model_params: iterable of ParamInfo (model parameters). Only user/user pairs
                  are merged; any pair involving a model parameter goes to
                  plan.review for the user to look at.
    """
    standards = standards or {}
    by_name = {p.name: p for p in params}
    plan = Plan()

    model_by_name = {p.name: p for p in (model_params or []) if p.name not in by_name}
    if model_by_name:
        everything = {**model_by_name, **by_name}
        for dup, root in sorted(find_duplicates(everything).items()):
            if dup in model_by_name or root in model_by_name:
                d, r = everything[dup], everything[root]
                plan.review.append(ReviewItem(dup, root, values_match(d, r), d.expression, r.expression))

    for dup, root in sorted(find_duplicates(by_name).items()):
        d, r = by_name[dup], by_name[root]
        if values_match(d, r):
            plan.merges.append(Merge(dup, root, 'values match'))
            continue
        std = standards.get(root)
        if std is not None:
            expr = normalize_expression(std.expression, std.unit or r.unit)
            plan.target_updates[root] = expr
            plan.merges.append(Merge(dup, root, f'values differ; {root} set to standard "{expr}"'))
        else:
            plan.skipped.append(Skipped(
                dup, root,
                f'values differ ({r.expression} vs {d.expression}) and {root} is not in the standards CSV'))
    return plan


_COLUMN_ALIASES = {
    'name': ('name', 'parameter', 'param'),
    'expression': ('expression', 'expr', 'value'),
    'unit': ('unit', 'units'),
    'comment': ('comment', 'comments', 'description'),
}


def parse_standards(text):
    """Parse the standards CSV into {name: Standard}.

    Needs a header row with at least Name and Expression columns (Unit and
    Comment optional; header names are case-insensitive). Comma, semicolon or
    tab delimited.
    """
    text = text.lstrip('﻿')
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=',;\t')
    except csv.Error:
        dialect = csv.excel
    rows = [r for r in csv.reader(io.StringIO(text), dialect) if any(c.strip() for c in r)]
    if not rows:
        return {}

    header = [h.strip().lower() for h in rows[0]]
    cols = {}
    for key, aliases in _COLUMN_ALIASES.items():
        cols[key] = next((header.index(a) for a in aliases if a in header), None)
    if cols['name'] is None or cols['expression'] is None:
        raise ValueError('Standards CSV needs a header row with "Name" and "Expression" columns. '
                         f'Found: {rows[0]}')

    def cell(row, key):
        i = cols[key]
        return row[i].strip() if i is not None and i < len(row) else ''

    standards = {}
    for row in rows[1:]:
        name, expr = cell(row, 'name'), cell(row, 'expression')
        if name and expr:
            standards[name] = Standard(name, expr, cell(row, 'unit'), cell(row, 'comment'))
    return standards
