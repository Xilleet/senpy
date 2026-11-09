init python:
    # a_caller.rpy loads BEFORE z_definer.rpy (alphabetical order).
    # setup_gui() is called here at init time, but the function is
    # defined in z_definer.rpy which Ren'Py loads later. This is the
    # exact hazard RPY109 is designed to catch.
    setup_gui()
