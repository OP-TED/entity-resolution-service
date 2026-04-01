import json
from pathlib import Path

from ers.curation.entrypoints.api.app import create_app as create_curation_app
from ers.ers_rest_api.entrypoints.api.app import create_app as create_ers_rest_api_app


def export(app_factory, output_path: Path) -> None:
    app = app_factory()

    schema = app.openapi()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w") as f:
        json.dump(schema, f, indent=2)

    print(f"OpenAPI schema written to {output_path}")


def main() -> None:
    export(
        create_curation_app,
        Path("resources/curation-openapi-schema.json"),
    )

    export(
        create_ers_rest_api_app,
        Path("resources/ers-openapi-schema.json"),
    )


if __name__ == "__main__":
    main()
