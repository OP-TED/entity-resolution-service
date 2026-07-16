from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import Field

from ers.commons.domain.data_transfer_objects import ERSResponse
from ers.ers_rest_api.entrypoints.api.dependencies import get_rdf_config
from ers.rdf_mention_parser.domain.rdf_mapping_config import RDFMappingConfig

router = APIRouter(tags=["Health"])


class EntityTypeInfo(ERSResponse):
    """A supported entity type exposed by this ERS instance."""

    name: str = Field(
        description="Human-readable name of the entity type (e.g. 'person', 'organization')."
    )
    rdf_type: str = Field(description="RDF class URI mapped to this entity type.")


class HealthResponse(ERSResponse):
    """Response model for the health endpoint."""

    status: str = Field(description="Service liveness status; always 'ok' when the service is up.")
    supported_entity_types: list[EntityTypeInfo] = Field(
        description="List of entity types this ERS instance is configured to resolve."
    )


@router.get(
    "/health",
    description="Returns service liveness status and the entity types supported by this ERS instance.",
)
async def health(
    rdf_config: Annotated[RDFMappingConfig, Depends(get_rdf_config)],
) -> HealthResponse:
    return HealthResponse(
        status="ok",
        supported_entity_types=[
            EntityTypeInfo(name=name, rdf_type=cfg.rdf_type)
            for name, cfg in rdf_config.entity_types.items()
        ],
    )
