from __future__ import annotations

import ast
from dataclasses import dataclass, field

from senpy.core.logging import get_logger

_logger = get_logger("signature")


@dataclass
class SignatureInfo:
    min_args: int = 0
    max_args: float = 0.0
    has_varargs: bool = False
    has_varkwargs: bool = False
    required_names: set[str] = field(default_factory=set)
    all_names: set[str] = field(default_factory=set)
    has_params: bool = False
    pos_names: list[str] = field(default_factory=list)


def parse_signature(param_str: str | None) -> SignatureInfo:
    """Parses the parameter string 'a, b=1, *args, **kwargs' via AST."""
    if not param_str or not param_str.strip():
        return SignatureInfo()

    clean = param_str.strip()
    try:
        tree = ast.parse(f"def _d({clean}): pass")
        args_node = tree.body[0].args  # type: ignore

        all_names = {a.arg for a in args_node.args + args_node.kwonlyargs}
        defaults_len = len(args_node.defaults)
        pos_args_len = len(args_node.args)
        num_required_pos = pos_args_len - defaults_len

        required_names = {args_node.args[i].arg for i in range(num_required_pos)}
        for a, d in zip(args_node.kwonlyargs, args_node.kw_defaults):
            if d is None:
                required_names.add(a.arg)

        has_varargs = args_node.vararg is not None
        has_varkwargs = args_node.kwarg is not None
        max_args = float("inf") if has_varargs else float(pos_args_len)

        pos_names = [a.arg for a in args_node.args]
        return SignatureInfo(
            min_args=num_required_pos,
            max_args=max_args,
            has_varargs=has_varargs,
            has_varkwargs=has_varkwargs,
            required_names=required_names,
            all_names=all_names,
            has_params=True,
            pos_names=pos_names,
        )
    except (SyntaxError, ValueError, TypeError) as e:
        # log debug instead of silent suppress. Caller gets fallback
        # SignatureInfo below, but the failure is now observable for debugging.
        _logger.debug("signature parse failed for %r: %s", param_str, e)

    return SignatureInfo(
        has_params=True, max_args=float("inf"), has_varargs=True, has_varkwargs=True
    )


def parse_call_args(args_str: str) -> tuple[int, set[str], bool, bool] | None:
    """Parses the passed call arguments: (num_positional, passed_kwargs, has_*args, has_**kwargs)."""
    clean = args_str.strip()
    try:
        tree = ast.parse(f"_d({clean})")
        call = tree.body[0].value  # type: ignore
        if isinstance(call, ast.Call):
            num_pos = len(call.args)
            has_star = any(isinstance(a, ast.Starred) for a in call.args)
            kwargs = {kw.arg for kw in call.keywords if kw.arg is not None}
            has_star_kw = any(kw.arg is None for kw in call.keywords)
            return num_pos, kwargs, has_star, has_star_kw
    except (SyntaxError, ValueError, TypeError) as e:
        # log debug instead of silent suppress.
        _logger.debug("call args parse failed for %r: %s", args_str, e)
    return None


def validate_call_arguments(sig: SignatureInfo, args_str: str | None) -> str | None:
    """Checks the passed arguments against the signature. Returns the error text or None."""
    if not sig.has_params:
        # The object has no parameters
        if args_str and args_str.strip():
            parsed = parse_call_args(args_str)
            if parsed and (parsed[0] > 0 or parsed[1]):
                return "takes no arguments, but arguments were provided"
        return None

    if args_str is None or not args_str.strip():
        # A call without parentheses or empty parentheses ()
        if sig.min_args > 0:
            return f"requires at least {sig.min_args} argument(s), but none were given"
        return None

    parsed = parse_call_args(args_str)
    if not parsed:
        return None

    num_pos, kwargs, has_star, has_star_kw = parsed
    if has_star or has_star_kw:
        return None  # Dynamic unpacking (*args, **kwargs), skip strict check

    # 1+2: positional count and unknown kwargs
    err = _check_arg_counts_and_kwargs(sig, num_pos, kwargs)
    if err:
        return err

    # 3+4: required coverage and positional/keyword overlap
    return _check_required_args_and_overlap(sig, num_pos, kwargs)


def _check_arg_counts_and_kwargs(
    sig: SignatureInfo,
    num_pos: int,
    kwargs: set[str],
) -> str | None:
    """Check (1) extra positional args beyond max_args and (2) unknown named kwargs."""
    # 1. Extra positional arguments
    if not sig.has_varargs and num_pos > sig.max_args:
        return f"takes at most {int(sig.max_args)} argument(s), but {num_pos} were provided"

    # 2. Unknown named parameters
    if not sig.has_varkwargs:
        unexpected = kwargs - sig.all_names
        if unexpected:
            first = min(unexpected)
            return f"got unexpected keyword argument '{first}'"

    return None


def _check_required_args_and_overlap(
    sig: SignatureInfo,
    num_pos: int,
    kwargs: set[str],
) -> str | None:
    """Check (3) coverage of required parameters and (4) positional/keyword duplication."""
    covered_by_pos = set(sig.pos_names[:num_pos])
    all_provided = covered_by_pos | kwargs

    # 3. Check coverage of required parameters
    missing = sig.required_names - all_provided
    if missing:
        missing_sorted = sorted(missing)
        return f"missing required argument '{missing_sorted[0]}'"

    # 4. Check for a positional argument duplicated via a keyword
    duplicated = covered_by_pos & kwargs
    if duplicated:
        return f"got multiple values for argument '{min(duplicated)}'"

    return None
