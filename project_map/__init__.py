import json
from typing import List, Dict
import re

_MAP_DATA = None

def load_map() -> List[Dict]:
    """Load the project map from file."""
    global _MAP_DATA
    if _MAP_DATA is None:
        try:
            with open('project_map.json', 'r') as f:
                _MAP_DATA = json.load(f)
        except FileNotFoundError:
            _MAP_DATA = []
    return _MAP_DATA

def find_files_by_keyword(keyword: str) -> List[str]:
    """Find files containing the keyword in their summary or symbols."""
    map_data = load_map()
    matching_paths = [
        item['path'] 
        for item in map_data 
        if keyword.lower() in item['summary'].lower() 
           or any(keyword.lower() in symbol['name'].lower() for symbol in item['symbols'])
    ]
    return list(set(matching_paths))  # Remove duplicates

def get_symbols(file_path: str) -> List[Dict]:
    """Get all symbols (functions/classes) from a specific file."""
    map_data = load_map()
    for item in map_data:
        if item['path'] == file_path:
            return item['symbols']
    return []

def search_symbols(name_pattern: str) -> List[Dict]:
    """Search symbols by name pattern (regex)."""
    map_data = load_map()
    results = []
    for item in map_data:
        for symbol in item['symbols']:
            if re.search(name_pattern, symbol['name']):
                results.append({**symbol, 'file': item['path']})
    return results

def refresh_project_map(root_dir: str = ".") -> None:
    """
    Regenerate `project_map.json` on‑demand.

    Parameters
    ----------
    root_dir: str
        Directory that contains the source tree. Defaults to the current working dir.
    """
    # Import locally to avoid circular imports if this module is loaded early
    from scripts.generate_project_map import generate_project_map
    generate_project_map(root_dir=root_dir)