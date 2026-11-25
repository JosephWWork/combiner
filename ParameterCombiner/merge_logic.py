"""Pure-Python logic for merging duplicate Fusion user parameters.

Nothing in this module imports adsk, so it can be unit-tested outside Fusion.
"""
import math
import re
from dataclasses import dataclass, field

# "Width_1" -> ("Width", "1"). Applied repeatedly for chains like "Width_1_1".
SUFFIX_RE = re.compile(r'^(.+)_(\d+)$')
# An identifier inside an expression (parameter names, unit names, functions).
IDENT_RE = re.compile(r'[^\W\d]\w*')


@dataclass
class ParamInfo:
    name: str
    expression: str
    unit: str
    value: float  # Fusion internal units (cm, rad); None if not numeric
    comment: str = ''
    is_favorite: bool = False


@dataclass
class Merge:
    duplicate: str
    target: str


@dataclass
class Conflict:
    """Two user parameters that look like duplicates but differ: fix manually."""
    duplicate: str
    target: str
    duplicate_expression: str
    target_expression: str


@dataclass
class ReviewItem:
    """A possible duplicate involving a model parameter: reported, never merged."""
    duplicate: str
    target: str
    same_value: bool
    duplicate_expression: str
    target_expression: str
    duplicates_user_param: bool = False  # model param duplicating a user param


@dataclass
class Plan:
    merges: list = field(default_factory=list)
    conflicts: list = field(default_factory=list)
    review: list = field(default_factory=list)

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
    if a.unit != b.unit:
        return False
    if a.value is None or b.value is None:
        # Non-numeric (text / true-false) parameter: compare what was typed.
        return a.value is None and b.value is None and a.expression.strip() == b.expression.strip()
    return math.isclose(a.value, b.value, rel_tol=1e-9, abs_tol=1e-12)


def rewrite_expression(expression, mapping):
    """Replace whole-identifier references using mapping (old name -> new name)."""
    if not mapping or not expression:
        return expression
    return IDENT_RE.sub(lambda m: mapping.get(m.group(0), m.group(0)), expression)


def build_plan(params, model_params=None):
    """Decide what to merge.

    params:       iterable of ParamInfo (the design's user parameters)
    model_params: iterable of ParamInfo (model parameters)

    User/user pairs with the same value and unit are merged. User/user pairs
    that differ go to plan.conflicts for the user to fix by hand. Any pair
    involving a model parameter goes to plan.review and is only reported.
    """
    by_name = {p.name: p for p in params}
    plan = Plan()

    model_by_name = {p.name: p for p in (model_params or []) if p.name not in by_name}
    if model_by_name:
        everything = {**model_by_name, **by_name}
        for dup, root in sorted(find_duplicates(everything).items()):
            if dup in model_by_name or root in model_by_name:
                d, r = everything[dup], everything[root]
                plan.review.append(ReviewItem(dup, root, values_match(d, r), d.expression, r.expression,
                                              dup in model_by_name and root in by_name))

    for dup, root in sorted(find_duplicates(by_name).items()):
        d, r = by_name[dup], by_name[root]
        if values_match(d, r):
            plan.merges.append(Merge(dup, root))
        else:
            plan.conflicts.append(Conflict(dup, root, d.expression, r.expression))
    return plan
