🧪 Add tests for forcefocus_cli.cmd_web

🎯 **What:** The `cmd_web` function in `forcefocus_cli.py` lacked unit tests.

📊 **Coverage:** The new `TestForceFocusCLICmdWeb` class tests:
* Starting the web interface when the primary script exists in `/usr/local/bin`
* Starting the web interface when the primary script is missing, falling back to the directory containing the CLI script
* Providing a helpful error message when the web script isn't found anywhere
* Stopping the web interface and correctly handling the `stop` action

✨ **Result:** Enhanced test coverage ensures that CLI commands to start/stop the web interface are thoroughly tested and verified.
