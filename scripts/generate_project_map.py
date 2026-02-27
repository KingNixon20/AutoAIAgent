
import os
import json
from pathlib import Path
import ast
import re

def generate_project_map(root_dir='.'):
    root_dir = str(Path(root_dir).resolve())
    map_data = []
    ignored_dirs = {'.git', 'node_modules', '__pycache__', '*.md'}

    for dirpath, _, filenames in os.walk(root_dir):
        if any(ignored in dirpath for ignored in ignored_dirs):
            continue

        for filename in filenames:
            file_path = Path(dirpath)/filename
            if not file_path.is_file():
                continue

            # Determine language from extension
            lang = 'python' if file_path.suffix == '.py' else 'javascript'
            
            try:
                with open(file_path, 'r') as f:
                    content = f.read()
            except Exception as e:
                continue

            # Extract summary (first 5 lines)
            summary_lines = [line.strip() for line in content.split('\n')[:5] if line.strip()]
            summary = '\n'.join(summary_lines) if summary_lines else 'No summary'

            # Collect symbols
            symbols = []
            if lang == 'python':
                tree = ast.parse(content)
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                        name = node.name
                        line = content.find(name) + 1
                        symbols.append({'name': name, 'type': 'function' if isinstance(node, ast.FunctionDef) else 'class', 'line': line})
            elif lang == 'javascript':
                # Basic regex for function/class detection (simplified)
                func_match = re.finditer(r'function\s+([a-zA-Z_][a-zA-Z0-9_]*)', content)
                class_match = re.finditer(r'class\s+([a-zA-Z_][a-zA-Z0-9_]*)', content)
                for match in func_match:
                    symbols.append({'name': match.group(1), 'type': 'function', 'line': content.find(match.group(1)) + 1})
                for match in class_match:
                    symbols.append({'name': match.group(1), 'type': 'class', 'line': content.find(match.group(1)) + 1})

            map_data.append({
                'path': str(file_path.resolve()),
                'summary': summary,
                'symbols': symbols
            })

    # Write to project_map.json
    map_file_path = Path(root_dir) / 'project_map.json'
    with open(map_file_path, 'w') as f:
        json.dump(map_data, f, indent=2)

if __name__ == '__main__':
    generate_project_map()
