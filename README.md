# Nuke Performance Assistant

**English** · [فارسی](START_HERE_FA.md)

Configure Nuke for the workstation you’re using. Performance Assistant reads your CPU, RAM, GPU memory and free cache space, then shows the proposed changes alongside Nuke’s current settings. Everything runs locally.

**0.5.2 Preview** · Maintainer: Omid Dabirsiaghi · [Download the install ZIP](https://github.com/omiddabir/performance-assistant-for-nuke/raw/refs/heads/main/archives/Nuke_Performance_Assistant_v0.5.2_preview.zip)

## Install

1. Close Nuke and extract the ZIP. Copy the entire **nuke-performance-assistant** folder into your user **.nuke** directory. On Windows this is usually `%USERPROFILE%\.nuke`.
2. Add the following lines once to **.nuke/init.py**. Create that file if it does not exist.

```python
import nuke
nuke.pluginAddPath('./nuke-performance-assistant')
```

3. Keep the included **init.py** and **menu.py** inside the plugin folder. Restart Nuke and open **Tools → Performance Assistant**.

To update an existing installation, close Nuke and replace the plugin folder. Your saved presets live separately.

## Choose a preset

- **Shared** reserves resources for other applications working alongside Nuke.
- **Comp focused** makes all available logical CPU threads available to Nuke and recommends larger cache budgets.
- **User preset** and custom presets let you choose and save your own settings.

**Auto configure** works in Shared and Comp focused. Review its suggestions, edit any values, then choose **Apply** to save them in Nuke. **Save preset** saves the profile separately. Stop active renders before applying changes and restart Nuke if prompted.

## Compatibility and feedback

Target versions are Nuke 13–17. Windows checks include Nuke 15.1v2 and 17.1v1. Coverage varies by version and hardware. The independent timeline playback cache is configured in Nuke Preferences on builds without a verified mapping.

For feedback, include your Nuke version, operating system, selected preset, and expected and observed values. Review local paths in diagnostics before sharing. See the [compatibility notes](docs/COMPATIBILITY.md) and [MIT license](LICENSE).
