"""Fusion add-in: merge duplicate user parameters (Width_1 -> Width).

Adds "Merge Duplicate Parameters" to Design > Solid > Modify. Clicking it:
  1. Shows a preview and asks to confirm. Pairs with the same value are
     merged; pairs with different values are listed for you to fix by hand
     (then run again to merge them). Model-parameter duplicates are listed only.
  2. All references are re-pointed and duplicates deleted inside one command,
     so a single Ctrl+Z undoes the whole merge.
"""
import importlib.util
import os
import sys
import traceback

import adsk.core
import adsk.fusion

_HERE = os.path.dirname(os.path.abspath(__file__))


def _load_local(name):
    """Load <name>.py from this add-in's folder by exact path.

    A plain `import` searches sys.path, which Fusion shares between all
    scripts and add-ins, so it could pick up a same-named file from another
    folder (e.g. an old copy under API/Scripts). Loading by path, under a
    unique module name, always gets ours and always the current file.
    """
    module_name = f'ParameterCombiner_{name}'
    spec = importlib.util.spec_from_file_location(module_name, os.path.join(_HERE, f'{name}.py'))
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module  # dataclasses look the module up here
    spec.loader.exec_module(module)
    return module


merge_logic = _load_local('merge_logic')

CMD_ID = 'ParameterCombiner_MergeDuplicates'
TITLE = 'Merge Duplicate Parameters'
TOOLTIP = 'Merge duplicate user parameters (e.g. Width_1 into Width) and list any that need manual fixing.'
PANEL_ID = 'SolidModifyPanel'                # Design workspace > Solid tab > Modify
POSITION_AFTER = 'ChangeParameterCommand'   # place next to Change Parameters if found
RESOURCES = os.path.join(_HERE, 'resources', 'MergeDuplicates')
MAX_LINES = 40

_app = None
_ui = None
_handlers = []      # kept for the add-in's lifetime
_cmd_handlers = []  # per-click handlers, cleared when the command ends
_plan = None
_report = ''


def run(context):
    global _app, _ui
    try:
        _app = adsk.core.Application.get()
        _ui = _app.userInterface

        _remove_ui()  # clean up anything left from a previous load
        cmd_def = _ui.commandDefinitions.addButtonDefinition(CMD_ID, TITLE, TOOLTIP, RESOURCES)
        on_created = _CommandCreatedHandler()
        cmd_def.commandCreated.add(on_created)
        _handlers.append(on_created)

        panel = _ui.allToolbarPanels.itemById(PANEL_ID)
        try:
            panel.controls.addCommand(cmd_def, POSITION_AFTER, False)
        except Exception:
            panel.controls.addCommand(cmd_def)
    except Exception:
        if _ui:
            _ui.messageBox('Failed to start:\n{}'.format(traceback.format_exc()), TITLE)


def stop(context):
    try:
        _remove_ui()
    except Exception:
        if _ui:
            _ui.messageBox('Failed to stop:\n{}'.format(traceback.format_exc()), TITLE)
    finally:
        _handlers.clear()
        _cmd_handlers.clear()


def _remove_ui():
    panel = _ui.allToolbarPanels.itemById(PANEL_ID)
    control = panel.controls.itemById(CMD_ID) if panel else None
    if control:
        control.deleteMe()
    cmd_def = _ui.commandDefinitions.itemById(CMD_ID)
    if cmd_def:
        cmd_def.deleteMe()


def _prepare():
    """Analyse the design and ask to confirm. Returns a Plan to apply, or None."""
    design = adsk.fusion.Design.cast(_app.activeProduct)
    if not design:
        _ui.messageBox('Open a design first.', TITLE)
        return None

    try:
        params = [_info(p) for p in design.userParameters]
    except RuntimeError:
        _ui.messageBox('This design has no parameters to merge.\n\n'
                       'It is in direct modelling mode (design history is turned off). To use '
                       'parameters, right-click the top item in the Browser and choose '
                       '"Capture Design History".', TITLE)
        return None
    plan = merge_logic.build_plan(params, _model_params(design))
    if not (plan.merges or plan.conflicts or plan.review):
        _ui.messageBox('No duplicate parameters found.', TITLE)
        return None
    if not plan.merges:
        _ui.messageBox('Nothing to merge automatically.\n\n' + _preview_text(plan), TITLE)
        return None

    answer = _ui.messageBox(_preview_text(plan) + '\n\nProceed with merge?', TITLE,
                            adsk.core.MessageBoxButtonTypes.YesNoButtonType,
                            adsk.core.MessageBoxIconTypes.QuestionIconType)
    return plan if answer == adsk.core.DialogResults.DialogYes else None


def _safe_value(p):
    """p.value, or None for text / true-false parameters (Fusion raises on those)."""
    try:
        return p.value
    except RuntimeError:
        return None


def _info(p):
    return merge_logic.ParamInfo(p.name, p.expression, p.unit, _safe_value(p), p.comment, p.isFavorite)


def _model_params(design):
    """Model parameters from every component (feature/sketch dimensions).

    A direct-modelling design (history off) has none, and Fusion raises
    "this is not a parametric design" if asked, so skip it.
    """
    result, seen = [], set()
    if design.designType != adsk.fusion.DesignTypes.ParametricDesignType:
        return result
    for comp in design.allComponents:
        try:
            model_params = comp.modelParameters
        except RuntimeError:
            continue
        for p in model_params:
            if p.name not in seen:
                seen.add(p.name)
                result.append(merge_logic.ParamInfo(p.name, p.expression, p.unit, _safe_value(p), p.comment))
    return result


# ---------------------------------------------------------------- reporting

def _limit(lines):
    if len(lines) > MAX_LINES:
        return lines[:MAX_LINES] + [f'  ... and {len(lines) - MAX_LINES} more']
    return lines


def _review_status(r):
    if r.same_value:
        return f'same value ({r.target_expression})'
    return f'DIFFERENT value ({r.target_expression} vs {r.duplicate_expression})'


def _review_lines(review):
    of_user = [r for r in review if r.duplicates_user_param]
    other = [r for r in review if not r.duplicates_user_param]
    lines = []
    if of_user:
        lines.append(f'Model parameters duplicating a user parameter ({len(of_user)}) - not changed:')
        lines += _limit([f'  {r.duplicate} (model) duplicates {r.target} (user): {_review_status(r)}'
                         for r in of_user])
    if other:
        if lines:
            lines.append('')
        lines.append(f'Other model parameters that could possibly be merged ({len(other)}) - '
                     'not changed, review manually:')
        lines += _limit([f'  {r.duplicate} / {r.target}: {_review_status(r)}' for r in other])
    return lines


def _conflict_lines(conflicts):
    lines = [f'User parameters with DIFFERENT values ({len(conflicts)}) - not merged. '
             'Fix the value of one, then run again:']
    lines += _limit([f'  {c.duplicate} = {c.duplicate_expression}   vs   {c.target} = {c.target_expression}'
                     for c in conflicts])
    return lines


def _preview_text(plan):
    lines = []
    if plan.merges:
        lines.append(f'Will merge {len(plan.merges)} user parameter(s) with the same value:')
        lines += _limit([f'  {m.duplicate} -> {m.target}' for m in plan.merges])
    if plan.conflicts:
        lines += ([''] if lines else []) + _conflict_lines(plan.conflicts)
    if plan.review:
        lines += ([''] if lines else []) + _review_lines(plan.review)
    return '\n'.join(lines)


# ---------------------------------------------------------------- apply

def _apply(design, plan):
    user_params = design.userParameters
    errors = []

    # 1. Carry comment / favourite over if the target lacks them.
    for m in plan.merges:
        d, t = user_params.itemByName(m.duplicate), user_params.itemByName(m.target)
        if not d or not t:
            continue
        try:
            if not t.comment and d.comment:
                t.comment = d.comment
            if d.isFavorite and not t.isFavorite:
                t.isFavorite = True
        except Exception:
            pass

    # 2. Re-point every expression (model + user parameters) at the targets.
    mapping = plan.mapping
    rewritten = 0
    if design.designType == adsk.fusion.DesignTypes.ParametricDesignType:
        collections = (design.allParameters, design.userParameters)
    else:
        collections = (design.userParameters,)
    for coll in collections:
        for p in coll:
            try:
                old = p.expression
                new = merge_logic.rewrite_expression(old, mapping)
                if new != old:
                    p.expression = new
                    rewritten += 1
            except Exception as e:
                errors.append(f'Could not update {p.name}: {e}')

    # 3. Delete duplicates; repeat while progress is made (chains).
    pending = [m.duplicate for m in plan.merges]
    deleted = []
    while pending:
        remaining = []
        for name in pending:
            p = user_params.itemByName(name)
            if p is None:
                continue
            try:
                ok = p.deleteMe()
            except Exception:
                ok = False
            (deleted if ok else remaining).append(name)
        if len(remaining) == len(pending):
            break
        pending = remaining
    for name in pending:
        p = user_params.itemByName(name)
        users = [d.name for d in p.dependentParameters] if p else []
        errors.append(f'Could not delete {name}' + (f' (still used by {", ".join(users)})' if users else ''))

    lines = [f'Merged and deleted {len(deleted)} duplicate(s).',
             f'Updated {rewritten} expression(s).']
    if plan.conflicts:
        lines += [''] + _conflict_lines(plan.conflicts)
    if plan.review:
        lines += [''] + _review_lines(plan.review)
    if errors:
        lines += ['', 'Problems:'] + _limit(['  ' + e for e in errors])
    lines += ['', 'Ctrl+Z undoes the whole merge.']
    return '\n'.join(lines)


# ---------------------------------------------------------------- command plumbing

class _CommandCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        global _plan, _report
        try:
            cmd = args.command
            cmd.isAutoExecute = True  # no dialog; the message boxes are the UI
            _report = ''
            _plan = _prepare()
            on_execute = _ExecuteHandler()
            cmd.execute.add(on_execute)
            _cmd_handlers.append(on_execute)
            on_destroy = _DestroyHandler()
            cmd.destroy.add(on_destroy)
            _cmd_handlers.append(on_destroy)
        except Exception:
            _plan = None
            _ui.messageBox('Failed:\n{}'.format(traceback.format_exc()), TITLE)


class _ExecuteHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        global _report
        if _plan is None:
            return  # cancelled or nothing to merge
        try:
            design = adsk.fusion.Design.cast(_app.activeProduct)
            _report = _apply(design, _plan)
        except Exception:
            _report = 'Failed:\n{}'.format(traceback.format_exc())


class _DestroyHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        global _plan, _report
        try:
            if _report:
                _ui.messageBox(_report, TITLE)
        finally:
            _plan = None
            _report = ''
            _cmd_handlers.clear()
