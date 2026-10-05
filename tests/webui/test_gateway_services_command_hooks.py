"""I comandi delle impostazioni ricevono i ganci del gateway.

``settings.provider.update`` e ``telegram.save`` hanno preso il posto di due rotte
GET che, dopo il salvataggio, rimettevano in servizio a caldo il provider e il
canale Telegram. Senza i ganci nel ``CommandContext`` i comandi salvano e basta:
la chiave nuova entra in servizio solo al riavvio.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from jafta.channels.websocket import WebSocketConfig
from jafta.webui.gateway_services import build_gateway_services


def test_command_context_carries_the_settings_hooks(tmp_path: Path) -> None:
    on_settings = MagicMock()
    on_telegram = MagicMock()
    services = build_gateway_services(
        config=WebSocketConfig.model_validate({}),
        bus=MagicMock(),
        session_manager=None,
        workspace_path=tmp_path,
        default_restrict_to_workspace=False,
        runtime_model_name=None,
        on_settings_changed=on_settings,
        on_telegram_changed=on_telegram,
    )

    assert services.commands.on_settings_changed is on_settings
    assert services.commands.on_telegram_changed is on_telegram
