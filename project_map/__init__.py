import json
from typing import List, Dict, Optional
import re
import os

_MAP_DATA_CACHE: Dict[str, List[Dict]] = {} # Cache per root_dir

def load_map(root_dir: str) -> List[Dict]:
    """Load the project map from file for a given root directory."""
    global _MAP_DATA_CACHE
    if root_dir in _MAP_DATA_CACHE:
        return _MAP_DATA_CACHE[root_dir]

    map_file_path = os.path.join(root_dir, 'project_map.json')
    try:
        with open(map_file_path, 'r') as f:
            _MAP_DATA_CACHE[root_dir] = json.load(f)
    except FileNotFoundError:
        _MAP_DATA_CACHE[root_dir] = [] # Cache empty list if file not found
    except json.JSONDecodeError:
        _MAP_DATA_CACHE[root_dir] = [] # Cache empty list if JSON is invalid
    return _MAP_DATA_CACHE[root_dir]

def find_files_by_keyword(keyword: str, root_dir: str) -> List[str]:
    """Find files containing the keyword in their summary or symbols."""
    map_data = load_map(root_dir)
    matching_paths = [
        item['path'] 
        for item in map_data 
        if keyword.lower() in item['summary'].lower() 
           or any(keyword.lower() in symbol['name'].lower() for symbol in item['symbols'])
    ]
    return list(set(matching_paths))  # Remove duplicates

def get_symbols(file_path: str, root_dir: str) -> List[Dict]:
    """Get all symbols (functions/classes) from a specific file."""
    map_data = load_map(root_dir)
    for item in map_data:
        if item['path'] == file_path:
            return item['symbols']
    return []

def search_symbols(name_pattern: str, root_dir: str) -> List[Dict]:
    """Search symbols by name pattern (regex)."""
    map_data = load_map(root_dir)
    results = []
    for item in map_data:
        for symbol in item['symbols']:
            if re.search(name_pattern, symbol['name']):
                results.append({**symbol, 'file': item['path']})
    return results

def refresh_project_map(root_dir: str = ".") -> None:
    """
    Regenerate `project_map.json` on‑demand and clear cache for that root_dir.

    Parameters
    ----------
    root_dir: str
        Directory that contains the source tree. Defaults to the current working dir.
    """
    # Clear cache for this root_dir before regenerating
    global _MAP_DATA_CACHE
    if root_dir in _MAP_DATA_CACHE:
        del _MAP_DATA_CACHE[root_dir]

    # Import locally to avoid circular imports if this module is loaded early
    from scripts.generate_project_map import generate_project_map
    generate_project_map(root_dir=root_dir)