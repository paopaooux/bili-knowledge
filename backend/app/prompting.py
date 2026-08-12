from pathlib import Path


def render_prompt(path: Path, **values: object) -> str:
    content = path.read_text(encoding="utf-8")
    for key, value in values.items():
        content = content.replace("{{" + key + "}}", str(value))
    return content.strip()
