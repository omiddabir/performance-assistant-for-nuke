import nuke
import nuke_performance_assistant
from nuke_performance_assistant.environment import env_value
if env_value(nuke, 'gui', False):
    nuke.menu('Nuke').addCommand('Tools/Performance Assistant', nuke_performance_assistant.show)
