# RPY110 true positives — actual Python syntax errors in `$` and `python:` blocks.
# These MUST fire RPY110 (the rule exists for these cases).

label start:
    # Real syntax error: missing closing paren.
    $ my_dict = {"key": "value"
    return
