init python:
    # z_definer.rpy loads AFTER a_caller.rpy (alphabetical order).
    # setup_gui() is defined here, but a_caller.rpy already tried to
    # call it at init time — NameError at startup.
    def setup_gui():
        pass
