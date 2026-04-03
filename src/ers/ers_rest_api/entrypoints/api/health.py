from typing import Annotated

from fastapi import APIRouter, Depends

from ers.commons.domain.data_transfer_objects import ERSResponse
from ers.ers_rest_api.entrypoints.api.dependencies import get_rdf_config
from ers.rdf_mention_parser.domain.rdf_mapping_config import RDFMappingConfig

router = APIRouter(tags=["Health"])


class EntityTypeInfo(ERSResponse):
    """A supported entity type exposed by this ERS instance."""

    name: str
    rdf_type: str


class HealthResponse(ERSResponse):
    """Response model for the health endpoint."""

    status: str
    supported_entity_types: list[EntityTypeInfo]


@router.get("/health")
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
