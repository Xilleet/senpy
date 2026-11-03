# RPY802 requires 2+ files in the same language directory with
# different translations for the same source string.
#
# The test framework (test_fixtures.py) copies only one .rpy file to
# tmp_path/game/, so RPY802 cannot be triggered in CI with the current
# fixture infrastructure. This fixture documents the bad case but will
# produce 0 RPY802 diagnostics.
#
# To properly test RPY802, we would need to extend test_fixtures.py to
# copy multiple files into a language directory structure:
#   tmp_path/game/tl/russian/common.rpy
#   tmp_path/game/tl/russian/dialogue.rpy
# with different `new` translations for the same `old` string.
#
# RPY802 IS covered by unit tests in test_rules_rpy7xx.py (or a new
# test_rules_rpy8xx.py) that build the multi-file structure directly.
#
# For now, this fixture is a placeholder that produces 0 RPY802 diags.

translate russian chapter1_a1b2:
    old "Hello"
    new "Privet"

translate russian chapter1_c3d4:
    old "Hello"
    new "Privet"
