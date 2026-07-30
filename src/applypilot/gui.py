"""ApplyPilot GUI launcher — starts the web dashboard and opens the browser.

This is the entry point for non-technical users. It launches the Flask
web server and automatically opens the default browser to the setup page
if the system hasn't been configured yet, or to the dashboard otherwise.

Usage:
    applypilot-gui          # via pip install
    python -m applypilot.gui
    applypilot-gui --no-browser  # don't open browser
    applypilot-gui --port 8080   # custom port
"""

import os
import sys
import time
import webbrowser
import threading
from pathlib import Path

import typer

app = typer.Typer(name="applypilot-gui", help="ApplyPilot desktop interface")


def _is_configured() -> bool:
    """Check if the user has completed initial setup."""
    from applypilot.config import APP_DIR, PROFILE_PATH, RESUME_PATH, SEARCH_CONFIG_PATH
    return PROFILE_PATH.exists() and RESUME_PATH.exists() and SEARCH_CONFIG_PATH.exists()


def _open_browser(url: str, delay: float = 1.0) -> None:
    """Open the default browser after a short delay (wait for Flask to start)."""
    time.sleep(delay)
    webbrowser.open(url)


def main(
    port: int = 5050,
    host: str = "127.0.0.1",
    no_browser: bool = False,
    debug: bool = True,
) -> None:
    """Launch the ApplyPilot web interface.

    Automatically opens the default browser. Goes to /setup if the system
    hasn't been configured yet, or to the dashboard otherwise.
    """
    from applypilot.config import load_env, ensure_dirs
    from applypilot.database import init_db

    load_env()
    ensure_dirs()

    try:
        init_db()
    except Exception:
        pass

    from applypilot.web import create_app
    flask_app = create_app()
    flask_app.config["APPLYPILOT_PORT"] = port

    url = f"http://{host}:{port}"

    if _is_configured():
        url += "/"
    else:
        url += "/setup"
        print()
        print("  ========================================")
        print("  Bem-vindo ao ApplyPilot!")
        print("  Vamos configurar seu perfil no navegador.")
        print("  ========================================")
        print()

    if not no_browser:
        threading.Thread(target=_open_browser, args=(url,), daemon=True).start()

    print(f"  Servidor rodando em {url}")
    print(f"  Pressione Ctrl+C para parar.")
    print()

    flask_app.run(host=host, port=port, debug=debug, use_reloader=False)


@app.command()
def launch(
    port: int = typer.Option(5050, "--port", "-p", help="Port to run the web server on."),
    host: str = typer.Option("127.0.0.1", "--host", help="Host to bind to."),
    no_browser: bool = typer.Option(False, "--no-browser", help="Don't open the browser automatically."),
) -> None:
    """Launch the ApplyPilot desktop interface."""
    main(port=port, host=host, no_browser=no_browser)


if __name__ == "__main__":
    app()
