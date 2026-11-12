"""Schedule once on the GUI thread after the current button callback returns."""
def defer(callback):
    import nuke
    if nuke.NUKE_VERSION_MAJOR >= 16:
        from PySide6.QtCore import QTimer
    else:
        from PySide2.QtCore import QTimer
    QTimer.singleShot(0, callback)
