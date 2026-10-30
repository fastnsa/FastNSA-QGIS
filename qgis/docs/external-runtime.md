# Set Up FastNSA

FastNSA uses the `fastnsa` Python package to run its analyses.

- **Self-contained Windows or Linux ZIP:** FastNSA is already included. You
  usually do not need to install anything else.
- **Source-only ZIP:** install `fastnsa==0.3.0` by following the steps below.

The plugin does not install packages for you. Matplotlib is optional: it adds
interactive 3D views, but is not needed for maps, tables, or 2D charts.

## 1. Check Your QGIS Installation

Open **Plugins > FastNSA > Runtime setup**. The **Installation status** tab
shows your QGIS and Python versions, the detected FastNSA installation, and
anything that needs attention.

You need Windows AMD64 or Linux x86_64, QGIS 3.34 through 3.x with Qt5,
Python 3.11 or newer, and NumPy 1.23.5 or newer. macOS and QGIS 4/Qt6 are not
supported in this version.

Use the Python that belongs to QGIS for the commands below. Installing into
an unrelated Python environment will not make FastNSA available to QGIS.
On Windows, use your QGIS installation's OSGeo4W Shell. On Linux, use the
Python for your QGIS installation, or activate its Conda environment.

If NumPy is missing or too old, repair your QGIS installation or environment.
Do not replace QGIS's NumPy, Qt, or GDAL just to install FastNSA.

## 2. Install FastNSA

Choose the instructions for your system. Run the commands in a terminal,
not in the QGIS Python Console.

For a first installation, QGIS can stay open. Before updating an installation
that QGIS has already used, save your work and close QGIS first.

### Windows

Open the **OSGeo4W Shell** supplied with your QGIS installation. Check that
`python --version` matches the Python version shown in Runtime setup.

```bat
python --version
python -m pip install --only-binary=:all: --no-deps --target "%APPDATA%\FastNSA\runtime-0.3.0" "fastnsa==0.3.0"
```

This installs FastNSA into your user folder without replacing QGIS's packages.

### Linux

Use QGIS's Python. If your QGIS installation uses `python3`:

```bash
python3 --version
python3 -m pip install --only-binary=:all: --no-deps \
  --target "$HOME/.local/share/FastNSA/runtime-0.3.0" "fastnsa==0.3.0"
```

The installation folder is `~/.local/share/FastNSA/runtime-0.3.0`.

### QGIS Installed with Conda

Activate the environment containing QGIS:

```bash
conda activate <your-qgis-environment>
python -m pip install --only-binary=:all: --no-deps "fastnsa==0.3.0"
```

These commands install only FastNSA. They rely on QGIS already having a
compatible NumPy version. If the command reports that pip is missing, use
your QGIS distribution or environment manager to obtain it. Do not use
`sudo pip`, `--break-system-packages`, or an arbitrary downloaded Python
installer to change QGIS's environment.

## 3. Enable the Analysis Tools

1. Return to **Runtime setup**.
2. Leave **Custom installation folder** empty and click **Check again**.
3. When FastNSA is ready, open it from the toolbar or plugin menu. The four
   algorithms are also available under **Processing Toolbox > FastNSA**.

The Windows and Linux folders above are found automatically. FastNSA can also
be found in QGIS's Python environment. If an old custom folder is still
entered, clear it and click **Save and enable** to return to automatic setup.

**Installed somewhere else?** Click **Browse**, choose the folder containing
the `fastnsa` folder, and click **Save and enable**. Do not choose the inner
`fastnsa` folder itself. Use the folder picker rather than entering an
environment variable such as `%APPDATA%`.

First-time setup normally needs no restart. If QGIS is already using another
FastNSA installation, the new folder is saved for the next start. Finish or
cancel any running analysis, save your project, and restart QGIS.

## Updating or Changing Installation Type

Save your work and restart QGIS after updating the plugin. If installation
succeeds but the FastNSA menu is missing, first restart QGIS and check that
FastNSA is enabled under **Plugins > Manage and Install Plugins > Installed**.

To change from a self-contained ZIP to a source-only ZIP:

1. Uninstall the old plugin and close QGIS.
2. Reopen QGIS and install the source-only ZIP.
3. Install FastNSA separately using the instructions above, if needed.
4. Open **Runtime setup** and click **Check again**.

Install only one type in each QGIS profile. The self-contained ZIP always uses
its included FastNSA package; a custom folder does not replace it.

If setup reports old files inside the plugin folder, they are ignored unless
QGIS has already loaded them. You can continue with a separate installation.
To remove the old files, uninstall the plugin, close QGIS, and reinstall the
source-only ZIP. The plugin does not delete these files for you.

## If Setup Does Not Work

| Message or problem | What to do |
| --- | --- |
| FastNSA was not found | Check that the install command finished successfully. Clear any old custom folder, then click **Save and enable**. |
| A different FastNSA version was found | Install `fastnsa==0.3.0` into a new folder, select that folder, and restart QGIS if requested. |
| The analysis library cannot load | Check that you downloaded the right package for your operating system and CPU. Your system also needs a compatible C++ runtime. |
| A restart is requested | Save your project and restart QGIS. Do not delete or replace files while QGIS is using them. |
| No compatible package is available | Check the supported systems above. Do not install a package intended for another platform. |
| A custom library environment setting is reported | Remove the named setting from your QGIS launch environment, then restart QGIS. |

If you need help, copy the message and **Details for support** from
**Installation status**, and include your QGIS and plugin versions in
[GitHub Issues](https://github.com/fastnsa/FastNSA-QGIS/issues). Review local
paths before sharing them publicly.

The FastNSA package and its source are available on
[PyPI](https://pypi.org/project/fastnsa/0.3.0/).
