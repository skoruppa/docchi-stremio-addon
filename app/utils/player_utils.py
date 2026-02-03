"""
Player utilities including domain mapping and detection.
"""

import importlib
import os


def _collect_player_info():
    """Collect domains, names and handler functions from enabled player modules."""
    player_domains = {}
    player_names = {}
    player_handlers = {}
    players_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'players')
    
    for filename in os.listdir(players_dir):
        if not filename.endswith('.py') or filename.startswith('_') or filename == 'test.py':
            continue
        
        module_name = filename[:-3]
        try:
            module = importlib.import_module(f'app.players.{module_name}')
            
            # Skip disabled players (default is enabled if ENABLED is not defined)
            if hasattr(module, 'ENABLED') and not getattr(module, 'ENABLED'):
                continue
            
            # Collect domains
            if hasattr(module, 'DOMAINS'):
                domains = getattr(module, 'DOMAINS')
                if domains:
                    player_domains[module_name] = domains
            
            # Collect names (default to module name)
            if hasattr(module, 'NAMES'):
                names = getattr(module, 'NAMES')
            else:
                names = [module_name]
            player_names[module_name] = names
            
            # Collect handler function
            handler_name = f'get_video_from_{module_name}_player'
            if hasattr(module, handler_name):
                player_handlers[module_name] = getattr(module, handler_name)
                
        except Exception:
            pass
    
    return player_domains, player_names, player_handlers


# Collect domains, names and handlers from enabled players
PLAYER_DOMAINS, PLAYER_NAMES, PLAYER_HANDLERS = _collect_player_info()


def detect_player(player_obj: dict) -> str:
    """
    Detect player name from player object.
    Uses player URL, player_hosting field, and NAMES list.
    Returns player name or 'default' if not found.
    """
    url = player_obj.get('player', '').lower()
    player_hosting = player_obj.get('player_hosting', '').lower()
    
    # Try domain matching first
    for player_name, domains in PLAYER_DOMAINS.items():
        for domain in domains:
            if domain in url:
                return player_name
    
    # Try player_hosting against NAMES
    for player_name, names in PLAYER_NAMES.items():
        if player_hosting in names:
            return player_name

    # Fallback: try to match any name in URL
    for player_name, names in PLAYER_NAMES.items():
        for name in names:
            if name in url:
                return player_name
    
    return 'default'


def get_player_handler(player_name: str):
    """Get handler function for a player by name."""
    return PLAYER_HANDLERS.get(player_name)
