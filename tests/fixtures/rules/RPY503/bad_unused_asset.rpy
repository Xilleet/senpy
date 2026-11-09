# This fixture documents the RPY503 bad case.
# In a real project, this would be:
#   game/images/unused_background.png  (exists, never referenced)
#   game/script.rpy  (does not show unused_background)
#
# The test framework copies only .rpy files to tmp_path/game/, so
# no image files exist in the test environment. RPY503 fires only
# when an image file is on disk but unreferenced — which means
# this fixture produces 0 diagnostics in CI.
#
# To properly test RPY503, we would need to extend test_fixtures.py
# to also copy a placeholder image file. Tracked as a follow-up.
label start:
    "No image references here."
    return
